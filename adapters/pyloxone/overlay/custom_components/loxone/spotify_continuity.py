"""
Opt-in room-owned Spotify resume using the existing HA OAuth2 session.

No context reconstruction, seek, token access or write retries.
Detached owned sessions use exact-device activation, matching, then separate Play.
Queue tuples below are provider previews, NOT the entire remote queue.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import hashlib
import json
import logging
import os
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any
from uuid import uuid4


from homeassistant.config_entries import ConfigEntryState
from homeassistant.util import dt as dt_util
from pyloxone_audio.spotify import NativeSessionUnavailableError, SpotifyNativeSession, async_resume_native_session

from .pyloxone_api.audioserver import AudioCommandError
from .audio_sources import environment as source_environment, source_matches


if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from datetime import datetime
    from aiohttp import ClientHandlerType, ClientRequest, ClientResponse
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.config_entry_oauth2_flow import OAuth2Session
    from .audio_catalogue import CatalogueTarget
    from .pyloxone_api.audioserver import AudioServerCommands, AudioZoneMetadata

CONF_SPOTIFY_RETURN = "audioserver_spotify_return"
_API = "https://api.spotify.com/v1/"
_MAX_AGE = 90
_STORE = "pyloxone_spotify_return"
_ROOM_FENCES = "pyloxone_spotify_return_room_fences"
_MAX_BINDINGS = 128
_MAX_QUEUE_PREVIEW = 1000
_MAX_DEVICES = 128
_HTTP_OK = 200
_HTTP_NO_CONTENT = 204
_NATIVE_FRESH_SECONDS = 5
_POSITION_TOLERANCE_MS = 3000
_LIBRARY_CLOCK_OBSERVATION_SECONDS = 0.05
_ACTIVATION_MATCHES = 2
_DISPATCH_RESTORED = "pyloxone_spotify_return_dispatch_restored"
_DISPATCH_RESTORE_LOCK = "pyloxone_spotify_return_dispatch_restore_lock"
_DISPATCH_RESTORE_FAILED = "pyloxone_spotify_return_dispatch_restore_failed"
_MAX_DURABLE_FENCES = 1024
_MAX_DURABLE_FENCE_BYTES = 2048
_LOGGER = logging.getLogger(__name__)
_BINDING_ID_PATTERN = r"[A-Za-z0-9_-]{1,128}"
_SPOTIFY_USER_ID_PATTERN = r"[A-Za-z0-9_.@+-]{1,128}"


def _literal(value: object, pattern: str) -> str:
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        msg = "Invalid literal Spotify return identity"
        raise ValueError(msg)
    return value


@dataclass(frozen=True)
class SpotifyBinding:
    """Owner-selected HA entry/account and exact native-room receiver."""

    entry_id: str
    user_id: str
    account_id: str
    device_id: str

    @classmethod
    def parse(cls, value: object) -> SpotifyBinding:
        """Reject malformed/extra fields rather than guessing a receiver."""
        if not isinstance(value, dict) or set(value) != {"entry_id", "user_id", "account_id", "device_id"}:
            msg = "Spotify return requires an explicit entry/user/account/device binding"
            raise ValueError(msg)
        return cls(
            _literal(value["entry_id"], _BINDING_ID_PATTERN),
            _literal(value["user_id"], _SPOTIFY_USER_ID_PATTERN),
            _literal(value["account_id"], _SPOTIFY_USER_ID_PATTERN),
            _literal(value["device_id"], _BINDING_ID_PATTERN),
        )


@dataclass(frozen=True)
class SpotifyBookmark:
    """Fresh ownership evidence; never used as a replacement playback body."""

    track: str
    context: str | None
    progress_ms: int
    shuffle: bool
    repeat: str
    queue: tuple[str, ...]
    captured: float
    native_user: str
    dispatch_id: str = field(default_factory=lambda: uuid4().hex)


@dataclass(frozen=True)
class _ActivationState:
    """Keep causal and settled observations, never rebase them during preparation."""

    sent_at: datetime
    progress_ms: int
    native: AudioZoneMetadata


def _room_fence_path(root: Path, room: str, player: int) -> Path:
    identity = json.dumps([room, player], separators=(",", ":"))
    return root / ("fence-" + hashlib.sha256(identity.encode()).hexdigest() + ".lock")


def _write_dispatch_marker(directory: str, identity: str, action: str, fence: dict) -> None:
    """Consume one dispatch before transport, including cancellation/restart ambiguity."""
    root = Path(directory)
    parents = [root.parent]
    while not parents[-1].exists():
        parents.append(parents[-1].parent)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    for parent in reversed(parents):
        descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    fence_path = _room_fence_path(root, fence["room"], fence["player"])
    try:
        fence_descriptor = os.open(fence_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if json.loads(fence_path.read_text()) != fence:
            msg = "An unreconciled room dispatch already exists"
            raise FileExistsError(msg) from None
    else:
        with os.fdopen(fence_descriptor, "w") as stream:
            json.dump(fence, stream)
            stream.flush()
            os.fsync(stream.fileno())
    name = hashlib.sha256((identity + ":" + action).encode()).hexdigest() + ".json"
    descriptor = os.open(root / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump({"version": 1, "action": action, "dispatch_may_have_occurred": True}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _clear_dispatch_fence(directory: str, fence: dict) -> None:
    """Reconcile only this attempt after positively observed complete restoration."""
    root = Path(directory)
    path = _room_fence_path(root, fence["room"], fence["player"])
    if json.loads(path.read_text()) != fence:
        msg = "Spotify dispatch reconciliation identity changed"
        raise OSError(msg)
    # Positive remote confirmation precedes this local commit point. Once the
    # namespace mutation succeeds, do not classify the resolved action as an
    # uncertain dispatch just because persisting its cleanup fails. A power loss
    # may resurrect the older fence; that conservatively blocks, never replays.
    path.unlink()
    try:
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        _LOGGER.debug("Spotify return confirmed; fence cleanup durability is unverified")


def _read_dispatch_fences(directory: str) -> list[dict]:
    """Read bounded non-secret uncertainty identities, never old bookmarks."""
    root = Path(directory)
    if not root.exists():
        return []
    result = []
    for path in root.glob("fence-*.lock"):
        if len(result) >= _MAX_DURABLE_FENCES or path.stat().st_size > _MAX_DURABLE_FENCE_BYTES:
            msg = "Spotify dispatch journal is outside the supported bound"
            raise ValueError(msg)
        fence = json.loads(path.read_text())
        if (
            not isinstance(fence, dict)
            or set(fence) != {"version", "room", "player", "user", "device", "attempt"}
            or fence["version"] != 1
            or type(fence["player"]) is not int
            or fence["player"] <= 0
        ):
            msg = "Spotify dispatch journal is invalid"
            raise ValueError(msg)
        _literal(fence["room"], _BINDING_ID_PATTERN)
        _literal(fence["user"], _SPOTIFY_USER_ID_PATTERN)
        _literal(fence["device"], _BINDING_ID_PATTERN)
        _literal(fence["attempt"], r"[A-Za-z0-9_.-]{1,128}")
        if path != _room_fence_path(root, fence["room"], fence["player"]):
            msg = "Spotify dispatch journal room identity changed"
            raise ValueError(msg)
        result.append(fence)
    return result


async def async_restore_dispatch_fences(hass: HomeAssistant) -> None:
    """Restore uncertainty before entities expose source-changing actions."""
    lock = hass.data.setdefault(_DISPATCH_RESTORE_LOCK, asyncio.Lock())
    async with lock:
        if hass.data.get(_DISPATCH_RESTORED):
            return
        try:
            fences = await hass.async_add_executor_job(
                _read_dispatch_fences,
                hass.config.path(".storage", "pyloxone_spotify_return_dispatch"),
            )
        except (OSError, ValueError, UnicodeError) as _exc:
            hass.data[_DISPATCH_RESTORE_FAILED] = True
        else:
            for fence in fences:
                hass.data.setdefault(_ROOM_FENCES, set()).add((fence["room"], fence["player"]))
                account = hass.data.setdefault(_STORE, {}).setdefault(
                    fence["user"],
                    {"lock": asyncio.Lock(), "owner": None},
                )
                account.setdefault("uncertain", set()).add(fence["device"])
        hass.data[_DISPATCH_RESTORED] = True


def validate_bindings(value: object) -> dict:
    """Validate non-secret, exact room mappings and reject duplicate receivers."""
    if not isinstance(value, dict) or len(value) > _MAX_BINDINGS:
        msg = "Spotify return requires a bounded room mapping"
        raise ValueError(msg)
    receivers = set()
    for room, item in value.items():
        _literal(room, _BINDING_ID_PATTERN)
        binding = SpotifyBinding.parse(item)
        receiver = (binding.user_id, binding.device_id)
        if receiver in receivers:
            msg = "Spotify receiver cannot be assigned to two rooms"
            raise ValueError(msg)
        receivers.add(receiver)
    return value


def _track(row: object) -> str:
    if not isinstance(row, dict):
        msg = "Missing Spotify item identity"
        raise ValueError(msg)  # noqa: TRY004 - one playback validation contract
    return _literal(row.get("uri"), r"spotify:track:[A-Za-z0-9]{22}")


def _reject_item_conflict(row: object, expected: str) -> None:
    """Reject a different observable URI rather than treating it as unavailable."""
    uri = row.get("uri") if isinstance(row, dict) else None
    if isinstance(uri, str) and uri.startswith("spotify:") and uri != expected:
        msg = "Spotify content identity changed; no command was sent"
        raise AudioCommandError(msg)


def _native_context(snapshot: AudioZoneMetadata) -> str | None:
    """Do not mistake the native single-track wrapper for a provider context."""
    if (
        snapshot.source == "Spotify"
        and isinstance(snapshot.audio_path, str)
        and re.fullmatch(r"spotify:track:[A-Za-z0-9]{22}", snapshot.audio_path)
        and snapshot.parent_id == snapshot.audio_path
    ):
        return None
    return snapshot.parent_id


def _reject_playback_conflict(data: object, track: str, context: str | None) -> None:
    """Reject positive content conflicts before optional capability checks."""
    if not isinstance(data, dict):
        return
    _reject_item_conflict(data.get("item"), track)
    current = data.get("context")
    uri = current.get("uri") if isinstance(current, dict) else None
    if (isinstance(uri, str) and uri.startswith("spotify:") and uri != context) or (
        "context" in data and current is None and context is not None
    ):
        msg = "Spotify context identity changed; no command was sent"
        raise AudioCommandError(msg)


def _reject_state_conflict(
    data: object,
    expected: tuple[float, bool | None, str | None],
    *,
    advancing: bool = False,
    position_window: tuple[float, float] | None = None,

) -> None:
    """Preserve observable clock/flag conflicts even if capability parsing fails."""
    if not isinstance(data, dict):
        return
    progress, shuffle, repeat = expected
    observed = data.get("progress_ms")
    lower, upper = (
        position_window
        if position_window is not None
        else (
            progress - (0 if advancing else _POSITION_TOLERANCE_MS),
            progress + _POSITION_TOLERANCE_MS,
        )
    )
    if (
        (type(observed) is int and not lower <= observed <= upper)
        or (shuffle is not None and type(data.get("shuffle_state")) is bool and data["shuffle_state"] != shuffle)
        or (
            repeat is not None
            and data.get("repeat_state") in ("off", "context", "track")
            and data["repeat_state"] != repeat
        )
    ):

        msg = "Spotify position or playback mode changed; no command was sent"
        raise AudioCommandError(msg)


def _capture_position_window(
    snapshot: AudioZoneMetadata,
    started: datetime,
    ended: datetime,
) -> tuple[float, float] | None:
    """Project the native clock across the provider's possible measurement interval."""
    if snapshot.position is None or snapshot.native_mode not in ("play", "pause", "stop"):
        return None
    base = snapshot.position * 1000
    if snapshot.native_mode != "play":
        return base - _POSITION_TOLERANCE_MS, base + _POSITION_TOLERANCE_MS
    anchor = snapshot.position_updated_at
    if anchor is None or ended < started or anchor > ended or (ended - anchor).total_seconds() > _MAX_AGE:
        return None
    return (
        base + (started - anchor).total_seconds() * 1000 - _POSITION_TOLERANCE_MS,
        base + (ended - anchor).total_seconds() * 1000 + _POSITION_TOLERANCE_MS,
    )


def _library_clock_unchanged(original: AudioZoneMetadata, current: AudioZoneMetadata) -> bool:
    """
    Allow a frozen sample or bounded, positively timed playing progress.

    These are conservative observation bounds, not device timing guarantees.
    Sub-50ms changes cannot establish a reliable rate from arrival timestamps;
    paused changes, backwards clocks and missing anchors never authorise replay.
    Always compare with the pre-await sample, never rebase onto a later frame.
    """
    if current.position == original.position:
        return True
    if (
        original.native_mode != "play" or current.native_mode != "play"
        or type(original.position) not in (int, float) or type(current.position) not in (int, float)
        or original.position_updated_at is None or current.position_updated_at is None
        or original.received_at is None or current.received_at is None
        or not original.position_updated_at <= original.received_at <= current.position_updated_at
        or not original.position_updated_at < current.position_updated_at <= current.received_at <= dt_util.utcnow()
    ):
        return False
    elapsed = (current.position_updated_at - original.position_updated_at).total_seconds()
    progress = current.position - original.position
    # A small relative window, capped at 50ms, cannot hide a multi-second seek.
    # Fail closed when sparse/jittery feedback cannot positively show that rate.
    margin = min(elapsed / 10, _LIBRARY_CLOCK_OBSERVATION_SECONDS)
    return elapsed >= _LIBRARY_CLOCK_OBSERVATION_SECONDS and progress > 0 and abs(progress - elapsed) <= margin


def _playback(data: object) -> tuple[str, str | None, int, bool, str]:
    if not isinstance(data, dict) or "context" not in data:
        msg = "Missing Spotify playback identity"
        raise ValueError(msg)
    context = data.get("context")
    if context is not None:
        if not isinstance(context, dict):
            msg = "Invalid Spotify context"
            raise ValueError(msg)
        context = _literal(context.get("uri"), r"spotify:(?:album|playlist|artist):[A-Za-z0-9]{22}")
    progress, shuffle, repeat = data.get("progress_ms"), data.get("shuffle_state"), data.get("repeat_state")
    item = data.get("item")
    duration = item.get("duration_ms") if isinstance(item, dict) else None
    if (
        type(progress) is not int
        or type(duration) is not int
        or not 0 <= progress < duration
        or type(shuffle) is not bool
        or repeat not in ("off", "context", "track")
        or type(data.get("is_playing")) is not bool
    ):
        msg = "Invalid Spotify playback state"
        raise ValueError(msg)
    return _track(item), context, progress, shuffle, repeat


def _queue(data: object, track: str, expected: tuple[str, ...] | None = None) -> tuple[str, ...]:
    if isinstance(data, dict):
        _reject_item_conflict(data.get("currently_playing"), track)
    if not isinstance(data, dict) or not isinstance(data.get("queue"), list):
        msg = "Missing or mismatched Spotify queue preview"
        raise ValueError(msg)  # noqa: TRY004 - one optional playback validation contract
    observed = tuple(item.get("uri") if isinstance(item, dict) else None for item in data["queue"])
    if expected is not None and any(
        isinstance(uri, str) and uri.startswith("spotify:") and (index >= len(expected) or uri != expected[index])
        for index, uri in enumerate(observed)
    ):
        msg = "Spotify queue contains a positively different item; no command was sent"
        raise AudioCommandError(msg)
    if (
        expected is not None
        and all(isinstance(uri, str) and uri.startswith("spotify:") for uri in observed)
        and observed != expected
    ):
        msg = "Spotify queue identity changed; no command was sent"
        raise AudioCommandError(msg)
    if len(data["queue"]) > _MAX_QUEUE_PREVIEW:
        msg = "Spotify queue preview is outside the supported bound"
        raise ValueError(msg)
    if _track(data.get("currently_playing")) != track:
        msg = "Spotify queue belongs to a different playing item"
        raise AudioCommandError(msg)
    return tuple(_track(item) for item in data["queue"])


class SpotifyReturnUnavailable(NativeSessionUnavailableError):  # noqa: N818 - internal capability outcome
    """Optional pre-dispatch capability is absent; native behaviour can remain."""


def spotify_room_uncertain(hass: HomeAssistant, room: str, player: int | None) -> bool:
    """Keep ambiguous room writes fenced even if its optional mapping is removed."""
    return bool(hass.data.get(_DISPATCH_RESTORE_FAILED)) or (room, player) in hass.data.get(_ROOM_FENCES, set())


class SpotifySourceReturn:
    """One room's bookmark, serialized with other PyLoxone users of its account."""

    def __init__(  # noqa: PLR0913 - explicit room, account and transport ownership
        self,
        hass: HomeAssistant,
        binding: SpotifyBinding,
        room: str,
        player: int,
        commands: AudioServerCommands,
        native: Callable[[], AudioZoneMetadata | None],
    ) -> None:
        """Retain exact room ownership without owning provider credentials."""
        self.hass, self.binding, self.room, self.player = hass, binding, room, player
        self.commands, self.native = commands, native
        self.bookmark: SpotifyBookmark | None = None
        self._library_departure: tuple[SpotifyBookmark, AudioZoneMetadata] | None = None
        self.closed = False
        self._generation = 0
        self._release = None
        store = hass.data.setdefault(_STORE, {})
        self._account = store.setdefault(binding.user_id, {"lock": asyncio.Lock(), "owner": None})
        self._account.setdefault("uncertain", set())
        if self.uncertain:
            hass.data.setdefault(_ROOM_FENCES, set()).add((self.room, self.player))
        if self.uncertain and self.player not in commands.source_fences:

            def release_restored() -> None:
                self.invalidate()
                if commands.source_fences.get(self.player) is release_restored:
                    commands.source_fences.pop(self.player)
                self._release = None

            self._release = release_restored
            commands.source_fences[self.player] = release_restored

    @property
    def uncertain(self) -> bool:
        """Retain ambiguous provider sends across entity/client recreation."""
        return self.binding.device_id in self._account["uncertain"] or spotify_room_uncertain(
            self.hass, self.room, self.player
        )

    @uncertain.setter
    def uncertain(self, value: bool) -> None:
        rooms = self.hass.data.setdefault(_ROOM_FENCES, set())
        if value:
            self._account["uncertain"].add(self.binding.device_id)
            rooms.add((self.room, self.player))
        else:
            self._account["uncertain"].discard(self.binding.device_id)
            rooms.discard((self.room, self.player))

    @property
    def generation(self) -> int:
        """Expose a read-only cancellation token for optional native fallback."""
        return self._generation

    def invalidate(self) -> None:
        """Invalidate pending completions and playback ownership on removal/loss."""
        self._generation += 1
        self.bookmark = None
        self._library_departure = None
        if self._account["owner"] is self:
            self._account["owner"] = None

    def remember_library_departure(self) -> None:
        """Retain only an entity-confirmed Library detour from this owned capture."""
        self._library_departure = None
        snapshot, saved = self.native(), self.bookmark
        if (
            not self.closed and not self.uncertain
            and saved is not None and self._account["owner"] is self
            and 0 <= asyncio.get_running_loop().time() - saved.captured <= _MAX_AGE
            and snapshot is not None and snapshot.player_id == self.player
            and snapshot.source == "Local Library"
            and isinstance(snapshot.audio_path, str)
            and snapshot.audio_path.startswith("library:local:track:")
            and len(snapshot.audio_path) > len("library:local:track:")
            and snapshot.native_mode == "play"
            and snapshot.event_idle and snapshot.event_active is False
            and snapshot.received_at is not None
            and 0 <= (dt_util.utcnow() - snapshot.received_at).total_seconds() <= _NATIVE_FRESH_SECONDS
        ):
            self._library_departure = (saved, snapshot)

    def _detached_source_supported(self, saved: SpotifyBookmark, snapshot: AudioZoneMetadata) -> bool:
        """HTTP204 is absence, not ownership; Library also needs our confirmed detour."""
        if snapshot.source == "TuneIn":
            return True
        departure = self._library_departure
        return bool(
            departure is not None and departure[0] is saved
            and snapshot.source == "Local Library"
            and all(
                getattr(snapshot, key) == getattr(departure[1], key)
                for key in ("player_id", "source", "source_name", "audio_path", "parent_id", "native_mode")
            )
        )

    def discard_delayed_capture(self, *, advancing: bool) -> bool:
        """Do not retain a playing clock across a slow subsequent native start."""
        if (
            advancing
            and self.bookmark is not None
            and ((asyncio.get_running_loop().time() - self.bookmark.captured) * 1000 > _POSITION_TOLERANCE_MS)
        ):
            self.invalidate()
            return True
        return False

    def close(self) -> None:
        """Do not close the official integration's shared session."""
        self.closed = True
        self.invalidate()
        if self._release is not None and not self.uncertain:
            self._release()

    @asynccontextmanager
    async def _reservation(self) -> AsyncIterator[None]:
        fences = self.commands.source_fences
        if self.player in fences or self.player in self.commands.announcement_fences:
            msg = "Another player action is active or uncertain"
            raise AudioCommandError(msg)

        def release() -> None:
            self.invalidate()
            if fences.get(self.player) is release:
                fences.pop(self.player)
            self._release = None

        self._release = release
        fences[self.player] = release
        try:
            yield
        finally:
            if not self.uncertain and fences.get(self.player) is release:
                fences.pop(self.player)
                self._release = None

    def _session(self) -> OAuth2Session:
        entry = self.hass.config_entries.async_get_entry(self.binding.entry_id)
        session = getattr(getattr(entry, "runtime_data", None), "session", None)
        if (
            entry is None
            or entry.domain != "spotify"
            or entry.state is not ConfigEntryState.LOADED
            or getattr(entry, "disabled_by", None) is not None
            or entry.unique_id != self.binding.user_id
            or not callable(getattr(session, "async_request", None))
            or not callable(getattr(session, "async_ensure_token_valid", None))
        ):
            msg = "The selected official Spotify integration is not available"
            raise SpotifyReturnUnavailable(msg)
        return session

    async def _read(self, session: OAuth2Session, endpoint: str) -> Any:
        response = await session.async_request("GET", _API + endpoint, allow_redirects=False)
        try:
            if endpoint == "me/player" and response.status == _HTTP_NO_CONTENT:
                return None
            if response.status != _HTTP_OK:
                msg = "Spotify state could not be read"
                raise SpotifyReturnUnavailable(msg)
            return await response.json()
        except ValueError as exc:
            raise SpotifyReturnUnavailable("Spotify state could not be decoded") from exc
        finally:
            response.release()

    def _guard(
        self,
        session: OAuth2Session,
        generation: int,
        available: Callable[[], bool],
        expected_native: AudioZoneMetadata | None = None,
    ) -> None:
        snapshot = self.native()
        if (
            self.closed
            or generation != self._generation
            or not available()
            or self._session() is not session
            or snapshot is None
            or snapshot.player_id != self.player
            or not snapshot.event_idle
            or snapshot.event_active is not False
            or (
                expected_native is not None
                and any(
                    getattr(snapshot, field) != getattr(expected_native, field)
                    for field in ("source", "source_name", "audio_path", "parent_id", "native_mode")
                )
            )
            or (
                expected_native is not None and expected_native.source == "Local Library"
                and not _library_clock_unchanged(expected_native, snapshot)
            )
        ):
            msg = "Room or Spotify ownership changed; no replay was sent"
            raise AudioCommandError(msg)
        if snapshot.received_at is None or not (
            0 <= (dt_util.utcnow() - snapshot.received_at).total_seconds() <= _NATIVE_FRESH_SECONDS
        ):
            msg = "Native feedback is not fresh enough for optional Spotify resume"
            raise SpotifyReturnUnavailable(msg)
        if self.uncertain and self.bookmark is not None:
            self._guard_bookmark(self.bookmark)

    def _own_device(self, data: object, *, require_control: bool = True) -> None:
        if not data:
            msg = "Spotify playback is not currently available"
            raise SpotifyReturnUnavailable(msg)
        device = data.get("device") if isinstance(data, dict) else None
        identity = device.get("id") if isinstance(device, dict) else None
        if not isinstance(identity, str) or not identity:
            msg = "Spotify receiver identity is currently unavailable"
            raise SpotifyReturnUnavailable(msg)
        if identity != self.binding.device_id:
            self.invalidate()
            msg = "Spotify is owned by another receiver"
            raise AudioCommandError(msg)
        if require_control and device.get("is_restricted") is not False:
            msg = "The optional Spotify receiver cannot be controlled"
            raise SpotifyReturnUnavailable(msg)

    async def _identity(self, session: OAuth2Session) -> None:
        user = await self._read(session, "me")
        identity = user.get("id") if isinstance(user, dict) else None
        if not isinstance(identity, str) or not identity:
            msg = "Spotify profile identity is currently unavailable"
            raise SpotifyReturnUnavailable(msg)
        if identity != self.binding.user_id:
            self.invalidate()
            msg = "Spotify account changed"
            raise AudioCommandError(msg)

    async def _native_user(self) -> str:
        try:
            accounts = await self.commands.async_service_accounts()
        except AudioCommandError:
            # Only optional inventory retrieval is classified here. Ownership
            # guards and the eventual native command retain their real errors.
            msg = "Native Spotify account inventory cannot currently be read"
            raise SpotifyReturnUnavailable(msg) from None
        if not isinstance(accounts, list) or len(accounts) > _MAX_DEVICES:
            msg = "Native Spotify account inventory is unavailable"
            raise SpotifyReturnUnavailable(msg)
        users = [
            a.get("user")
            for a in accounts
            if isinstance(a, dict)
            and a.get("cmd") == "spotify"
            and a.get("id") == self.binding.account_id
            and a.get("configerror") is False
        ]
        if len(users) != 1 or not isinstance(users[0], str) or not users[0]:
            msg = "Native Spotify account is not positively matched"
            raise SpotifyReturnUnavailable(msg)
        if any(
            isinstance(account, dict)
            and account.get("cmd") == "spotify"
            and account.get("user") == users[0]
            and account.get("id") != self.binding.account_id
            for account in accounts
        ):
            msg = "Native Spotify user label does not uniquely identify the account"
            raise SpotifyReturnUnavailable(msg)
        return users[0]

    async def async_capture(self, available: Callable[[], bool]) -> None:  # noqa: PLR0915 - one guarded capture with explicit timing and positive-conflict checks
        """Capture immediately before leaving the positively matched native session."""
        generation, snapshot = self._generation, self.native()
        self.bookmark = None
        self._library_departure = None
        if snapshot is None:
            msg = "Initial native playback identity is missing"
            raise AudioCommandError(msg)

        async with asyncio.timeout(10), self._account["lock"], self._reservation():

            session = self._session()
            self._guard(session, generation, available, snapshot)
            native_user = await self._native_user()
            self._guard(session, generation, available, snapshot)
            if snapshot.source != "Spotify":
                msg = "Native Spotify account is not positively matched"
                raise AudioCommandError(msg)
            if snapshot.source_name != native_user:
                # An initially different native account is outside this
                # optional capture, not a veto on its requested departure.
                # The pinned guard above still rejects changes during lookup.
                msg = "Initial native account is outside the optional Spotify binding"
                raise SpotifyReturnUnavailable(msg)
            await self._identity(session)
            started = dt_util.utcnow()
            data = await self._read(session, "me/player")

            ended = dt_util.utcnow()
            _reject_playback_conflict(data, snapshot.audio_path, _native_context(snapshot))
            window = _capture_position_window(snapshot, started, ended)
            if window is not None:
                _reject_state_conflict(
                    data,
                    (snapshot.position * 1000, None, None),
                    position_window=(
                        min(window[0], snapshot.position * 1000 - _POSITION_TOLERANCE_MS),
                        window[1],
                    ),

                )
            self._own_device(data if isinstance(data, dict) else {})
            track, context, progress, shuffle, repeat = _playback(data)
            if window is None or not window[0] <= progress <= window[1]:
                msg = "Native playback timing is currently unavailable"
                raise SpotifyReturnUnavailable(msg)
            if data["is_playing"] != (snapshot.native_mode == "play"):
                msg = "Native and provider playback timing is unsettled"
                raise SpotifyReturnUnavailable(msg)
            queue = _queue(await self._read(session, "me/player/queue"), track)
            measured_earliest = asyncio.get_running_loop().time()
            again_started = dt_util.utcnow()
            again = await self._read(session, "me/player")
            again_ended = dt_util.utcnow()
            _reject_playback_conflict(again, track, context)
            advancing = data["is_playing"] or not isinstance(again, dict) or again.get("is_playing") is not False
            maximum = (
                progress
                + _POSITION_TOLERANCE_MS
                + (max(0, (again_ended - started).total_seconds()) * 1000 if advancing else 0)
            )
            _reject_state_conflict(
                again,
                (progress, shuffle, repeat),
                position_window=(
                    progress - _POSITION_TOLERANCE_MS,
                    maximum,
                ),

            )
            self._own_device(again if isinstance(again, dict) else {})
            new_track, new_context, new_progress, new_shuffle, new_repeat = _playback(again)
            self._guard(session, generation, available, snapshot)
            if (new_track, new_context, new_shuffle, new_repeat) != (
                track,
                context,
                shuffle,
                repeat,
            ) or self.native().audio_path != track:
                msg = "Spotify changed while capturing the room bookmark"
                raise AudioCommandError(msg)
            latest_native = self.native()
            final_window = _capture_position_window(latest_native, again_started, again_ended)
            if final_window is not None:
                _reject_state_conflict(
                    again,
                    (new_progress, None, None),
                    position_window=(
                        min(final_window[0], latest_native.position * 1000 - _POSITION_TOLERANCE_MS),
                        final_window[1],
                    ),

                )
            if (
                final_window is None
                or not final_window[0] <= new_progress <= final_window[1]
                or data["is_playing"] != again["is_playing"]
            ):
                msg = "Playback clock timing cannot currently be matched"
                raise SpotifyReturnUnavailable(msg)
            self.bookmark = SpotifyBookmark(
                track, context, new_progress, shuffle, repeat, queue, measured_earliest, native_user
            )
            self._account["owner"] = self

            # Only fresh, independently matching native/provider evidence can
            # reconcile a previous ambiguous send after command-client unload.
            self.uncertain = False

    def _already_active(
        self,
        data: object,
        snapshot: AudioZoneMetadata,
        native_user: str,
    ) -> bool:
        """Only the exact currently native-owned session permits a playing no-op."""
        if not isinstance(data, dict) or data.get("is_playing") is not True:
            return False
        _reject_playback_conflict(data, snapshot.audio_path, _native_context(snapshot))
        device = data.get("device")
        identity = device.get("id") if isinstance(device, dict) else None
        if isinstance(identity, str) and identity and identity != self.binding.device_id:
            msg = "Spotify playback is owned by another receiver; no command was sent"
            raise AudioCommandError(msg)
        if not (
            snapshot.source_name == native_user and snapshot.native_mode == "play" and snapshot.source == "Spotify"
        ):
            msg = "Spotify playback is independently active; no command was sent"
            raise AudioCommandError(msg)
        item, context = data.get("item"), data.get("context")
        uri = item.get("uri") if isinstance(item, dict) else None
        native_context = _native_context(snapshot)
        context_known = ("context" in data and context is None and native_context is None) or (
            isinstance(context, dict) and isinstance(context.get("uri"), str) and context["uri"] == native_context
        )
        if not (
            identity == self.binding.device_id
            and isinstance(uri, str)
            and uri.startswith("spotify:")
            and uri == snapshot.audio_path
            and context_known
        ):
            msg = "Active Spotify identity is currently incomplete"
            raise SpotifyReturnUnavailable(msg)
        return True

    def _guard_bookmark(self, saved: SpotifyBookmark) -> None:
        """Do not dispatch after a bookmark expires during awaited preparation."""
        if (
            self.bookmark is not saved
            or self._account["owner"] is not self
            or not 0 <= asyncio.get_running_loop().time() - saved.captured <= _MAX_AGE
        ):
            msg = "The room-owned Spotify bookmark is no longer available"
            raise SpotifyReturnUnavailable(msg)
        self.reject_native_conflict(self.native())

    def native_noop(self, target: CatalogueTarget, snapshot: AudioZoneMetadata | None) -> bool:
        """Recognise only an unchanged active target; never dispatch replacement content."""
        saved = self.bookmark
        return bool(
            saved is not None
            and snapshot is not None
            and snapshot.player_id == self.player
            and snapshot.source == "Spotify"
            and snapshot.native_mode == "play"
            and snapshot.event_idle
            and snapshot.event_active is False
            and snapshot.received_at is not None
            and 0 <= (dt_util.utcnow() - snapshot.received_at).total_seconds() <= _NATIVE_FRESH_SECONDS
            and snapshot.source_name == saved.native_user
            and target.service == "spotify"
            and target.account == self.binding.account_id
            and target.audio_path is not None
            and source_matches(
                snapshot,
                target.audio_path,
                is_context=target.is_context,
                account_user=saved.native_user,
            )
        )

    def reject_native_conflict(self, snapshot: AudioZoneMetadata | None) -> None:
        """Do not let optional loss hide a bookmark superseded by native identity."""
        saved = self.bookmark
        if snapshot is None or snapshot.source != "Spotify" or saved is None:
            return
        if (
            snapshot.source_name != saved.native_user
            or snapshot.audio_path != saved.track
            or _native_context(snapshot) != saved.context
            or (
                snapshot.native_mode != "play"
                and snapshot.position is not None
                and abs(snapshot.position * 1000 - saved.progress_ms) > _POSITION_TOLERANCE_MS
            )
        ):
            self.invalidate()
            msg = "Current native Spotify identity contradicts the saved session"
            raise AudioCommandError(msg)

    def _match_activation(
        self, data: object, saved: SpotifyBookmark, settled: _ActivationState | None = None
    ) -> None:
        """Require matching identity rather than treating transfer ACK as permission."""
        _reject_playback_conflict(data, saved.track, saved.context)
        _reject_state_conflict(data, (saved.progress_ms, saved.shuffle, saved.repeat))
        self._own_device(data)
        track, context, progress, shuffle, repeat = _playback(data)
        if (
            data["is_playing"] is not False
            or data["device"].get("is_active") is not True
            or (track, context, shuffle, repeat) != (saved.track, saved.context, saved.shuffle, saved.repeat)
            or abs(progress - saved.progress_ms) > _POSITION_TOLERANCE_MS
            or (settled is not None and progress != settled.progress_ms)
        ):
            msg = "Activated Spotify session does not match; no Play was sent"
            raise AudioCommandError(msg)

    def _dispatch_fence(self, saved: SpotifyBookmark) -> dict:
        return {
            "version": 1,
            "room": self.room,
            "player": self.player,
            "user": self.binding.user_id,
            "device": self.binding.device_id,
            "attempt": saved.dispatch_id,
        }

    def _activation_native(self, snapshot: AudioZoneMetadata, saved: SpotifyBookmark, sent_at: datetime) -> bool:
        """Recognise only the expected exact-session, stopped post-transfer frame."""
        return bool(
            snapshot.player_id == self.player
            and snapshot.event_idle
            and snapshot.event_active is False
            and snapshot.source == "Spotify"
            and snapshot.source_name == saved.native_user
            and snapshot.audio_path == saved.track
            and _native_context(snapshot) == saved.context
            and snapshot.native_mode in ("stop", "pause")
            and type(snapshot.position) in (int, float)
            and snapshot.position >= 0
            and abs(snapshot.position * 1000 - saved.progress_ms) <= _POSITION_TOLERANCE_MS
            and snapshot.received_at is not None
            and snapshot.position_updated_at is not None
            and sent_at <= snapshot.position_updated_at <= snapshot.received_at
            and 0 <= (dt_util.utcnow() - snapshot.received_at).total_seconds() <= _NATIVE_FRESH_SECONDS
        )

    def _guard_activation(self, saved: SpotifyBookmark, settled: _ActivationState) -> None:
        """Keep complete activation evidence mandatory until the separate Play send."""
        snapshot = self.native()
        if (
            snapshot is None
            or not self._activation_native(snapshot, saved, settled.sent_at)
            or snapshot.position != settled.native.position
        ):
            # Consumed activation stays uncertain. A later healthy frame cannot
            # rehabilitate this attempt or enable a source-changing fallback.
            msg = "Incomplete or changed native activation evidence; no Play was sent"
            raise AudioCommandError(msg)

    async def _send_once(  # noqa: PLR0913 - exact transaction fences travel with each dispatch
        self,
        session: OAuth2Session,
        generation: int,
        available: Callable[[], bool],
        expected_native: AudioZoneMetadata,
        saved: SpotifyBookmark,
        *,
        activate: bool = False,
        durable: bool = False,
        activation: _ActivationState | None = None,
    ) -> datetime:
        """Use HA-owned OAuth and middleware; never replay an ambiguous PUT."""
        if durable:
            # Cancellation does not stop a filesystem job already consuming its marker.
            self.uncertain = True
            identity = f"{self.binding.user_id}:{self.binding.device_id}:{saved.dispatch_id}"
            try:
                await self.hass.async_add_executor_job(
                    _write_dispatch_marker,
                    self.hass.config.path(".storage", "pyloxone_spotify_return_dispatch"),
                    identity,
                    "activate" if activate else "play",
                    self._dispatch_fence(saved),
                )
            except OSError as exc:
                msg = "Spotify one-send marker is unavailable; no replay was sent"
                raise AudioCommandError(msg) from exc

        def guard() -> None:
            self._guard(session, generation, available, expected_native)
            self._guard_bookmark(saved)
            if activation is not None:
                self._guard_activation(saved, activation)

        # Observe after the marker await before yielding to OAuth, then again
        # inside the real transport middleware after its refresh/prepare awaits.
        guard()
        sent_at = None

        async def send_once(request: ClientRequest, handler: ClientHandlerType) -> ClientResponse:
            nonlocal sent_at
            if sent_at is not None:
                msg = "Spotify dispatch is uncertain; transport replay blocked"
                raise AudioCommandError(msg)
            guard()
            self.uncertain = True
            sent_at = dt_util.utcnow()

            return await handler(request)

        payload = (
            {"json": {"device_ids": [self.binding.device_id], "play": False}}
            if activate
            else {"params": {"device_id": self.binding.device_id}}
        )
        response = await session.async_request(
            "PUT",
            _API + ("me/player" if activate else "me/player/play"),
            allow_redirects=False,
            middlewares=(send_once,),
            **payload,
        )
        try:
            if response.status != _HTTP_NO_CONTENT or sent_at is None:
                msg = "Spotify dispatch was not accepted; no replay was sent"
                raise AudioCommandError(msg)

        finally:
            response.release()
        return sent_at

    async def _commit_dispatch(self, saved: SpotifyBookmark) -> None:
        """Settle a positively confirmed return before propagating late cancellation."""

        # This commit point is reached only after all playing/native/queue checks.
        # Before it, cancellation retains the durable uncertainty fence. After it,
        # finish the already-authorised bookkeeping, not another provider command.
        async def commit() -> OSError | ValueError | None:
            # Resolve expected IO failures inside the shielded task: Python may
            # report a failed shielded future even when a later await handles it.
            try:
                await self.hass.async_add_executor_job(
                    _clear_dispatch_fence,
                    self.hass.config.path(".storage", "pyloxone_spotify_return_dispatch"),
                    self._dispatch_fence(saved),
                )
            except (OSError, ValueError) as exc:
                return exc
            return None

        job = asyncio.create_task(commit())
        cancelled = False
        while True:
            try:
                error = await asyncio.shield(job)
                break
            except asyncio.CancelledError:
                if job.cancelled():
                    raise
                cancelled = True
        if error is not None:
            if cancelled:
                raise asyncio.CancelledError from error
            msg = "Spotify dispatch reconciliation is uncertain"
            raise AudioCommandError(msg) from error
        self.uncertain = False
        self.invalidate()

        if cancelled:
            raise asyncio.CancelledError

    async def _activate_detached(
        self,
        session: OAuth2Session,
        generation: int,
        available: Callable[[], bool],
        expected_native: AudioZoneMetadata,
        saved: SpotifyBookmark,
    ) -> _ActivationState:
        """Activate once, permit only its expected native transition, then match twice."""
        sent_at = await self._send_once(
            session,
            generation,
            available,
            expected_native,
            saved,
            activate=True,
            durable=True,
        )
        seen_native = False
        matches = 0
        previous_progress = None
        previous_native_position = None

        def observe() -> bool:
            nonlocal seen_native, previous_native_position
            self._guard(session, generation, available)
            self._guard_bookmark(saved)
            snapshot = self.native()
            ready = self._activation_native(snapshot, saved, sent_at)
            if not ready and (
                seen_native
                or (
                    expected_native.source == "Local Library"
                    and snapshot is not None and not _library_clock_unchanged(expected_native, snapshot)
                )
                or any(
                    getattr(snapshot, key) != getattr(expected_native, key)
                    for key in ("source", "source_name", "audio_path", "parent_id", "native_mode")
                )
            ):
                msg = "Unexpected native transition during activation; no Play was sent"
                raise AudioCommandError(msg)
            if ready:
                if previous_native_position is not None and snapshot.position != previous_native_position:
                    msg = "Activated paused native position changed; no Play was sent"
                    raise AudioCommandError(msg)
                previous_native_position = snapshot.position
            seen_native = seen_native or ready
            return ready

        async with asyncio.timeout(8):
            while True:
                observe()
                data = await self._read(session, "me/player")
                observe()
                if data is not None:
                    self._match_activation(data, saved)
                    if previous_progress is not None and data["progress_ms"] != previous_progress:
                        msg = "Activated paused position changed; no Play was sent"
                        raise AudioCommandError(msg)
                    previous_progress = data["progress_ms"]
                    if _queue(await self._read(session, "me/player/queue"), saved.track, saved.queue) != saved.queue:
                        msg = "Activated Spotify preview changed; no Play was sent"
                        raise AudioCommandError(msg)
                    if observe():
                        matches += 1
                        if matches == _ACTIVATION_MATCHES:
                            return _ActivationState(sent_at, previous_progress, self.native())
                elif previous_progress is not None:
                    # Initial activation latency may have no provider identity.
                    # Once observed, however, that identity must remain complete:
                    # losing it consumes the attempt even before native readiness.
                    msg = "Activated Spotify identity disappeared; no Play was sent"
                    raise AudioCommandError(msg)
                await asyncio.sleep(0.2)

    @asynccontextmanager
    async def async_native_session(self, available: Callable[[], bool]) -> AsyncIterator[SpotifyNativeSession | None]:
        """Qualify the already-linked session, retaining its account lock.

        Native policy/settlement is package-owned. No additional OAuth session,
        token storage, receiver discovery or provider playback write is added.
        """
        generation = self._generation
        async with self._account["lock"]:
            session = self._session()
            self._guard(session, generation, available)
            await self._identity(session)
            user = await self._native_user()
            data = await self._read(session, "me/player")
            self._guard(session, generation, available)
            if data is None:
                yield None
            else:
                self._own_device(data, require_control=False)
                yield SpotifyNativeSession(user, self.binding.account_id)

    async def async_resume_native(self, metadata: Any, available: Callable[[], bool]) -> bool:
        """Use the real native library through the existing read-only session."""
        return await async_resume_native_session(
            self.commands, metadata, self.player, self, available, timeout_factory=asyncio.timeout,
            environment=source_environment,
        )

    async def async_resume(self, available: Callable[[], bool]) -> None:  # noqa: C901, PLR0912, PLR0915 - one bounded transaction with explicit pre-send conflict guards
        """Resume once without replacing provider context, queue, shuffle or clock."""
        generation, expected_native = self._generation, self.native()
        if expected_native is None:
            msg = "Initial native playback identity is missing"
            raise AudioCommandError(msg)

        async with asyncio.timeout(25), self._account["lock"], self._reservation():

            if self.uncertain:
                msg = "Previous Spotify resume is uncertain; no replay was sent"
                raise AudioCommandError(msg)
            session = self._session()
            self._guard(session, generation, available, expected_native)
            await self._identity(session)
            native_user = await self._native_user()
            data = await self._read(session, "me/player")

            self._guard(session, generation, available, expected_native)
            # An already-active owned source is a no-op, not another start/seek.
            snapshot = self.native()
            saved = self.bookmark
            age = asyncio.get_running_loop().time() - saved.captured if saved else _MAX_AGE + 1
            if data is not None and self._already_active(data, snapshot, native_user):
                self._guard(session, generation, available)
                # An active session is newer than any retained paused bookmark.
                self.invalidate()
                return
            if snapshot.source == "Spotify":
                self.reject_native_conflict(snapshot)
                if snapshot.source_name != native_user:
                    self.invalidate()
                    msg = "Current native Spotify identity contradicts the saved session"
                    raise AudioCommandError(msg)
                if data is not None:
                    _reject_playback_conflict(data, snapshot.audio_path, _native_context(snapshot))
                    if snapshot.position is not None:
                        _reject_state_conflict(data, (snapshot.position * 1000, None, None))
            if data is not None:
                if saved is not None:
                    _reject_playback_conflict(data, saved.track, saved.context)
                    if self._account["owner"] is self and 0 <= age <= _MAX_AGE:
                        _reject_state_conflict(data, (saved.progress_ms, saved.shuffle, saved.repeat))
                self._own_device(data)
                track, context, _, _, _ = _playback(data)
                if snapshot.source == "Spotify" and snapshot.source_name != native_user:
                    msg = "Native Spotify account is not positively matched"
                    raise AudioCommandError(msg)
                if snapshot.source == "Spotify" and snapshot.native_mode == "play":
                    # A paused provider view cannot authorise another start
                    # over native playback that is already running.
                    msg = "Native playback is already active; use native source selection"
                    raise SpotifyReturnUnavailable(msg)
            if saved is None or self._account["owner"] is not self or not 0 <= age <= _MAX_AGE:
                msg = "No fresh room-owned Spotify session is available"
                raise SpotifyReturnUnavailable(msg)
            if data is not None:
                track, context, progress, shuffle, repeat = _playback(data)
                if (track, context, shuffle, repeat) != (
                    saved.track,
                    saved.context,
                    saved.shuffle,
                    saved.repeat,
                ) or abs(progress - saved.progress_ms) > _POSITION_TOLERANCE_MS:
                    msg = "Saved Spotify session no longer matches"
                    raise AudioCommandError(msg)
            devices = await self._read(session, "me/player/devices")
            rows = devices.get("devices") if isinstance(devices, dict) else None
            if isinstance(rows, list) and any(
                isinstance(d, dict)
                and d.get("is_active") is True
                and isinstance(d.get("id"), str)
                and d["id"]
                and d["id"] != self.binding.device_id
                for d in rows
            ):
                self.invalidate()
                msg = "Another Spotify device owns playback"
                raise AudioCommandError(msg)
            if (
                not isinstance(rows, list)
                or len(rows) > _MAX_DEVICES
                or any(not isinstance(d, dict) or type(d.get("is_active")) is not bool for d in rows)
            ):
                msg = "Spotify receiver inventory is invalid"
                raise SpotifyReturnUnavailable(msg)
            targets = [d for d in rows if d.get("id") == self.binding.device_id and d.get("is_restricted") is False]

            if len(targets) != 1:
                msg = "The optional Spotify receiver is not available"
                raise SpotifyReturnUnavailable(msg)
            # Refresh before the last guard, using the existing session's lock.
            await session.async_ensure_token_valid()
            latest = await self._read(session, "me/player")
            activated = False
            activation = None


            def guard_native() -> None:
                self._guard(session, generation, available, expected_native)
                if activation is not None:
                    self._guard_activation(saved, activation)

            if latest is None:
                if (
                    data is not None
                    or not self._detached_source_supported(saved, expected_native)
                    or expected_native.native_mode not in ("play", "stop", "pause")
                    or any(row["is_active"] for row in rows)
                ):
                    msg = "The retained Spotify session cannot currently be verified"
                    raise SpotifyReturnUnavailable(msg)
                if saved.native_user != native_user:
                    msg = "Native Spotify account changed before activation"
                    raise AudioCommandError(msg)
                self._guard(session, generation, available, expected_native)
                self._guard_bookmark(saved)
                activation = await self._activate_detached(
                    session,
                    generation,
                    available,
                    expected_native,
                    saved,
                )
                expected_native = activation.native
                activated = True
                guard_native()
                await self._identity(session)
                guard_native()
                if await self._native_user() != saved.native_user:
                    msg = "Native account changed after activation; no Play was sent"
                    raise AudioCommandError(msg)
                guard_native()
                latest = await self._read(session, "me/player")
                guard_native()
                self._match_activation(latest, saved, activation)
            if latest is not None:
                if isinstance(latest, dict) and latest.get("is_playing") is True:
                    msg = "Spotify playback resumed independently; no command was sent"
                    raise AudioCommandError(msg)
                _reject_playback_conflict(latest, saved.track, saved.context)
                _reject_state_conflict(latest, (saved.progress_ms, saved.shuffle, saved.repeat))
                self._own_device(latest)
                track, context, progress, shuffle, repeat = _playback(latest)
                if (track, context, shuffle, repeat) != (
                    saved.track,
                    saved.context,
                    saved.shuffle,
                    saved.repeat,
                ) or abs(progress - saved.progress_ms) > _POSITION_TOLERANCE_MS:
                    msg = "Spotify session changed before resume"
                    raise AudioCommandError(msg)
                if _queue(await self._read(session, "me/player/queue"), saved.track, saved.queue) != saved.queue:
                    msg = "Spotify queue preview changed before resume"
                    raise AudioCommandError(msg)
                guard_native()
            if saved.native_user != native_user:
                msg = "Native Spotify account changed before resume"
                raise AudioCommandError(msg)
            guard_native()
            self._guard_bookmark(saved)
            sent_at = await self._send_once(
                session,
                generation,
                available,
                expected_native,
                saved,
                durable=activated,
                activation=activation,
            )
            async with asyncio.timeout(8):
                while True:
                    self._guard(session, generation, available)
                    data = await self._read(session, "me/player")
                    self._guard(session, generation, available)
                    if data is not None:
                        self._own_device(data)
                        track, context, progress, shuffle, repeat = _playback(data)
                        snapshot = self.native()
                        if (
                            data["is_playing"]
                            and (track, context, shuffle, repeat)
                            == (saved.track, saved.context, saved.shuffle, saved.repeat)
                            and saved.progress_ms - 1500 <= progress <= saved.progress_ms + 11000
                            and snapshot.source_name == saved.native_user
                            and snapshot.audio_path == track
                            and _native_context(snapshot) == context
                            and snapshot.native_mode == "play"
                            and snapshot.received_at >= sent_at
                            and _queue(await self._read(session, "me/player/queue"), track) == saved.queue
                        ):
                            self._guard(session, generation, available)
                            latest_native = self.native()
                            if (
                                self.bookmark is not saved
                                or self._account["owner"] is not self
                                or latest_native.source_name != saved.native_user
                                or latest_native.audio_path != track
                                or _native_context(latest_native) != context
                                or latest_native.native_mode != "play"
                                or latest_native.received_at < sent_at
                            ):
                                msg = "Spotify bookmark or native playback ownership changed"
                                raise AudioCommandError(msg)
                            if activated:
                                await self._commit_dispatch(saved)
                                return
                            self.uncertain = False
                            # A confirmed return consumes the paused snapshot;
                            # active playback can now advance to another track.
                            self.invalidate()
                            return
                    await asyncio.sleep(0.2)
