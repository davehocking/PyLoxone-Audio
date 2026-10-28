"""Entry-owned optional Audioserver metadata, shared by the entry's players."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import logging
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit

from .native import AudioServerCommands, AudioServerListener, AudioZoneMetadata, audioserver_uri
from .diagnostic_events import diagnostic_event, diagnostics_enabled

if TYPE_CHECKING:
    from collections.abc import Callable

    from collections.abc import Coroutine
    from typing import Any

_LOGGER = logging.getLogger(__name__)


class AudioMetadataCoordinator:
    """Keep the event connection independent of ordinary Miniserver controls."""

    def __init__(self, host: str) -> None:
        """Prepare a receive-only listener without opening a connection."""
        self._listeners: dict[int, set[Callable[[], None]]] = {}
        self._client = AudioServerListener(host, self._on_update)
        self._http_origin = audioserver_uri(host).replace("ws://", "http://", 1)
        self._task: asyncio.Task[None] | None = None
        self.diagnostics = None

    def async_start(self, create_task: Callable[[Coroutine[Any, Any, None]], asyncio.Task[None]] = asyncio.create_task) -> None:
        """Start observation with an optional host-owned task scheduler."""
        if self._task is not None and not self._task.done():
            return
        self._task = create_task(self._client.async_run())

    async def async_stop(self) -> None:
        """Cancel and await the connection before dropping entity subscriptions."""
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._listeners.clear()

    def get(self, player_id: int) -> AudioZoneMetadata | None:
        """Return an exact player's current metadata, never a name-based guess."""
        return self._client.get(player_id)

    async def async_ensure_snapshot(
        self, commands: AudioServerCommands, player_id: int, *, is_current: Callable[[], bool],
    ) -> None:
        """Read missing initial state only for an explicit opted-in action."""
        await self._client.async_ensure_snapshot(
            player_id, lambda: commands.async_player_status(player_id, is_current=is_current), is_current=is_current,
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

    def async_add_listener(self, player_id: int, listener: Callable[[], None]) -> Callable[[], None]:
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
                diagnostic_event(self.diagnostics, "disconnected", transport="audio_server")
            for row in updates:
                diagnostic_event(self.diagnostics, "feedback", transport="audio_server", player=row.player_id,
                                 content=row.audio_path, parent=row.parent_id, account=row.source_name,
                                 position=row.position, duration=row.duration, mode=row.native_mode,
                                 event_idle=row.event_idle, event_active=row.event_active,
                                 shuffle=row.shuffle, repeat={0: "off", 1: "all", 3: "one"}.get(row.repeat),
                                 seek_supported=bool(row.playback_restrictions is not None and row.playback_restrictions & 32))
        player_ids = {row.player_id for row in updates} if updates else set(self._listeners)
        for player_id in player_ids:
            for listener in tuple(self._listeners.get(player_id, ())):
                try:
                    listener()
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Audioserver metadata subscriber failed (%s)", type(err).__name__)
