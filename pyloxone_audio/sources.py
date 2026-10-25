"""Bounded configured room favourites, separate from catalogue browsing."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
import re
from typing import TYPE_CHECKING, Any

from . import clock as dt_util

from .native import AudioCommandError


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import datetime
    from .metadata import AudioMetadataCoordinator
    from .catalogue import CatalogueTarget
    from .native import AudioServerCommands, AudioZoneMetadata


_LOGGER = logging.getLogger(__name__)
_MAX_FAVOURITES = 256
_MAX_SERVICE_ACCOUNTS = 32
_MAX_NAME_LENGTH = 256
_MAX_PATH_LENGTH = 2048
_CONTROL_BOUNDARY = 32
_PAUSED_POSITION_TOLERANCE = 3.0


@dataclass(frozen=True)
class SourceEnvironment:
    """An isolated source-operation clock; defaults to aware UTC, never HA."""

    clock: Callable[[], datetime] = dt_util.utcnow

    async def async_observed_change(self, *args: Any, **kwargs: Any) -> AudioZoneMetadata | None:
        """Run the concrete native settlement/feedback operation with this clock."""
        return await async_observed_change(*args, clock=self.clock, **kwargs)


@dataclass(frozen=True)
class AudioFavourite:
    """A discovered favourite's stable identity and expected playback path."""

    player_id: int
    favourite_id: int
    label: str
    audio_path: str
    is_context: bool = False


def parse_room_favourites(payload: object, player_id: int) -> tuple[AudioFavourite, ...]:
    """Read one complete, bounded room-favourite page without rewriting paths."""
    message = "Configured favourites require a complete bounded exact-player page"
    if type(player_id) is not int or player_id <= 0 or not isinstance(payload, list) or len(payload) != 1:
        raise ValueError(message)
    row = payload[0]
    if not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] != player_id:
        raise ValueError(message)
    items, total = row.get("items"), row.get("totalitems")
    if (
        type(row.get("start")) is not int
        or row["start"] != 0
        or type(total) is not int
        or not 0 <= total <= _MAX_FAVOURITES
        or not isinstance(items, list)
        or len(items) != total
    ):
        raise ValueError(message)
    choices = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError(message)  # noqa: TRY004 - one discovery-validation contract
        target = item.get("id")
        if type(target) is not int or target <= 0 or target in seen:
            raise ValueError(message)
        seen.add(target)
        kind = item.get("type")
        prefixes = {
            "tunein": ("tunein:",),
            "loxoneradio": ("loxoneradio:",),
            "custom_stream": ("tunein:",),
            "linein": ("linein/", "linein:"),
            "library_track": ("library:local:track:",),
            "library_folder": ("library:local:folder:",),
            "playlist": ("playlist:",),
            **{
                f"spotify_{name}": ("spotify:", "spotify@")
                for name in (
                    "track",
                    "playlist",
                    "album",
                    "artist",
                    "collection",
                    "show",
                    "episode",
                )
            },
        }
        if kind not in prefixes:
            continue
        label, path = item.get("name"), item.get("audiopath")
        if (
            not isinstance(label, str)
            or not label.strip()
            or len(label) > _MAX_NAME_LENGTH
            or any(ord(c) < _CONTROL_BOUNDARY for c in label)
            or not isinstance(path, str)
            or len(path) > _MAX_PATH_LENGTH
            or not any(path.startswith(prefix) and path[len(prefix) :].strip() for prefix in prefixes[kind])
            or any(ord(c) < _CONTROL_BOUNDARY for c in path)
        ):
            raise ValueError(message)
        if kind.startswith("spotify_") and path.startswith("spotify:"):
            # A favourite lacks the separately selected browser account. Do
            # not advertise an account-ambiguous URI as an exact selection.
            continue
        context = kind in {
            "library_folder",
            "playlist",
            "spotify_playlist",
            "spotify_album",
            "spotify_artist",
            "spotify_collection",
            "spotify_show",
        }
        choices.append(AudioFavourite(player_id, target, label, path, context))
    counts = {label: sum(c.label == label for c in choices) for label in {c.label for c in choices}}
    result = tuple(
        AudioFavourite(
            c.player_id,
            c.favourite_id,
            f"{c.label} (favourite {c.favourite_id})" if counts[c.label] > 1 else c.label,
            c.audio_path,
            c.is_context,
        )
        for c in choices
    )
    if len({c.label for c in result}) != len(result):
        raise ValueError(message)
    return result


def parse_spotify_accounts(payload: object) -> tuple[str, ...]:
    """Retain healthy configured account IDs, not names or another service's IDs."""
    message = "Spotify requires a bounded list of healthy configured accounts"
    if not isinstance(payload, list) or len(payload) > _MAX_SERVICE_ACCOUNTS:
        raise ValueError(message)
    result = []
    for row in payload:
        if not isinstance(row, dict):
            raise ValueError(message)  # noqa: TRY004 - one discovery-validation contract
        if row.get("cmd") != "spotify" or row.get("configerror") is not False:
            continue
        account = row.get("id")
        if not isinstance(account, str) or not re.fullmatch(r"[A-Za-z0-9_.@+-]{1,128}", account):
            raise ValueError(message)
        if account not in result:
            result.append(account)
    return tuple(result)


def passive_history_eligible(
    snapshot: AudioZoneMetadata | None, previous: AudioZoneMetadata | None,
    *, settled: bool, initial_generation: bool,
) -> bool:
    """Qualify passive last-good observations independently of host scheduling."""
    corroborated = bool(
        snapshot is not None and previous is not None
        and snapshot.native_mode == previous.native_mode == "play"
        and snapshot.event_idle and previous.event_idle
        and snapshot.event_active is previous.event_active is False
        and snapshot.received_at is not None and previous.received_at is not None
        and snapshot.received_at > previous.received_at
        and all(getattr(snapshot, field) == getattr(previous, field)
                for field in ("player_id", "source", "source_name", "audio_path", "parent_id"))
        and (snapshot.source in ("TuneIn", "Loxone Radio", "Line-In") or (
            snapshot.position is None or previous.position is None
            or snapshot.position > previous.position
        ))
    )
    return settled and (
        initial_generation or corroborated or (snapshot is not None and snapshot.native_mode == "pause")
    )


def native_selection_unchanged(original: AudioZoneMetadata | None, current: AudioZoneMetadata | None) -> bool:
    """Reject identity changes and positive paused seeks throughout preparation."""
    return bool(
        original is not None
        and current is not None
        and all(
            getattr(original, field) == getattr(current, field)
            for field in (
                "player_id",
                "source",
                "source_name",
                "audio_path",
                "parent_id",
                "native_mode",
            )
        )
        and not (
            original.source == "Spotify"
            and original.native_mode in ("pause", "stop")
            and original.position is not None
            and current.position is not None
            and abs(original.position - current.position) > _PAUSED_POSITION_TOLERANCE
        )
    )


def source_matches(
    snapshot: AudioZoneMetadata,
    path: str,
    *,
    is_context: bool = False,
    account_user: str | None = None,
) -> bool:
    """Match exact inputs/tracks or native parent context, including account scope."""
    if account_user is not None and path.startswith(("spotify:", "spotify@")):
        if snapshot.source != "Spotify" or snapshot.source_name != account_user:
            return False
    observed = snapshot.parent_id if is_context else snapshot.audio_path
    if observed == path:
        return True
    if path.startswith("linein/"):
        return observed == "linein:" + path.removeprefix("linein/")
    match = re.fullmatch(r"spotify@([A-Za-z0-9_.@+-]{1,128}):(.+)", path)
    return bool(match and account_user and snapshot.source_name == account_user and observed == "spotify:" + match[2])


async def _source_matcher(
    commands: AudioServerCommands, path: str, *, is_context: bool = False,
    expected_account: str | None = None, source_return: bool = False,
) -> Callable[[AudioZoneMetadata], bool]:
    account_user = None
    match = re.fullmatch(r"spotify@([A-Za-z0-9_.@+-]{1,128}):(.+)", path)
    if expected_account is not None and (match is None or match[1] != expected_account):
        msg = "Spotify account changed; no source command was sent"
        raise AudioCommandError(msg)
    if match:
        rows = await commands.async_service_accounts()
        if match[1] not in parse_spotify_accounts(rows):
            msg = "Spotify account changed; no source command was sent"
            raise AudioCommandError(msg)
        account_user = next(
            row.get("user")
            for row in rows
            if row.get("cmd") == "spotify" and row.get("id") == match[1] and row.get("configerror") is False
        )
        if source_return and (
            not isinstance(account_user, str) or not account_user.strip()
            or sum(row.get("cmd") == "spotify" and row.get("user") == account_user for row in rows) != 1
        ):
            msg = "Native Spotify account is not positively matched"
            raise AudioCommandError(msg)
    if source_return:
        native_path = "spotify:" + match[2] if match else path
        provider = next((
            (prefix, label) for prefix, label in (
                ("spotify:", "Spotify"), ("library:local:", "Local Library"),
                ("tunein:", "TuneIn"), ("loxoneradio:", "Loxone Radio"),
            ) if native_path.startswith(prefix)
        ), None)
        if provider is not None:
            prefix, label = provider
            return lambda snapshot: bool(
                snapshot.source == label and snapshot.audio_path and snapshot.audio_path.startswith(prefix)
                and snapshot.audio_path.removeprefix(prefix).strip()
                and (prefix != "spotify:" or snapshot.source_name == account_user)
            )
    return lambda snapshot: source_matches(snapshot, path, is_context=is_context, account_user=account_user)


async def async_select_catalogue(  # noqa: PLR0913 - pin the pre-preparation native selection
    commands: AudioServerCommands,
    metadata: AudioMetadataCoordinator,
    player_id: int,
    target: CatalogueTarget,
    *,
    is_available: Callable[[], bool],
    expected_native: AudioZoneMetadata | None = None,
    source_return: bool = False,
    on_confirmed: Callable[[AudioZoneMetadata], None] | None = None,
    environment: SourceEnvironment | None = None,
) -> None:
    """Revalidate source ownership and share the existing no-blind-replay fence."""
    from .catalogue import parse_line_inputs  # noqa: PLC0415 - break catalogue/source import cycle

    if target.kind not in ("item", "input") and not target.is_context:
        msg = "Only a discovered playable source can be selected"
        raise ValueError(msg)
    if target.service == "linein" and not any(
        item.folder == target.folder and item.audio_path == target.audio_path
        for item in parse_line_inputs(await commands.async_source_inputs())
    ):
        msg = "Input changed or became unavailable; no command was sent"
        raise AudioCommandError(msg)
    observed_path = target.audio_path
    if target.service == "spotify" and observed_path.startswith("spotify:"):
        observed_path = "spotify@" + target.account + ":" + observed_path.removeprefix("spotify:")
    # Validate the selected account and resolve its observed user together from
    # one discovery snapshot, rather than issuing the same native read twice.
    matches = await _source_matcher(
        commands, observed_path, is_context=target.is_context,
        expected_account=target.account if target.service == "spotify" else None, source_return=source_return,
    )
    content_matches = matches
    if not source_return and target.parent_path is not None:
        matches = lambda snapshot: content_matches(snapshot) and snapshot.parent_id == target.parent_path

    async def send(guard: Callable[[], bool], sent: Callable[[], None]) -> None:
        parent = (
            {"parent_path": target.parent_path, "parent_index": target.parent_index}
            if target.parent_path is not None else {}
        )
        await commands.async_play_catalogue(
            player_id, target.service, target.account, target.folder, is_current=guard, on_send=sent, **parent,
        )

    observed = await (environment or SourceEnvironment()).async_observed_change(
        commands, metadata, player_id, send, matches,
        is_available=is_available, expected_native=expected_native,
        on_confirmed=None if source_return else on_confirmed,
    )
    if source_return and on_confirmed is not None and is_available():
        on_confirmed(observed or metadata.get(player_id))
    saved = target.return_session
    if not source_return or saved is None or observed is None:
        return

    def can_restore() -> bool:
        snapshot = metadata.get(player_id)
        return bool(
            is_available() and snapshot is not None
            and snapshot.player_id == player_id
            and snapshot.event_idle and snapshot.event_active is False
            and snapshot.native_mode == "play" and matches(snapshot)
            and snapshot.audio_path == saved.audio_path
            and snapshot.source_name == saved.source_name
            and snapshot.duration is not None and saved.position is not None
            and 0 < saved.position < snapshot.duration - 1
            and snapshot.playback_restrictions is not None and snapshot.playback_restrictions & 32
            and player_id not in commands.announcement_fences
            and player_id not in commands.source_fences
        )

    if can_restore():
        # An ordinary bounded native request, with a last current-target check
        # after authentication. Its echo is not observed playback progress.
        # Optional failure cannot undo already confirmed source playback.

        try:
            await commands.async_seek(
                player_id, saved.position, is_current=can_restore,
            )
        except (AudioCommandError, ValueError, TimeoutError):
            _LOGGER.warning("Optional audio position restore failed; confirmed source playback is retained")
        if can_restore() and on_confirmed is not None:
            on_confirmed(metadata.get(player_id))


async def async_select_favourite(
    commands: AudioServerCommands,
    metadata: AudioMetadataCoordinator,
    favourite: AudioFavourite,
    *,
    is_available: Callable[[], bool],
    expected_native: AudioZoneMetadata | None = None,
    source_return: bool = False,
    on_confirmed: Callable[[AudioZoneMetadata], None] | None = None,
    environment: SourceEnvironment | None = None,
) -> None:
    """Revalidate an advertised choice, send once, and await exact source evidence."""
    fresh = parse_room_favourites(await commands.async_room_favourites(favourite.player_id), favourite.player_id)
    if favourite not in fresh:
        message = "Configured favourite changed; refresh the source choices before selecting"
        raise AudioCommandError(message)
    if favourite.audio_path.startswith(("linein/", "linein:")):
        from .catalogue import parse_line_inputs  # noqa: PLC0415 - cycle boundary

        expected = favourite.audio_path.replace("linein/", "linein:", 1)
        if not any(item.audio_path == expected for item in parse_line_inputs(await commands.async_source_inputs())):
            msg = "Favourite input became unavailable; no source command was sent"
            raise AudioCommandError(msg)
    matches = await _source_matcher(
        commands, favourite.audio_path, is_context=favourite.is_context, source_return=source_return,
    )

    async def send(guard: Callable[[], bool], sent: Callable[[], None]) -> None:
        await commands.async_play_room_favourite(
            favourite.player_id, favourite.favourite_id, is_current=guard, on_send=sent
        )

    observed = await (environment or SourceEnvironment()).async_observed_change(
        commands,
        metadata,
        favourite.player_id,
        send,
        matches,
        is_available=is_available,
        expected_native=expected_native,
        on_confirmed=None if source_return else on_confirmed,
    )
    if source_return and on_confirmed is not None and is_available():
        on_confirmed(observed or metadata.get(favourite.player_id))


async def async_select_radio_station(  # noqa: PLR0913 - exact source and shared observation dependencies
    commands: AudioServerCommands,
    metadata: AudioMetadataCoordinator,
    player_id: int,
    service: str,
    audio_path: str,
    *,
    is_available: Callable[[], bool],
    expected_native: AudioZoneMetadata | None = None,
    source_return: bool = False,
    on_confirmed: Callable[[AudioZoneMetadata], None] | None = None,
    environment: SourceEnvironment | None = None,
) -> None:
    """Share the existing source fence and require fresh exact-station feedback."""

    async def send(guard: Callable[[], bool], sent: Callable[[], None]) -> None:
        await commands.async_play_radio_station(player_id, service, audio_path, is_current=guard, on_send=sent)

    matches = await _source_matcher(commands, audio_path, source_return=source_return)
    observed = await (environment or SourceEnvironment()).async_observed_change(
        commands,
        metadata,
        player_id,
        send,
        matches,
        is_available=is_available,
        expected_native=expected_native,
        on_confirmed=None if source_return else on_confirmed,
    )
    if source_return and on_confirmed is not None and is_available():
        on_confirmed(observed or metadata.get(player_id))


async def async_seek_track(
    commands: AudioServerCommands,
    metadata: AudioMetadataCoordinator,
    player_id: int,
    position: float,
    *,
    is_available: Callable[[], bool],
    environment: SourceEnvironment | None = None,
) -> AudioZoneMetadata:
    """Require matching wire progress as well as the native position echo."""
    expected = position

    async def send(guard: Callable[[], bool], sent: Callable[[], None]) -> None:
        nonlocal expected
        echoed = await commands.async_seek(player_id, position, is_current=guard, on_send=sent)
        if isinstance(echoed, bool) or not isinstance(echoed, (int, float)) or abs(echoed - position) > 1:
            msg = "Invalid seek echo; no replay was sent"
            raise AudioCommandError(msg)
        expected = echoed

    def matches(snapshot: AudioZoneMetadata) -> bool:
        return bool(is_available() and snapshot.position is not None and abs(snapshot.position - expected) <= 1)

    observed = await (environment or SourceEnvironment()).async_observed_change(
        commands,
        metadata,
        player_id,
        send,
        matches,
        is_available=is_available,
        allow_noop=False,
        retain_progress=True,

        timeout=10,
    )
    snapshot = metadata.get(player_id)
    if (
        observed is None
        or snapshot is None
        or snapshot.position is None
        or not is_available()
        or snapshot.native_mode != "play"
    ):
        msg = "Seek progress was not observed"
        raise AudioCommandError(msg)
    return observed


async def async_native_catalogue_noop(
    commands: AudioServerCommands,
    metadata: AudioMetadataCoordinator,
    player_id: int,
    target: CatalogueTarget,
    *,
    is_available: Callable[[], bool],
    resume_paused: bool = False,
    environment: SourceEnvironment | None = None,
) -> bool:
    """Recognize an active source account, not its obsolete historical context."""
    original = metadata.get(player_id)
    if (
        original is None or original.source != "Spotify"
        or original.native_mode not in (("play", "pause") if resume_paused else ("play",))
        or not original.audio_path or not original.audio_path.startswith(("spotify:track:", "spotify:episode:"))
    ):
        return False
    rows = await commands.async_service_accounts()
    if target.account not in parse_spotify_accounts(rows):
        msg = "Spotify account changed; no source command was sent"
        raise AudioCommandError(msg)
    users = [
        row.get("user")
        for row in rows
        if row.get("cmd") == "spotify" and row.get("id") == target.account and row.get("configerror") is False
    ]
    user = users[0] if len(users) == 1 else None
    matched = (
        isinstance(user, str)
        and bool(user)
        and not any(
            row.get("cmd") == "spotify" and row.get("id") != target.account and row.get("user") == user for row in rows
        )
    )
    current = metadata.get(player_id)
    if not is_available() or not native_selection_unchanged(original, current):
        msg = "Native no-op was superseded; no command was sent"
        raise AudioCommandError(msg)
    if matched and current.source_name != user:
        # Optional provider loss cannot convert another native account's
        # current playback into permission for a remembered-item fallback.
        raise AudioCommandError("Native Spotify account does not match the selected source")
    qualified = bool(
        matched
        and current.player_id == player_id
        and current.event_idle
        and current.event_active is False
        and current.source_name == user
    )
    if qualified and current.native_mode == "pause":
        await (environment or SourceEnvironment()).async_observed_change(
            commands, metadata, player_id,
            lambda available, sent: commands.async_spotify_handoff(
                player_id, target.account, is_current=available, on_send=sent,
            ),
            lambda row: (
                row.native_mode == "play" and row.player_id == player_id
                and row.event_idle and row.event_active is False
                and row.source == "Spotify" and row.source_name == user
                and bool(row.audio_path and row.audio_path.startswith(("spotify:track:", "spotify:episode:")))
            ),
            is_available=is_available, allow_noop=False, expected_native=original,
        )
    return qualified


async def async_observed_change(  # noqa: C901, PLR0913, PLR0915 - explicit send/observation/fence ownership
    commands: AudioServerCommands,
    metadata: AudioMetadataCoordinator,
    player_id: int,
    send: Callable[[Callable[[], bool], Callable[[], None]], Awaitable[None]],
    matches: Callable[[AudioZoneMetadata], bool],
    *,
    is_available: Callable[[], bool],
    allow_noop: bool = True,
    retain_progress: bool = False,
    expected_native: AudioZoneMetadata | None = None,
    on_confirmed: Callable[[AudioZoneMetadata], None] | None = None,

    timeout: float = 15,  # noqa: ASYNC109 - bounded native feedback deadline, not a public HA action
    clock: Callable[[], datetime] = dt_util.utcnow,
) -> AudioZoneMetadata | None:
    """Retain uncertain writes until exact fresh target feedback or client close."""
    if player_id in (fences := commands.source_fences) or player_id in commands.announcement_fences:
        message = "Another player action is active or uncertain; no content was sent"
        raise AudioCommandError(message)

    def selection_current() -> bool:
        snapshot = metadata.get(player_id)
        return bool(
            snapshot is not None
            and snapshot.player_id == player_id
            and (expected_native is None or native_selection_unchanged(expected_native, snapshot))
        )

    if not selection_current() or not is_available():
        msg = "Native source selection was superseded before dispatch"
        raise AudioCommandError(msg)

    def target_playing() -> bool:
        return bool(
            (snapshot := metadata.get(player_id))
            and snapshot.event_active is False
            and snapshot.event_idle
            and snapshot.native_mode == "play"
            and matches(snapshot)
        )

    if allow_noop and is_available() and target_playing():

        if on_confirmed is not None:
            on_confirmed(metadata.get(player_id))
        return None
    finished = asyncio.get_running_loop().create_future()
    finished.add_done_callback(lambda future: None if future.cancelled() else future.exception())
    dispatched = completed = send_settled = False
    waiter_active = True
    settlement_sample = object()
    dispatched_at = None
    observed = None
    observation = asyncio.get_running_loop().create_future()
    observations = getattr(commands, "source_observations", None)
    if not isinstance(observations, dict):
        observations = commands.source_observations = {}
    observations[player_id] = observation

    def release() -> None:
        remove()
        if observations.get(player_id) is observation:
            observations.pop(player_id)
        if not observation.done():
            observation.cancel()
        if fences.get(player_id) is release:
            fences.pop(player_id)
        if not finished.done():
            finished.cancel()

    def updated() -> None:
        nonlocal completed, observed
        snapshot = metadata.get(player_id)
        valid = bool(
            snapshot
            and snapshot.event_active is False
            and snapshot.event_idle
            and snapshot.native_mode == "play"
            # A terminal action no longer owns an entity generation. Keep its
            # exact-target settlement observer, not its obsolete dispatch guard:
            # a refused later request must not make this fence permanent.
            and (not waiter_active or is_available())
            and player_id not in commands.announcement_fences
            and dispatched_at is not None
            and snapshot.received_at is not None
            and dispatched_at <= snapshot.received_at <= clock()
        )
        if (
            dispatched
            and snapshot
            and snapshot.received_at is not None
            and snapshot.received_at is not settlement_sample
            and dispatched_at is not None
            and dispatched_at <= snapshot.received_at <= clock()
        ):
            if valid and matches(snapshot):
                if not (retain_progress and observed is not None and snapshot.position == 0):
                    observed = snapshot
                    # Feedback can precede a rejection or transport failure.
                    # Publish successful history only after the send settles.
                    if send_settled and waiter_active and on_confirmed is not None:
                        on_confirmed(snapshot)
                    if not observation.done():
                        observation.set_result(None)
            elif retain_progress and valid and observed is not None:
                # Once qualified, retain genuine positive progress, not a later
                # passive zero placeholder (including after a zero-target seek).
                if snapshot.position is not None and snapshot.position > 0:
                    observed = snapshot
            elif not (retain_progress and valid):
                observed = None
        if send_settled and observed and valid:
            completed = True
            if not finished.done():
                finished.set_result(None)
            # Seek progress can advance before the awakened waiter resumes.
            # Keep observing until it consumes the qualified clock snapshot.
            if not retain_progress or not waiter_active:
                release()
        elif (snapshot is None or snapshot.event_active is not False) and not finished.done():
            finished.set_exception(AudioCommandError("Source event stream lost or preempted; no replay was sent"))

    def is_current() -> bool:
        return bool(
            not finished.done()
            and is_available()
            and (dispatched or selection_current())
            and (snapshot := metadata.get(player_id)) is not None
            and snapshot.event_active is False
            and snapshot.event_idle
            and player_id not in commands.announcement_fences
            and (not allow_noop or not target_playing())
        )

    def on_send() -> None:
        nonlocal dispatched, settlement_sample, dispatched_at
        snapshot = metadata.get(player_id)
        settlement_sample = snapshot.received_at if snapshot else None
        dispatched_at = clock()
        dispatched = True


    remove = metadata.async_add_listener(player_id, updated)

    fences[player_id] = release
    try:
        if not is_current():
            message = "Source state is unavailable or active; no content was sent"
            raise AudioCommandError(message)
        await send(is_current, on_send)
        # Native source/progress events can precede the command echo. Require
        # fresh post-SEND evidence plus successful settlement, in either order.
        send_settled = True

        if not finished.done():
            updated()
        async with asyncio.timeout(timeout):
            await asyncio.shield(finished)

        return observed
    finally:
        # Failed/cancelled writes cannot consume observations that arrived while
        # the write was unresolved. Only later feedback or client close can release.
        waiter_active = False
        send_settled = True
        if not dispatched or completed:
            release()
        else:

            observed = None
            # Receiver timer callbacks retain the exact wire sample timestamp
            # object; they are not new feedback after uncertain settlement.
            settlement_sample = snapshot.received_at if (snapshot := metadata.get(player_id)) else None


# Historical private import retained for source-compatible offline consumers.
_async_observed_change = async_observed_change
