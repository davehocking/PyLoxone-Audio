"""Frozen actual-owning-service oracle; invented identities, real crypto, no hardware."""
import asyncio
import hashlib
import json
import os
from pathlib import Path

import pytest
from homeassistant.exceptions import HomeAssistantError
from custom_components.loxone.pyloxone_api import audioserver as wire
from test_audio_grouping_ha import audio_setup, grouped_setup, row
from test_audioserver_playback import SyntheticAudioSocket, rsa_key

FIELDS = ('source', 'source_name', 'audio_path', 'parent_id')
# Desired bounded semantics, frozen before any product change.
CASES = [
    ('complete-stable', 'parent-A', 'parent-A', 'parent-A', 'success', False),
    ('complete-progress', 'parent-A', 'parent-A', 'parent-A', 'success', False),
    ('qualified-enrichment', None, 'parent-A', 'parent-A', 'success', True),
    ('qualified-takeover', None, 'parent-A', 'parent-B', 'HomeAssistantError', True),
    ('known-parent-takeover', 'parent-A', 'parent-A', 'parent-B', 'HomeAssistantError', False),
    ('preflight-unavailable', None, False, 'parent-A', 'HomeAssistantError', True),
    ('preflight-sparse', None, None, 'parent-A', 'HomeAssistantError', True),
]


def native_row(player, parent, **extra):
    result = {'playerid': player, 'mode': 'pause', 'eventype': 0,
              'audiopath': f'library:local:track:existing-{player}',
              'sourceName': 'Synthetic retained account', 'time': 20,
              'duration': 600, 'pbr': 63}
    if parent is not None:
        result['parent'] = {'id': parent}
    result.update(extra)
    return result


@pytest.mark.parametrize('name,initial_parent,status_parent,after_parent,expected,needs_status', CASES, ids=[c[0] for c in CASES])
async def test_precommand_parent_qualification(hass, grouped_setup, audio_setup, monkeypatch, rsa_key,
                                              name, initial_parent, status_parent, after_parent, expected, needs_status):
    g = grouped_setup
    entry, co, ids = await g.setup()
    await g.feed(entry, row('pair', (1, 2)), row('untouched', (5, 6)))
    callback = g.callbacks[entry.entry_id]['callback']
    await callback({**{f'play-{p}': 1 for p in ids}, **{f'volume-{p}': p * 10 for p in ids}})
    co.audio_commands._credentials = lambda: ('synthetic-user', 'synthetic-active-token')
    observations, routes, sockets, phases = [], [], [], []

    def identity(player):
        m = co.audio_metadata.get(player)
        return None if m is None else [getattr(m, field) for field in FIELDS]

    async def emit(player, parent, **extra):
        future = asyncio.get_running_loop().create_future()
        remove = co.audio_metadata.async_add_listener(player, lambda: future.done() or future.set_result(None))
        frame = native_row(player, parent, **extra)
        try:
            audio_setup.queues[0].put_nowait(json.dumps({'audio_event': [frame]}))
            await asyncio.wait_for(future, 2)
        finally:
            remove()
        observations.append({'frame': frame, 'parsed_identity': identity(player)})

    for player in (1, 2):
        await emit(player, initial_parent if player == 2 else 'parent-A')
    original = co.audio_grouping.native.snapshot
    cache_before = co.audio_metadata.get(2)
    untouched_before = {p: hass.states.get(ids[p]).as_dict() for p in (5, 6)}
    cache_before_send = []

    class Socket(SyntheticAudioSocket):
        async def send(self, message):
            if message.startswith('audio/') and message != 'audio/cfg/getkey/full':
                self.sent.append(message)
                routes.append(message)
                if message.endswith('/status'):
                    phases.append('status-send')
                    assert message == 'audio/2/status'
                    result = False if status_parent is False else [native_row(2, status_parent)]
                    self.queue.put_nowait(json.dumps({'status_result': result}))
                    return
                assert message == 'audio/grouped/play/1,2', message
                phases.append('group-send')
                cache_before_send.append({'same_object': co.audio_metadata.get(2) is cache_before,
                                          'identity': identity(2)})
                await emit(2, after_parent, mode='play', time=24.945,
                           **({'title': 'Synthetic changed title'} if name == 'complete-progress' else {}))
                await callback({'play-1': 2, 'play-2': 2})
                self.queue.put_nowait(json.dumps({'grouped_play_result': {'players': [
                    {'playerid': p, 'mode': 'play'} for p in (1, 2)]}}))
                return
            await super().send(message)

    def connect(*args, **kwargs):
        socket = Socket(rsa_key)
        sockets.append(socket)
        return socket
    monkeypatch.setattr(wire, 'connect', connect)
    result = 'success'
    try:
        await hass.services.async_call('media_player', 'media_play', {}, target={'entity_id': ids[1]}, blocking=True)
    except HomeAssistantError:
        result = 'HomeAssistantError'
    await hass.async_block_till_done()
    native = co.audio_grouping.native
    receipt = {'name': name, 'result': result, 'expected': expected, 'routes': routes,
               'phases': phases, 'observations': observations, 'cache_before_send': cache_before_send,
               'status_parent': status_parent, 'membership_unchanged': native.snapshot is original,
               'all_sockets_closed': all(s.closed for s in sockets),
               'sockets': len(sockets), 'authenticated_sockets': sum(any(m.startswith('secure/authenticate/') for m in s.sent) for s in sockets),
               'acoustic_success': 'UNVERIFIED'}
    out = Path(os.environ['STAGE2_EVIDENCE_ROOT'])
    out.mkdir(parents=True, exist_ok=True)
    (out / (name + '.json')).write_text(json.dumps(receipt, indent=2) + '\n')
    assert receipt['membership_unchanged'] and not native.uncertain
    assert not native._scope and not native._requests and not native._tasks and not native._lock.locked()
    assert co.audio_commands._socket is None and receipt['all_sockets_closed']
    assert all(not e._transport_tasks for e in g.entities.values())
    assert {p: hass.states.get(ids[p]).as_dict() for p in (5, 6)} == untouched_before
    co.api.send_websocket_command.assert_not_awaited()
    assert result == expected, receipt
    expected_routes = (['audio/2/status'] if needs_status else [])
    if name != 'preflight-unavailable':
        expected_routes += ['audio/grouped/play/1,2']
        assert cache_before_send == [{'same_object': True, 'identity': [getattr(cache_before, f) for f in FIELDS]}]
    assert routes == expected_routes, receipt
    assert len(sockets) == len(expected_routes) == receipt['authenticated_sockets']
