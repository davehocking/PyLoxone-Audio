"""Entry-owned optional Audioserver metadata, shared by the entry's players."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit

from .native import (
    AudioCommandError,
    AudioServerCommands,
    AudioServerListener,
    AudioZoneMetadata,
    audio_mode_supported,
    audioserver_uri,
)
from .clock import utcnow
from .diagnostic_events import diagnostic_event, diagnostics_enabled

# Application freshness, not a declaration that a quiet WebSocket is broken.
_ACTIVE_SAMPLE_SECONDS = 30.0
_READ_SPACING_SECONDS = 1.0
_MAX_RETRY_SECONDS = 300.0
_RECOVERY_TIMEOUT_SECONDS = 15.0

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from datetime import datetime
    from typing import Any


type _RecoveryBinding = tuple[
    AudioServerCommands, Callable[[], int], Callable[[], bool]
]
type _TaskFactory = Callable[[Coroutine[Any, Any, None]], asyncio.Task[None]]

_LOGGER = logging.getLogger(__name__)


@dataclass
class _ModeRecovery:
    """An obligation, not cached mode values or permission to reuse a reply."""

    binding: _RecoveryBinding
    intent: int
    context: tuple[int, str, str | None, str]
    authenticated: Callable[[], bool]
    observed_at: float


class AudioMetadataCoordinator:
    """Keep the event connection independent of ordinary Miniserver controls."""

    def __init__(self, host: str) -> None:
        """Prepare a receive-only listener without opening a connection."""
        self._listeners: dict[int, set[Callable[[], None]]] = {}
        self._client = AudioServerListener(host, self._on_update)
        self._http_origin = audioserver_uri(host).replace("ws://", "http://", 1)
        self._task: asyncio.Task[None] | None = None
        self._playing: set[int] = set()
        self._active_since: dict[int, datetime] = {}
        self._stale: set[int] = set()
        self._requested_refresh: set[int] = set()
        self._mode_recovery: dict[int, _ModeRecovery] = {}
        self._mode_revoked: set[int] = set()
        self._bindings: dict[int, _RecoveryBinding] = {}
        self._recoveries: dict[int, asyncio.Task[None]] = {}
        self._retry_at: dict[int, float] = {}
        self._retry_delay: dict[int, float] = {}
        self._read_after = 0.0
        self._timer: asyncio.TimerHandle | None = None
        self._create_task: _TaskFactory | None = None
        self.diagnostics = None

    def async_start(
        self,
        create_task: Callable[
            [Coroutine[Any, Any, None]], asyncio.Task[None]
        ] = asyncio.create_task,
    ) -> None:
        """Start observation with an optional host-owned task scheduler."""
        if self._task is not None and not self._task.done():
            return
        self._create_task = create_task
        self._task = create_task(self._client.async_run())
        self._schedule_check()

    async def async_stop(self) -> None:
        """Cancel scheduled reads and await owned IO before dropping subscriptions."""
        self._create_task = None
        self._mode_recovery.clear()
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        for task in tuple(self._recoveries.values()):
            task.cancel()
        await asyncio.gather(*tuple(self._recoveries.values()), return_exceptions=True)
        for player, binding in self._bindings.items():
            binding[0].observe_playback(player, False)
        self._bindings.clear()
        self._playing.clear()
        self._active_since.clear()
        self._stale.clear()
        self._requested_refresh.clear()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._listeners.clear()

    def set_playing(self, player_id: int, playing: bool) -> None:
        """Use independent native playback feedback without certifying old content."""
        if playing:
            self._playing.add(player_id)
            self._active_since.setdefault(player_id, utcnow())
        else:
            if player_id in self._playing and self.get(player_id) is None:
                self._stale.add(player_id)
            self._playing.discard(player_id)
            self._requested_refresh.discard(player_id)
            self._mode_recovery.pop(player_id, None)
            self._active_since.pop(player_id, None)
            if task := self._recoveries.get(player_id):
                task.cancel()
        self._check_freshness()

    def _remaining(self, player_id: int) -> float:
        """Bound active display by sample age; untouched idle data need not expire."""
        if player_id in self._stale:
            return 0.0
        row = self._client.get(player_id)
        if row is not None and not row.has_observation:
            # A parsed bare player ID has a timestamp and default event_active
            # False, but no useful observation. Do not let repeated empty rows
            # postpone recovery. Sparse real data (including zero/False) still
            # has its ordinary bounded lifetime and must remain visible.
            return 0.0
        stamp = (
            row.received_at if row is not None else self._active_since.get(player_id)
        )
        if stamp is None:
            return 0.0
        age = (utcnow() - stamp).total_seconds()
        lifetime = _ACTIVE_SAMPLE_SECONDS
        if (
            row is not None
            and row.playback_mode == "play"
            and row.duration is not None
            and row.position is not None
        ):
            lifetime = min(lifetime, max(0.0, row.duration - row.position))
        return lifetime - age

    def get(self, player_id: int) -> AudioZoneMetadata | None:
        """Withhold expired active content from presentation AND command guards."""
        if player_id in self._stale or (
            player_id in self._playing and self._remaining(player_id) <= 0
        ):
            return None
        return self._client.get(player_id)

    def async_add_reconciler(
        self,
        player_id: int,
        commands: AudioServerCommands,
        *,
        intent: Callable[[], int],
        available: Callable[[], bool],
    ) -> Callable[[], None]:
        """Bind opted-in recovery to the actual entity's intent and lifecycle."""
        binding = (commands, intent, available)
        self._mode_recovery.pop(player_id, None)
        self._requested_refresh.discard(player_id)
        self._bindings[player_id] = binding

        def remove() -> None:
            if self._bindings.get(player_id) is binding:
                del self._bindings[player_id]
                commands.observe_playback(player_id, False)
                self.set_playing(player_id, False)

        return remove

    def _notify(self, player_id: int) -> None:
        """Publish invalidation without fabricating received feedback/disconnects."""
        for listener in tuple(self._listeners.get(player_id, ())):
            try:
                listener()
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Audioserver metadata subscriber failed (%s)", type(err).__name__
                )

    @staticmethod
    def _mode_context(row: AudioZoneMetadata) -> tuple[int, str, str | None, str] | None:
        """Qualify omissions only; explicit invalid/denied modes revoke repair."""
        if (
            row.source not in {"Spotify", "Local Library"}
            or (row.source == "Spotify" and row.source_name is None)
            or not row.event_idle or row.native_mode != "play"
            or not row.audio_path or row.parent_id is None
            or any(key in row.mode_fields_present and getattr(row, name) is None
                   for key, name in (("pbr", "playback_restrictions"), ("plshuffle", "shuffle"), ("plrepeat", "repeat")))
            or ("pbr" in row.mode_fields_present and (row.playback_restrictions is None
                or row.playback_restrictions & (2048 | 4096 | 8192) != (2048 | 4096 | 8192)))
        ):
            return None
        return row.player_id, row.source, row.source_name, row.parent_id

    def _mode_recovery_pending(self, player: int, observed: AudioZoneMetadata | None = None) -> bool:
        """Retain exact ownership across sparse progress, never across revocation."""
        obligation = self._mode_recovery.get(player)
        if obligation is None:
            return False
        row = observed if observed is not None else self._client.get(player)
        if (
            self._create_task is not None and player in self._playing
            and self._bindings.get(player) is obligation.binding
            and obligation.binding[1]() == obligation.intent
            and obligation.binding[2]() and obligation.authenticated()
            and row is not None
            # Bare rows do not supersede the native revision fence either.
            and (not row.has_observation or (
                self._mode_context(row) == obligation.context
                and not all(audio_mode_supported(row, op) for op in ("shuffle", "repeat"))
            ))
        ):
            return True
        self._mode_recovery.pop(player, None)
        self._requested_refresh.discard(player)
        return False

    def refresh_incomplete_modes(self, player_id: int, previous: AudioZoneMetadata | None) -> None:
        """Read new modes after a sparse ordinary track change; never merge.

        State stays unknown until the existing authenticated, revision-fenced
        status read supplies new values. Explicit denial/malformed fields and
        changed source/account/context, idle/event/stale data do not qualify.
        """
        row = self.get(player_id)
        if (
            player_id in self._mode_revoked
            or previous is None or row is None or player_id not in self._playing
            or row.source not in {"Spotify", "Local Library"}
            or not row.event_idle or row.native_mode != "play"
            or not previous.event_idle or previous.native_mode != "play"
            or not previous.audio_path or not row.audio_path or previous.audio_path == row.audio_path
            or previous.parent_id is None
            or any(getattr(previous, name) != getattr(row, name)
                   for name in ("player_id", "source", "source_name", "parent_id"))
            or (row.source == "Spotify" and row.source_name is None)
            or previous.received_at is None
            or not 0 <= (utcnow() - previous.received_at).total_seconds() < _ACTIVE_SAMPLE_SECONDS
            or any(key in row.mode_fields_present and getattr(row, name) is None
                   for key, name in (("pbr", "playback_restrictions"), ("plshuffle", "shuffle"), ("plrepeat", "repeat")))
            or ("pbr" in row.mode_fields_present and (row.playback_restrictions is None
                or row.playback_restrictions & (2048 | 4096 | 8192) != (2048 | 4096 | 8192)))
        ):
            return
        if any(
            audio_mode_supported(previous, operation)
            and not audio_mode_supported(row, operation)
            and not {"pbr", key} <= row.mode_fields_present
            for operation, key in (("shuffle", "plshuffle"), ("repeat", "plrepeat"))
        ):
            # A prior successful status read must not defer the next ordinary
            # track's repair until its freshness deadline. Failed-read backoff
            # and the shared serial read spacing still apply.
            if player_id not in self._retry_delay:
                self._retry_at.pop(player_id, None)
            binding = self._bindings.get(player_id)
            context = self._mode_context(row)
            if binding is not None and context is not None and binding[2]():
                if not self._mode_recovery_pending(player_id):
                    self._mode_recovery[player_id] = _ModeRecovery(
                        binding, binding[1](), context, binding[0].authentication_guard(),
                        asyncio.get_running_loop().time(),
                    )
                self._requested_refresh.add(player_id)
                self._check_freshness()

    def _schedule_check(self) -> None:
        """One entry-owned timer; no idle polling or permanently running helper."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self._create_task is None or not self._playing:
            return
        loop = asyncio.get_running_loop()
        delays = []
        for player in self._playing:
            self._mode_recovery_pending(player)
            remaining = self._remaining(player)
            if remaining > 0 and (
                player not in self._requested_refresh
                or (player in self._mode_recovery and player in self._retry_delay
                    and self._mode_recovery[player].observed_at < self._retry_at.get(player, 0))
            ):
                # Fresh observations already invoke _check_freshness. After a
                # failed mode read they are the retry trigger; do not poll a
                # still-fresh sparse stream between those observations. A quiet
                # stream keeps its ordinary freshness deadline as the fallback.
                delays.append(remaining)
            elif player not in self._recoveries:
                delays.append(
                    max(
                        _READ_SPACING_SECONDS,
                        self._retry_at.get(player, 0) - loop.time(),
                        self._read_after - loop.time(),
                    )
                )
        if delays:
            self._timer = loop.call_later(max(0.01, min(delays)), self._check_freshness)

    def _check_freshness(self) -> None:
        """Invalidate active old content and deduplicate bounded recovery reads."""
        if self._create_task is None:
            return
        loop = asyncio.get_running_loop()
        # A fresh explicit omission must not sit behind every room whose
        # ordinary content happens to expire together. All reads still share
        # the same ownership, spacing and per-player failure backoff.
        for player in sorted(self._playing, key=lambda p: p not in self._requested_refresh):
            self._mode_recovery_pending(player)
            remaining = self._remaining(player)
            if remaining > 0 and player not in self._requested_refresh:
                continue
            obligation = self._mode_recovery.get(player)
            if (remaining > 0 and obligation is not None and player in self._retry_delay
                and obligation.observed_at < self._retry_at.get(player, 0)):
                continue
            if remaining <= 0 and player not in self._stale:
                self._stale.add(player)
                self._notify(player)
            binding = self._bindings.get(player)
            if (
                binding is None
                or self._recoveries
                or loop.time() < self._read_after
                or loop.time() < self._retry_at.get(player, 0)
            ):
                continue
            if not binding[2]():
                continue
            self._read_after = loop.time() + _READ_SPACING_SECONDS
            obligation = self._mode_recovery.get(player)
            if obligation is None:
                self._requested_refresh.discard(player)
            self._recoveries[player] = self._create_task(
                self._async_reconcile(player, binding, obligation)
            )
        self._schedule_check()

    async def _async_reconcile(
        self, player: int, binding: _RecoveryBinding, obligation: _ModeRecovery | None = None,
    ) -> None:
        """Read only, with host intent, receiver generation and sample fences."""
        commands, intent, available = binding
        generation = intent()

        def current() -> bool:
            mode_current = obligation is None or (
                self._mode_recovery.get(player) is obligation
                and self._mode_recovery_pending(player)
            )
            return bool(
                mode_current and self._create_task is not None
                and self._bindings.get(player) is binding
                and player in self._playing
                and intent() == generation
                and available()
            )

        try:
            # HA may eagerly run a background coroutine during create_task;
            # register ownership before a synchronous read can finish/clean up.
            await asyncio.sleep(0)
            async with asyncio.timeout(_RECOVERY_TIMEOUT_SECONDS):
                await self._client.async_refresh_snapshot(
                    player,
                    lambda: commands.async_player_status(player, is_current=current),
                    is_current=current,
                )
            self._retry_delay.pop(player, None)
            # Even an authentic snapshot at the old track's end must not cause
            # a tight read loop or monopolise recovery for the other rooms.
            remaining = self._remaining(player)
            self._retry_at[player] = asyncio.get_running_loop().time() + (
                remaining if remaining > 0 else _ACTIVE_SAMPLE_SECONDS
            )
        except AudioCommandError, TimeoutError, OSError, ValueError:
            # Fixed local backoff only; never retry or fall back to a media write.
            delay = self._retry_delay.get(player, _ACTIVE_SAMPLE_SECONDS)
            self._retry_at[player] = asyncio.get_running_loop().time() + delay
            self._retry_delay[player] = min(delay * 2, _MAX_RETRY_SECONDS)
        finally:
            self._recoveries.pop(player, None)
            self._schedule_check()

    async def async_ensure_snapshot(
        self,
        commands: AudioServerCommands,
        player_id: int,
        *,
        is_current: Callable[[], bool],
    ) -> None:
        """Read missing OR expired state for an explicit opted-in action."""

        async def read() -> AudioZoneMetadata:
            return await commands.async_player_status(player_id, is_current=is_current)

        if self.get(player_id) is None and self._client.get(player_id) is not None:
            await self._client.async_refresh_snapshot(
                player_id, read, is_current=is_current
            )
        else:
            await self._client.async_ensure_snapshot(
                player_id, read, is_current=is_current
            )

    def artwork_url(self, cover_url: str | None) -> str | None:
        """Resolve optional artwork against this entry's configured Audioserver."""
        if not cover_url:
            return None
        try:
            resolved = urljoin(self._http_origin, cover_url)
            parsed = urlsplit(resolved)
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.port == 0
            ):
                return None
        except ValueError:
            return None
        return resolved

    def async_add_listener(
        self, player_id: int, listener: Callable[[], None]
    ) -> Callable[[], None]:
        """Subscribe one player; the entity owns its unsubscribe callback."""
        self._listeners.setdefault(player_id, set()).add(listener)

        def unsubscribe() -> None:
            if listeners := self._listeners.get(player_id):
                listeners.discard(listener)
            if player_id in self._listeners and not self._listeners[player_id]:
                del self._listeners[player_id]

        return unsubscribe

    def _on_update(self, updates: tuple[AudioZoneMetadata, ...]) -> None:
        """Notify affected players; an empty update invalidates every snapshot."""
        # Only exact opted-in mapped bindings qualify retention. This does not
        # alter content/permission freshness, source proof or recovery policy.
        if not updates:
            for player, binding in self._bindings.items():
                binding[0].observe_playback(player, False)
        for row in updates:
            if binding := self._bindings.get(row.player_id):
                # Reconciler eligibility includes source/group/operation fences;
                # those do not make a mapped room's positive playback unknown.
                # Binding removal/stop owns retention invalidation separately.
                binding[0].observe_playback(row.player_id, row.native_mode == "play")
        if diagnostics_enabled(self.diagnostics):
            if not updates:
                diagnostic_event(
                    self.diagnostics, "disconnected", transport="audio_server"
                )
            for row in updates:
                diagnostic_event(
                    self.diagnostics,
                    "feedback",
                    transport="audio_server",
                    player=row.player_id,
                    content=row.audio_path,
                    parent=row.parent_id,
                    account=row.source_name,
                    position=row.position,
                    duration=row.duration,
                    mode=row.native_mode,
                    event_idle=row.event_idle,
                    event_active=row.event_active,
                    shuffle=row.shuffle,
                    repeat={0: "off", 1: "all", 3: "one"}.get(row.repeat),
                    playback_restrictions=row.playback_restrictions,
                    capability_present="pbr" in row.mode_fields_present,
                    capability_valid=row.playback_restrictions is not None,
                    seek_supported=bool(
                        row.playback_restrictions is not None
                        and row.playback_restrictions & 32
                    ),
                )
        for row in updates:
            self._stale.discard(row.player_id)
            owned = row.player_id in self._mode_recovery
            if not self._mode_recovery_pending(row.player_id, row):
                self._requested_refresh.discard(row.player_id)
                if owned:
                    self._mode_revoked.add(row.player_id)
            elif row.has_observation:
                self._mode_recovery[row.player_id].observed_at = asyncio.get_running_loop().time()
        if not updates:
            self._requested_refresh.clear()
            self._mode_recovery.clear()
        player_ids = (
            {row.player_id for row in updates} if updates else set(self._listeners)
        )
        for player_id in player_ids:
            self._notify(player_id)
        self._mode_revoked.clear()
        self._check_freshness()
