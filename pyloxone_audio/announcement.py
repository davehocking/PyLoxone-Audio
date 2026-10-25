"""Reviewed native announcement ownership; no HA resolution, conversion or login."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from .native import AudioCommandError, AudioServerCommands
from .metadata import AudioMetadataCoordinator

async def async_send_prepared_announcement(  # noqa: PLR0913, PLR0915
    session_provider: Callable[[], Any],
    commands: AudioServerCommands,
    metadata: AudioMetadataCoordinator,
    player_id: int,
    data: bytes,
    duration: float,
    volume: int,
) -> None:
    """Require this owned event to start/end; let native firmware restore media."""
    fences = getattr(commands, "announcement_fences", None)
    if fences is None:
        commands.announcement_fences = fences = {}
    if player_id in fences or player_id in getattr(commands, "source_fences", {}):
        message = "Previous announcement outcome is uncertain; no new announcement was sent"
        raise AudioCommandError(message)
    filename = f"pyloxone-{uuid4().hex}.wav"
    finished = asyncio.get_running_loop().create_future()
    # Caller cancellation must not discard ownership after a possible write.
    finished.add_done_callback(lambda future: None if future.cancelled() else future.exception())
    started = dispatched = completed = False

    def failed(message: str) -> None:
        nonlocal started
        # A later idle frame cannot complete a sequence whose ownership broke.
        # Only a newly observed exact-owned start can establish it again.
        started = False
        if not finished.done():
            finished.set_exception(AudioCommandError(message))

    def release() -> None:
        remove()
        if fences.get(player_id) is release:
            fences.pop(player_id)
        if not finished.done():
            finished.cancel()

    def updated() -> None:
        nonlocal started, completed
        snapshot = metadata.get(player_id)
        if snapshot is None:
            failed("Announcement event stream was lost; playback may have occurred; no replay was sent")
            return
        try:
            parsed = urlsplit(snapshot.audio_path or "")
        except ValueError:
            failed("Malformed native event path; playback may have occurred; no replay was sent")
            return
        owned = parsed.scheme == "file" and parsed.path.rsplit("/", 1)[-1] == filename
        if dispatched and snapshot.event_active is True and owned:
            started = True
        elif started and snapshot.event_active is False and snapshot.event_idle and not owned:
            completed = True
            if not finished.done():
                finished.set_result(None)
            release()
        elif snapshot.event_active is True and not owned:
            failed("Another native event intervened; playback may have occurred; no replay was sent")

    def is_current() -> bool:
        snapshot = metadata.get(player_id)
        return not finished.done() and snapshot is not None and snapshot.event_active is False and snapshot.event_idle

    def on_send() -> None:
        nonlocal dispatched
        dispatched = True

    remove = metadata.async_add_listener(player_id, updated)
    fences[player_id] = release
    try:
        if not is_current():
            message = "Native event state is unavailable or active; no announcement was sent"
            raise AudioCommandError(message)
        await commands.async_upload_announcement(session_provider(), filename, data)
        if not is_current():
            message = "Native event state changed; no announcement was sent"
            raise AudioCommandError(message)
        await commands.async_announce(player_id, filename, volume, is_current=is_current, on_send=on_send)
        async with asyncio.timeout(duration + 15):
            await asyncio.shield(finished)
    finally:
        if not dispatched or completed:
            release()
            if not finished.done():
                finished.cancel()
        # Otherwise retain ownership until the exact owned start/end is observed.
        # ACK loss/cancellation never authorises a potentially overlapping send.


