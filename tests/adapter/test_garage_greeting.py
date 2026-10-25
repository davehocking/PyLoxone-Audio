"""Synthetic contracts reproducing the independently observed event/greeting order.

Real HA entry/service path and real client crypto, no household IO or payloads.
"""
# ruff: noqa: S101, INP001, ANN001, ANN202, SLF001, F811, F401, D103
import asyncio
import json
from unittest.mock import AsyncMock
import pytest
from homeassistant.exceptions import HomeAssistantError
from test_audioserver_playback import SyntheticAudioSocket, rsa_key
from test_audioserver_ha import audio_setup, zone_entity_id
from test_audio_catalogue import catalogue_commands
from custom_components.loxone.pyloxone_api import audioserver as wire


def prefixed(socket, frames):
    greeting = socket.queue.get_nowait()
    for frame in frames:
        socket.queue.put_nowait(frame)
    socket.queue.put_nowait(greeting)
    return socket


@pytest.mark.asyncio
@pytest.mark.parametrize('field', ['audio_event', 'audio_sync_event'])
async def test_known_unsolicited_events_before_greeting_authenticate_once(monkeypatch, rsa_key, field):
    socket = prefixed(SyntheticAudioSocket(rsa_key), [json.dumps({field: []})] * 70)
    monkeypatch.setattr(wire, 'connect', lambda *a, **k: socket)
    client = wire.AudioServerCommands('audio.example.invalid', lambda: ('synthetic-user', 'synthetic-active-token'))
    await client.async_execute(13, 'play')
    assert socket.sent.count('audio/cfg/getkey/full') == 1
    assert len([s for s in socket.sent if s.startswith('secure/authenticate/')]) == 1
    assert socket.sent.count('audio/13/play') == 1
    assert socket.closed


@pytest.mark.asyncio
@pytest.mark.parametrize('bad', ['bad greeting', b'bad', '{}', '{"audio_event":true}', '{"error":"denied","audio_event":[]}'])
async def test_unknown_or_negative_greeting_still_rejects_without_auth_or_play(monkeypatch, rsa_key, bad):
    socket = prefixed(SyntheticAudioSocket(rsa_key), [bad])
    monkeypatch.setattr(wire, 'connect', lambda *a, **k: socket)
    client = wire.AudioServerCommands('audio.example.invalid', lambda: ('synthetic-user', 'synthetic-active-token'))
    with pytest.raises(wire.AudioCommandError):
        await client.async_execute(13, 'play')
    assert socket.sent == [] and socket.closed


@pytest.mark.asyncio
async def test_endless_ready_pre_greeting_events_obey_wall_deadline(monkeypatch, rsa_key):
    socket = SyntheticAudioSocket(rsa_key)
    async def noise():
        return '{"audio_event":[]}'
    monkeypatch.setattr(socket, 'recv', noise)
    monkeypatch.setattr(wire, 'connect', lambda *a, **k: socket)
    client = wire.AudioServerCommands('audio.example.invalid', lambda: ('synthetic-user', 'synthetic-active-token'), timeout=0.03)
    start = asyncio.get_running_loop().time()
    with pytest.raises(wire.AudioCommandError):
        await asyncio.wait_for(client.async_execute(13, 'play'), timeout=1)
    assert asyncio.get_running_loop().time() - start < 0.5
    assert not socket.sent and socket.closed


@pytest.mark.asyncio
async def test_event_prefix_never_weakens_authentication_result(monkeypatch, rsa_key):
    socket = prefixed(SyntheticAudioSocket(rsa_key), ['{"audio_event":[]}'])
    socket.auth_result = 'authentication unsuccessful'
    monkeypatch.setattr(wire, 'connect', lambda *a, **k: socket)
    client = wire.AudioServerCommands('audio.example.invalid', lambda: ('synthetic-user', 'synthetic-active-token'))
    with pytest.raises(wire.AudioCommandError):
        await client.async_execute(13, 'play')
    assert 'audio/13/play' not in socket.sent and socket.closed


@pytest.mark.asyncio
async def test_stop_generation_during_greeting_prevents_late_send(monkeypatch, rsa_key):
    socket = prefixed(SyntheticAudioSocket(rsa_key), ['{"audio_event":[]}'])
    current = True
    receive = socket.recv
    async def changed():
        nonlocal current
        frame = await receive()
        if 'audio_event' in frame:
            current = False
        return frame
    monkeypatch.setattr(socket, 'recv', changed)
    monkeypatch.setattr(wire, 'connect', lambda *a, **k: socket)
    client = wire.AudioServerCommands('audio.example.invalid', lambda: ('synthetic-user', 'synthetic-active-token'))
    with pytest.raises(wire.AudioCommandError):
        await client.async_execute(13, 'play', is_current=lambda: current)
    assert 'audio/13/play' not in socket.sent and socket.closed


@pytest.mark.asyncio
async def test_real_ha_source_service_lifecycle_survives_event_before_greeting(hass, audio_setup, monkeypatch, rsa_key):
    commands = catalogue_commands()
    for name, value in vars(commands).items():
        monkeypatch.setattr(wire.AudioServerCommands, name, value)
    await audio_setup.setup(playback=True)
    entity = hass.data['media_player'].get_entity(zone_entity_id(hass, 7))
    entity._audio_commands._credentials = lambda: ('synthetic-user', 'synthetic-active-token')
    await audio_setup.queues[0].put(json.dumps({'audio_event': [{'playerid': 7, 'mode': 'stop', 'audiopath': 'tunein:station:before'}]}))
    await hass.async_block_till_done()
    other = hass.states.get(zone_entity_id(hass, 8))
    route = 'audio/7/linein/ABCDEF123456%231000001'
    class SourceSocket(SyntheticAudioSocket):
        async def send(self, message):
            if message != route:
                return await super().send(message)
            self.sent.append(message)
            self.queue.put_nowait(json.dumps({'command': message}))
            audio_setup.queues[0].put_nowait(json.dumps({'audio_event': [{'playerid': 7, 'mode': 'play', 'audiopath': 'linein:ABCDEF123456#1000001'}]}))
    socket = prefixed(SourceSocket(rsa_key), ['{"audio_event":[{"playerid":8,"mode":"stop"}]}'])
    monkeypatch.setattr(wire, 'connect', lambda *a, **k: socket)
    await hass.services.async_call('media_player', 'select_source', {'entity_id': entity.entity_id, 'source': 'Line-In'}, blocking=True)
    assert entity.source == 'Line-In'
    assert socket.sent.count(route) == 1 and socket.closed
    assert not entity._audio_commands.source_fences
    assert hass.states.get(zone_entity_id(hass, 8)) == other
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()
