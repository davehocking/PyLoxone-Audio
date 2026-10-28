"""Synthetic review10 transport/lifecycle and persistent-device regressions."""

# ruff: noqa: S101, INP001, ANN001, D103, SLF001
import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock
from Crypto.PublicKey import RSA
import pytest
from homeassistant.exceptions import HomeAssistantError
from test_audioserver_playback import SyntheticAudioSocket
from test_spotify_continuity import native
from test_spotify_continuity_review import entity_boundary
from custom_components.loxone.pyloxone_api import audioserver as wire





@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["remove", "stop", "source"])
async def test_native_play_prepared_before_newer_action_cannot_dispatch(hass, monkeypatch, change):
    entered, release = asyncio.Event(), asyncio.Event()

    class BlockingSocket(SyntheticAudioSocket):
        """Hold real synthetic authentication before the guarded player send."""

        async def send(self, message: str) -> None:
            """Expose the pre-dispatch suspension without mocking async_execute."""
            if message.startswith("secure/authenticate/"):
                entered.set()
                await release.wait()
            if message == "audio/7/play":
                self.sent.append(message)
                self.queue.put_nowait('{"play_result":true}')
            else:
                await super().send(message)

    entity, _, snapshots, _, _, _ = entity_boundary(hass)
    client = wire.AudioServerCommands("audio.example.invalid", lambda: ("synthetic-user", "synthetic-active-token"))
    entity._audio_commands = client
    socket = BlockingSocket(RSA.generate(2048))
    monkeypatch.setattr(wire, "connect", lambda *_args, **_kwargs: socket)
    task = asyncio.create_task(entity.async_media_play())
    try:
        async with asyncio.timeout(1):
            await entered.wait()
        if change == "remove":
            await entity.async_will_remove_from_hass()
        elif change == "stop":
            await entity.async_media_stop()
        else:
            snapshots[0] = native("tunein:station:newer-household-choice")
    finally:
        release.set()
        result = (await asyncio.gather(task, return_exceptions=True))[0]
        await client.async_close()
    assert isinstance(result, (HomeAssistantError, asyncio.CancelledError))
    assert "audio/7/play" not in socket.sent
    assert socket.closed
