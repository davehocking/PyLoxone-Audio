"""Real HA services/catalogue with one authenticated synthetic native session."""
import asyncio
import json
from pathlib import Path
from time import perf_counter
import pytest
from homeassistant.exceptions import HomeAssistantError
from custom_components.loxone.pyloxone_api import audioserver as wire
from test_room_transport_fences_ha import room_peer as room_peer
from test_audio_grouping_ha import grouped_setup as grouped_setup
from test_audio_grouping_ha import audio_setup as audio_setup
from test_audioserver_playback import SyntheticAudioSocket, rsa_key as rsa_key

_REAL_READS = {name: getattr(wire.AudioServerCommands, name) for name in (
    'async_service_accounts', 'async_source_inputs', 'async_media_folder',
)}


@pytest.fixture
async def reusable_peer(hass, room_peer, monkeypatch, rsa_key):
    p = room_peer
    p.sockets.clear()
    p.wires = []
    p.reject = False
    p.delays = (0, 0, 0, 0)
    p.on_command = None
    for name, method in _REAL_READS.items():
        monkeypatch.setattr(p.co.audio_commands, name, method.__get__(p.co.audio_commands))
    class Socket(SyntheticAudioSocket):
        async def __aenter__(self):
            await asyncio.sleep(p.delays[0])
            return await super().__aenter__()

        async def __aexit__(self, *args):
            await asyncio.sleep(p.delays[2])
            return await super().__aexit__(*args)

        async def send(self, message):
            if message.startswith('secure/authenticate/'):
                await asyncio.sleep(p.delays[1])
            if message.startswith('audio/') and message != 'audio/cfg/getkey/full':
                self.sent.append(message)
                p.wires.append(message)
                if p.on_command is not None:
                    await p.on_command(message)
                action = message.split('/')[2]
                if action in ('play', 'pause'):
                    reply = {action + '_result': not p.reject}
                elif action == 'getservices':
                    reply = {'getservices_result': []}
                elif action == 'getinputs':
                    reply = {'getinputs_result': []}
                elif action == 'getradios':
                    reply = {'getradios_result': []}
                elif action == 'getroomfavs':
                    reply = {'getroomfavs_result': [{'id': int(message.split('/')[3]), 'start': 0, 'totalitems': 0, 'items': []}]}
                elif action in ('getmediafolder', 'getservicefolder'):
                    reply = {action + '_result': [{'start': 0, 'totalitems': 0, 'items': []}]}
                else:
                    raise AssertionError('Unhandled synthetic native command: ' + message)
                await asyncio.sleep(p.delays[3])
                self.queue.put_nowait(json.dumps({'command': message, **reply}))
            else:
                await super().send(message)
    def connect(*args, **kwargs):
        socket = Socket(rsa_key)
        p.sockets.append(socket)
        return socket
    monkeypatch.setattr(wire, 'connect', connect)
    owned_commands = p.co.audio_commands
    try:
        yield p
    finally:
        await owned_commands.async_close()


async def test_registered_room_services_reuse_entry_owned_session(hass, reusable_peer):
    p = reusable_peer
    for action in ('play', 'pause', 'play'):
        await hass.services.async_call('loxone', 'audio_room_transport', {'action': action}, target={'entity_id': p.ids[1]}, blocking=True)
    assert p.wires == ['audio/1/play', 'audio/1/pause', 'audio/1/play']
    assert len(p.sockets) == 1
    assert sum(m.startswith('secure/authenticate/') for s in p.sockets for m in s.sent) == 1
    assert not p.sockets[0].closed
    assert not p.co.audio_grouping.native._requests
    p.co.api.send_websocket_command.assert_not_awaited()


async def test_actual_browse_journey_reuses_session_and_yields_to_room_service(hass, reusable_peer):
    p = reusable_peer
    entity = p.g.entities[p.ids[1]]
    await p.g.feed(p.entry)
    browse = await entity.async_browse_media()
    assert browse.children
    assert 'audio/cfg/getservices' in p.wires
    await entity.async_browse_media(media_content_id='pyloxone-audio:inputs')
    assert 'audio/cfg/getinputs' in p.wires
    await hass.services.async_call('loxone', 'audio_room_transport', {'action': 'pause'}, target={'entity_id': p.ids[1]}, blocking=True)
    assert p.wires[-1] == 'audio/1/pause'
    assert len(p.sockets) == 1
    p.reject = True
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call('loxone', 'audio_room_transport', {'action': 'play'}, target={'entity_id': p.ids[1]}, blocking=True)
    assert p.wires.count('audio/1/play') == 1
    p.co.api.send_websocket_command.assert_not_awaited()


@pytest.mark.parametrize('delays', [(0.02, 0.06, 0.03, 0.005), (0.02, 0.10, 0.15, 0.005)])
async def test_owning_cold_warm_latency_benchmark(hass, reusable_peer, delays):
    from pyloxone_audio.diagnostic_events import DiagnosticEmitter
    p = reusable_peer
    p.delays = delays
    events = []
    p.co.audio_commands.diagnostics = DiagnosticEmitter(b'synthetic', events.append)
    p.co.audio_commands.diagnostics.enabled = True
    durations = []
    for action in ('play', 'pause', 'play', 'pause'):
        start = perf_counter()
        await hass.services.async_call('loxone', 'audio_room_transport', {'action': action}, target={'entity_id': p.ids[1]}, blocking=True)
        durations.append((perf_counter() - start) * 1000)
    assert p.wires == ['audio/1/play', 'audio/1/pause', 'audio/1/play', 'audio/1/pause']
    assert all(e['outcome'] == 'returned' for e in events if e['stage'] == 'request_finished')
    result = {'delays_s': delays, 'durations_ms': durations, 'wires': p.wires,
              'handshakes': sum(m.startswith('secure/authenticate/') for s in p.sockets for m in s.sent),
              'closed_before_unload': sum(s.closed for s in p.sockets), 'events': events}
    Path('owning-benchmark-' + str(delays[2]) + '.json').write_text(json.dumps(result, indent=2))


async def test_real_catalogue_yields_transport_lock_between_requests(hass, reusable_peer):
    p = reusable_peer
    await p.g.feed(p.entry)
    entity = p.g.entities[p.ids[1]]
    entered, release = asyncio.Event(), asyncio.Event()
    async def hold(command):
        if command == 'audio/cfg/getservices':
            entered.set()
            await release.wait()
    p.on_command = hold
    browse = asyncio.create_task(entity.async_browse_media())
    pause = None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        pause = asyncio.create_task(hass.services.async_call('loxone', 'audio_room_transport', {'action': 'pause'}, target={'entity_id': p.ids[1]}, blocking=True))
        for _ in range(100):
            if p.co.audio_commands._lock._waiters:
                break
            await asyncio.sleep(0)
        assert p.co.audio_commands._lock._waiters
        release.set()
        await asyncio.wait_for(asyncio.gather(browse, pause), 4)
        assert p.wires[:2] == ['audio/cfg/getservices', 'audio/1/pause']
        assert 'audio/cfg/getinputs' in p.wires[2:]
        assert len(p.sockets) == 1
    finally:
        release.set()
        for task in (browse, pause):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(t for t in (browse, pause) if t is not None), return_exceptions=True)


async def test_real_mapped_receiver_updates_session_retention(hass, reusable_peer):
    p = reusable_peer
    await p.call()
    await p.emit(1, mode='play')
    await p.emit(2, mode='play')
    assert set(p.co.audio_commands._playback_until) == {1, 2}
    await p.emit(1, mode='pause')
    assert set(p.co.audio_commands._playback_until) == {2}
    await p.emit(2, mode='stop')
    assert not p.co.audio_commands._playback_until
    saved = p.co.audio_commands._session
    await hass.config_entries.async_unload(p.entry.entry_id)
    assert saved.reader.done()
    assert saved._idle_timer is None
    assert p.sockets[0].closed


@pytest.mark.parametrize('boundary', [
    'stable', 'token', 'availability', 'registry', 'generation', 'topology',
    'group', 'source', 'announcement', 'source-fence', 'announcement-fence',
    'spotify', 'source-identity', 'account-identity', 'event', 'capability',
    'capability-notify', 'removed',
])
async def test_warm_registered_room_service_preserves_revocation_fences(
    hass, reusable_peer, monkeypatch, boundary,
):
    from test_room_transport_fences_ha import perturb
    p = reusable_peer
    await p.emit(1)
    await p.call()
    assert len(p.sockets) == 1
    prior_wires = list(p.wires)
    async def change(_command):
        if boundary != 'stable':
            await perturb(p, boundary, monkeypatch)
    p.on_command = change
    if boundary == 'stable':
        await p.call()
        assert not p.sockets[0].closed
    else:
        # Disabling an entity legitimately cancels its owning HA service task;
        # other revoked requests use the ordinary translated refusal.
        refusal = asyncio.CancelledError if boundary == 'registry' else HomeAssistantError
        with pytest.raises(refusal):
            await p.call()
    assert p.wires == prior_wires + ['audio/1/play']
    assert len(p.sockets) == 1
    assert sum(m.startswith('secure/authenticate/') for s in p.sockets for m in s.sent) == 1
    assert not p.co.audio_grouping.native._requests
    assert not p.co.audio_grouping.native._scope
    p.co.api.send_websocket_command.assert_not_awaited()
