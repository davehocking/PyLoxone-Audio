"""Entry-owned optional Audioserver metadata, shared by the entry's players."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
import logging
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit

from .native import (
    AudioCommandError,
    AudioServerCommands,
    AudioServerListener,
    AudioZoneMetadata,
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
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        for task in tuple(self._recoveries.values()):
            task.cancel()
        await asyncio.gather(*tuple(self._recoveries.values()), return_exceptions=True)
        self._bindings.clear()
        self._playing.clear()
        self._active_since.clear()
        self._stale.clear()
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
        self._bindings[player_id] = binding

        def remove() -> None:
            if self._bindings.get(player_id) is binding:
                del self._bindings[player_id]
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
            remaining = self._remaining(player)
            if remaining > 0:
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
        for player in tuple(self._playing):
            if self._remaining(player) > 0:
                continue
            if player not in self._stale:
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
            self._recoveries[player] = self._create_task(
                self._async_reconcile(player, binding)
            )
        self._schedule_check()

    async def _async_reconcile(self, player: int, binding: _RecoveryBinding) -> None:
        """Read only, with host intent, receiver generation and sample fences."""
        commands, intent, available = binding
        generation = intent()

        def current() -> bool:
            return bool(
                self._create_task is not None
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
                    seek_supported=bool(
                        row.playback_restrictions is not None
                        and row.playback_restrictions & 32
                    ),
                )
        for row in updates:
            self._stale.discard(row.player_id)
        player_ids = (
            {row.player_id for row in updates} if updates else set(self._listeners)
        )
        for player_id in player_ids:
            self._notify(player_id)
        self._check_freshness()
