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
from custom_components.loxone.spotify_continuity import SpotifySourceReturn, SpotifyReturnUnavailable


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["async_media_play", "async_media_next_track", "async_media_previous_track"])
async def test_rebinding_uncertain_device_cannot_bypass_transport_guards(hass, monkeypatch, action):
    first, _, _, _, _, _ = entity_boundary(hass)
    first._spotify_return.uncertain = True
    second, _, snapshots, commands, _, _ = entity_boundary(hass)
    commands.async_execute = AsyncMock()
    second.unique_id = "synthetic-replacement-room"
    second._audio_player_id = 8
    snapshots[0] = replace(native(), player_id=8)
    second._spotify_return = SpotifySourceReturn(
        hass, second._spotify_binding, second.unique_id, 8, commands, lambda: snapshots[0]
    )
    assert second._spotify_return.uncertain
    assert second._audio_player_id in commands.source_fences
    fire = MagicMock()
    monkeypatch.setattr(type(hass.bus), "async_fire", fire)
    with pytest.raises(HomeAssistantError):
        await getattr(second, action)()
    commands.async_execute.assert_not_awaited()
    fire.assert_not_called()


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


@pytest.mark.asyncio
@pytest.mark.parametrize("accounts", [None, 42, "not-an-account-list"])
async def test_malformed_optional_account_read_is_classified_not_type_error(hass, accounts):
    entity, session, _, commands, _, _ = entity_boundary(hass)
    commands.async_service_accounts = AsyncMock(return_value=accounts)
    with pytest.raises(SpotifyReturnUnavailable):
        await entity._spotify_return.async_capture(lambda: True)
    assert not session.calls
