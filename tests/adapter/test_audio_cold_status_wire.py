"""Cold bootstrap authenticates exact read and source sockets; no hardware IO."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from test_audioserver_playback import SyntheticAudioSocket, rsa_key
from test_audioserver_ha import audio_setup, zone_entity_id
from test_audio_catalogue import catalogue_commands
from test_garage_greeting import prefixed
from custom_components.loxone.pyloxone_api import audioserver as wire


@pytest.mark.asyncio
async def test_actual_ha_cold_source_reads_status_then_dispatches_once_with_real_crypto(hass, audio_setup, monkeypatch, rsa_key):
    commands = catalogue_commands()
    for name, value in vars(commands).items():
        monkeypatch.setattr(wire.AudioServerCommands, name, value)
    await audio_setup.setup(playback=True)
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    entity._audio_commands._credentials = lambda: ("synthetic-user", "synthetic-active-token")
    assert entity._audio_metadata.get(7) is None
    route = "audio/7/linein/ABCDEF123456%231000001"
    sockets = []

    class Socket(SyntheticAudioSocket):
        async def send(self, message):
            if message == "audio/7/status":
                self.sent.append(message)
                self.queue.put_nowait(json.dumps({"status_result": [{"playerid": 7, "mode": "stop", "audiopath": "tunein:station:before"}]}))
            elif message == route:
                self.sent.append(message)
                self.queue.put_nowait(json.dumps({"command": message}))
                audio_setup.queues[0].put_nowait(json.dumps({"audio_event": [{"playerid": 7, "mode": "play", "audiopath": "linein:ABCDEF123456#1000001"}]}))
            else:
                await super().send(message)

    def connect(*args, **kwargs):
        s = prefixed(Socket(rsa_key), ['{"audio_event":[{"playerid":8,"mode":"stop"}]}'])
        sockets.append(s)
        return s

    monkeypatch.setattr(wire, "connect", connect)
    await hass.services.async_call("media_player", "select_source", {"entity_id": entity.entity_id, "source": "Line-In"}, blocking=True)
    assert len(sockets) == 2
    assert [m for s in sockets for m in s.sent if m.startswith("audio/7/")] == ["audio/7/status", route]
    assert all(s.closed for s in sockets)
    assert entity._audio_metadata.get(8) is None
    assert entity.source == "Line-In"
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["select_source", "play_media"])
async def test_actual_ha_cold_spotify_uses_configured_native_account(hass, audio_setup, monkeypatch, kind):
    commands = catalogue_commands()
    for name, value in vars(commands).items():
        monkeypatch.setattr(wire.AudioServerCommands, name, value)
    monkeypatch.setattr(wire.AudioServerCommands, "async_recent_sources", AsyncMock(return_value={"items": [{"type": 7, "title": "Synthetic playlist", "audiopath": "spotify@owner:playlist:one"}], "ts": 0}))
    old = {"playerid": 7, "mode": "stop", "audiopath": "spotify:track:before", "sourceName": "Synthetic owner", "parent": {"id": "spotify:playlist:one"}}
    read = AsyncMock(return_value=wire.parse_audio_events({"audio_event": [old]})[0])
    monkeypatch.setattr(wire.AudioServerCommands, "async_player_status", read)
    await audio_setup.setup(playback=True)
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    assert entity._audio_metadata.get(7) is None
    sent = AsyncMock()

    async def play(self, player, service, account, item, *, is_current, on_send):
        assert (player, service, account, item) == (7, "spotify", "owner", "spotify@owner:playlist:one")
        assert is_current()
        on_send()
        await sent(player, service, account, item)
        audio_setup.queues[0].put_nowait(json.dumps({"audio_event": [{**old, "mode": "play"}]}))

    monkeypatch.setattr(wire.AudioServerCommands, "async_play_catalogue", play)
    if kind == "select_source":
        data = {"source": "Spotify"}
    else:
        media_id = await entity._radio_catalogue.async_source_selection("Spotify")
        data = {"media_content_type": "pyloxone_radio", "media_content_id": media_id}
    await hass.services.async_call("media_player", kind, {"entity_id": entity.entity_id, **data}, blocking=True)
    assert read.await_count == sent.await_count == 1
    assert entity._audio_metadata.get(8) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [TimeoutError, wire.AudioCommandError])
async def test_failed_status_read_cannot_seed_receiver_or_trigger_retry(failure):
    q = asyncio.Queue()
    async def messages():
        while True:
            yield await q.get()
    updates = []
    receiver = wire.AudioEventReceiver(updates.append)
    task = asyncio.create_task(receiver.async_listen(messages()))
    await asyncio.sleep(0)
    read = AsyncMock(side_effect=failure("Synthetic unavailable"))
    try:
        with pytest.raises(failure):
            await receiver.async_ensure_snapshot(7, read, is_current=lambda: True)
        read.assert_awaited_once()
        assert receiver.get(7) is None
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_disconnected_receiver_never_bootstraps_from_independent_status():
    receiver = wire.AudioEventReceiver(lambda _: None)
    read = AsyncMock()
    with pytest.raises(wire.AudioCommandError):
        await receiver.async_ensure_snapshot(7, read, is_current=lambda: True)
    read.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("player", [True, 0, -1, 7.5, "7/8"])
async def test_status_invalid_identity_sends_nothing(player, monkeypatch):
    owner = wire.AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "token"))
    request = AsyncMock()
    monkeypatch.setattr(owner, "_async_request", request)
    with pytest.raises(ValueError):
        await owner.async_player_status(player, is_current=lambda: True)
    request.assert_not_awaited()
