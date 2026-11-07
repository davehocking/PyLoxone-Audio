"""Frozen synthetic owning-service recurrence. No household input or I/O.

A missing HA source selection is deliberately not used as a queue-empty proof.
Parent enrichment remains a rejected ambiguous supersession, not a safe retry.
"""
import asyncio
import hashlib
import json
import time
from types import SimpleNamespace

import pytest
from homeassistant.exceptions import HomeAssistantError
from custom_components.loxone.const import SENDDOMAIN
from custom_components.loxone.pyloxone_api import audioserver as wire
from test_audio_grouping_ha import STATE, action, payload, row
from test_audio_grouping_ha import grouped_setup as grouped_setup
from test_audio_grouping_ha import audio_setup as audio_setup
from test_audioserver_playback import SyntheticAudioSocket
from test_audioserver_playback import rsa_key as rsa_key
from test_stage2_modes_ha import output


@pytest.fixture
async def playback_peer(hass, grouped_setup, audio_setup, monkeypatch, rsa_key, request):
    g = grouped_setup
    entry, co, ids = await g.setup()
    groups = {'pair': (1, 2), 'untouched': (5, 6)}
    await g.feed(entry, *(row(k, v) for k, v in groups.items()))
    callback = g.callbacks[entry.entry_id]['callback']
    await callback({**{f'play-{p}': 1 for p in ids}, **{f'volume-{p}': p * 10 for p in ids}})
    co.audio_commands._credentials = lambda: ('synthetic-user', 'synthetic-active-token')
    p = SimpleNamespace(g=g, co=co, ids=ids, entry=entry, groups=groups, sockets=[], rows={},
                        mode='normal', hook=None, source='library:local', sent=asyncio.Event(),
                        release=asyncio.Event(), outcomes=[], writes=[])

    async def emit(player=1, **fields):
        delivered = asyncio.get_running_loop().create_future()
        remove = co.audio_metadata.async_add_listener(player, lambda: delivered.done() or delivered.set_result(None))
        try:
            frame = {
                'playerid': player, 'mode': 'pause', 'eventype': 0,
                'audiopath': f'{p.source}:track:existing-{player}',
                'sourceName': 'Synthetic retained account', 'time': 20,
                'duration': 600, 'plshuffle': False, 'plrepeat': 0, 'pbr': 63,
                **fields,
            }
            p.rows[player] = frame
            audio_setup.queues[0].put_nowait(json.dumps({'audio_event': [frame]}))
            await asyncio.wait_for(delivered, 1)
        finally:
            remove()

    class Socket(SyntheticAudioSocket):
        async def send(self, message):
            if message.startswith('audio/cfg/dgroup/update/'):
                self.sent.append(message)
                parts = message.split('/')
                name = 'created' if parts[4] == 'new' else parts[4]
                players = tuple(map(int, parts[5].split(','))) if len(parts) > 5 else ()
                groups.pop(name, None)
                if players:
                    groups[name] = players
                await callback({STATE: payload(*(row(k, v) for k, v in groups.items()))})
                self.queue.put_nowait(json.dumps({'dgroup_update_result': {'id': name}}))
                return
            if message.startswith('audio/') and message != 'audio/cfg/getkey/full':
                self.sent.append(message)
                parts = message.split('/')
                if parts[-1] == 'status':
                    player = int(parts[1])
                    assert player in p.rows, 'A status read must bind existing exact-player evidence'
                    self.queue.put_nowait(json.dumps({'status_result': [p.rows[player]]}))
                    return
                if parts[1] == 'grouped':
                    mode, players = parts[2], tuple(map(int, parts[3].split(',')))
                    p.sent.set()
                    if p.hook:
                        await p.hook()
                    if p.mode == 'hold':
                        await p.release.wait()
                    if p.mode == 'silent':
                        return
                    result = False if p.mode == 'reject' else {'players': [
                        {'playerid': v, 'mode': mode} for v in (players[:1] if p.mode == 'partial' else players)]}
                    self.queue.put_nowait(json.dumps({f'grouped_{mode}_result': result}))
                else:
                    assert len(parts) == 3 and parts[2] in ('play', 'pause'), message
                    self.queue.put_nowait(json.dumps({parts[2] + '_result': True}))
                return
            await super().send(message)

    def connect(*args, **kwargs):
        s = Socket(rsa_key)
        p.sockets.append(s)
        return s

    monkeypatch.setattr(wire, 'connect', connect)

    async def volume(event):
        p.writes.append(dict(event.data))
        target = next(v for v in ids if action(v) == event.data['uuid'])
        await callback({f'volume-{target}': int(event.data['value'].split('/')[1])})

    remove = hass.bus.async_listen(SENDDOMAIN, volume)
    p.emit = emit
    # Preserve exact transport-write assertions while explicitly retaining ALL
    # extra read routes; do not silently discard them from the evidence.
    p.all_commands = lambda: [m for s in p.sockets for m in s.sent if m.startswith('audio/') and m != 'audio/cfg/getkey/full']
    p.status_commands = lambda: [m for m in p.all_commands() if m.endswith('/status')]
    p.sent_commands = lambda: [m for m in p.all_commands() if not m.endswith('/status')]
    async def call(domain, service, player=1, **data):
        try:
            await hass.services.async_call(domain, service, data, target={'entity_id': ids[player]}, blocking=True)
            result = 'success'
        except HomeAssistantError:
            result = 'HomeAssistantError'
        await hass.async_block_till_done()
        p.outcomes.append({'domain': domain, 'service': service, 'player': player, 'data': data, 'result': result})
        return result
    p.call = call
    try:
        yield p
    finally:
        output('preflight-peer-' + hashlib.sha256(request.node.nodeid.encode()).hexdigest() + '.json', {
            'node': request.node.nodeid, 'all_routes': p.all_commands(),
            'transport_writes': p.sent_commands(), 'status_reads': p.status_commands(),
            'all_sockets_closed': all(s.closed for s in p.sockets)})
        remove()


def assert_clean(p):
    n = p.co.audio_grouping.native
    assert not n._scope and not n._tasks and not n._requests and not n._lock.locked()
    assert p.co.audio_commands._socket is None and all(s.closed for s in p.sockets)
    assert all(not e._transport_tasks for e in p.g.entities.values())


@pytest.mark.parametrize('source', ['library:local', 'tunein'])
@pytest.mark.parametrize('failure', ['reject', 'partial', 'deadline', 'cancel', 'enrichment'])
async def test_failed_playback_keeps_confirmed_membership_and_registered_routes(hass, playback_peer, source, failure):
    p = playback_peer
    p.source = source
    for player in (1, 2):
        await p.emit(player)
    owner, native = p.co.audio_grouping, p.co.audio_grouping.native
    original = native.snapshot
    generation = native._generation
    assert native.timeout == 8
    assert all(p.g.entities[p.ids[v]]._source_task is None for v in (1, 2))
    # Real native queue metadata exists before any select_source service.
    assert p.co.audio_metadata.get(1).audio_path
    p.mode = {'deadline': 'silent', 'cancel': 'hold'}.get(failure, failure)
    if failure == 'enrichment':
        async def enrich():
            for player in (1, 2):
                await p.emit(player, mode='play', time=24.945, parent={'id': 'retained-parent'})
            await p.g.callbacks[p.entry.entry_id]['callback']({'play-1': 2, 'play-2': 2})
        p.hook = enrich
        p.mode = 'normal'
    start = time.monotonic()
    if failure == 'cancel':
        task = asyncio.create_task(hass.services.async_call('media_player', 'media_play', {}, target={'entity_id': p.ids[1]}, blocking=True))
        await asyncio.wait_for(p.sent.wait(), 2)
        task.cancel()
        result = (await asyncio.gather(task, return_exceptions=True))[0]
        assert isinstance(result, asyncio.CancelledError)
        failed = 'CancelledError'
    else:
        failed = await p.call('media_player', 'media_play')
        assert failed == 'HomeAssistantError'
    elapsed = time.monotonic() - start
    if failure == 'deadline':
        assert 7.8 <= elapsed < 11
    assert p.sent_commands() == ['audio/grouped/play/1,2']
    assert native.snapshot is original
    assert native._generation > generation
    assert_clean(p)
    p.mode, p.hook = 'normal', None
    # No grouping feedback/reconnect/reset between failure and these services.
    before = len(p.outcomes)
    for player in (1, 2, 3, 5):
        for service in ('media_play', 'media_pause'):
            await p.call('media_player', service, player)
    for player in (1, 2):
        for mode in ('pause', 'play'):
            await p.call('loxone', 'audio_room_transport', player, action=mode)
    await p.call('media_player', 'volume_set', 1, volume_level=.4)
    await p.call('loxone', 'audio_room_volume', 2, volume_percent=21)
    async def manage(player, action, members=(), group_id=None):
        d = owner.control_descriptor(player)
        await p.call('loxone', 'audio_group_manage', player, action=action,
                     revision=d['revision'] if d else 'missing-after-playback',
                     members=[p.ids[v] for v in members], **({'group_id': group_id} if group_id else {}))
    await manage(1, 'add', (3,), 'pair')
    await manage(3, 'remove', group_id='pair')
    await manage(1, 'destroy', group_id='pair')
    await manage(3, 'create', (4,))
    await manage(3, 'remove', group_id='created')  # leader dissolution
    output(f'playback-{source.replace(":", "-")}-{failure}.json', {
        'failure': failed, 'elapsed': elapsed, 'source': source,
        'enrichment_still_rejected': failure == 'enrichment', 'outcomes': p.outcomes,
        'commands': p.sent_commands(), 'volume_writes': p.writes,
        'uncertain': native.uncertain, 'groups': p.groups, 'acoustic_success': 'UNVERIFIED',
    })
    assert [r['result'] for r in p.outcomes[before:]] == ['success'] * (len(p.outcomes) - before)
    assert p.groups == {'untouched': (5, 6)}
    assert not native.uncertain
    assert_clean(p)


@pytest.mark.parametrize('change', ['stable', 'parent-enrichment', 'source', 'account', 'content', 'parent-replacement', 'parent-ABA'])
async def test_resume_metadata_qualification_remains_fail_closed(hass, playback_peer, change):
    p = playback_peer
    initial = {} if change == 'parent-enrichment' else {'parent': {'id': 'parent-A'}}
    for player in (1, 2):
        await p.emit(player, **initial)
    async def change_during_reply():
        fields = {
            'stable': initial, 'parent-enrichment': {'parent': {'id': 'parent-A'}},
            'source': {'audiopath': 'tunein:station:replacement'},
            'account': {'sourceName': 'Synthetic different account'},
            'content': {'audiopath': 'library:local:track:replacement'},
            'parent-replacement': {'parent': {'id': 'parent-B'}},
            'parent-ABA': {'parent': {'id': 'parent-B'}},
        }[change]
        await p.emit(2, mode='play', time=24.945, **{**initial, **fields})
        if change == 'parent-ABA':
            await p.emit(2, mode='play', time=29.506, **initial)
    p.hook = change_during_reply
    result = await p.call('media_player', 'media_play')
    output('resume-' + change + '.json', {'result': result, 'commands': p.sent_commands(),
        'metadata': repr(p.co.audio_metadata.get(2)), 'no_select_source': True})
    assert result == ('success' if change == 'stable' else 'HomeAssistantError')
    assert p.sent_commands() == ['audio/grouped/play/1,2']
    assert_clean(p)
