"""Immutable owner-failure oracle: actual owning HA, invented rooms, offline I/O.

Not a recording or physical zero-volume explanation. The default eight-second
operation deadline is deliberately exercised, not replaced by a unit timeout.
"""
import asyncio
import json
import time

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from custom_components.loxone.const import SENDDOMAIN
from custom_components.loxone.pyloxone_api import audioserver as wire
from test_audio_grouping_ha import STATE, action, payload, row, structure
from test_audio_grouping_ha import grouped_setup as grouped_setup
from test_audio_grouping_ha import audio_setup as audio_setup
from test_audioserver_playback import SyntheticAudioSocket
from test_audioserver_playback import rsa_key as rsa_key
from test_stage2_modes_ha import output


@pytest.mark.parametrize('players', [(7, 8), (11, 3)])
async def test_owner_unconfirmed_zero_timeout_preserves_real_subsequent_routes(
    hass, grouped_setup, audio_setup, monkeypatch, rsa_key, players,
):
    g = grouped_setup
    g.source.clear()
    g.source.update(structure(12))
    entry, co, _ = await g.setup()
    ids = {p: er.async_get(hass).async_get_entity_id('media_player', 'loxone', action(p)) for p in range(1, 13)}
    first, second = players
    outside = (1, 2)
    free = tuple(p for p in ids if p not in {*players, *outside})
    groups = {'owner-pair': players, 'untouched': outside}
    await g.feed(entry, *(row(k, v) for k, v in groups.items()))
    callback = g.callbacks[entry.entry_id]['callback']
    await callback({**{f'play-{p}': 2 for p in ids}, **{f'volume-{p}': 20 for p in ids}, f'volume-{first}': 10, f'volume-{second}': 38})
    await audio_setup.queues[0].put(json.dumps({'audio_event': [{'playerid': first, 'mode': 'play', 'audiopath': 'library:local:track:synthetic-owner', 'time': 0, 'duration': 600, 'plshuffle': False, 'plrepeat': 0, 'pbr': 63}]}))
    await hass.async_block_till_done()
    owner = co.audio_grouping
    assert owner.native.timeout == 8
    assert len(owner.entities) == 12
    assert hass.states.get(ids[first]).attributes['volume_level'] == .24
    original_snapshot = owner.native.snapshot
    initial_generation = owner.native._generation
    writes, sockets, progress, outcomes, snapshots = [], [], [], [], []
    first_sent = asyncio.Event()
    finished = asyncio.Event()
    accepting = False
    co.audio_commands._credentials = lambda: ('synthetic-user', 'synthetic-active-token')

    class Socket(SyntheticAudioSocket):
        async def send(self, message):
            if message.startswith('audio/cfg/dgroup/update/'):
                self.sent.append(message)
                parts = message.split('/')
                name = 'fresh-created' if parts[4] == 'new' else parts[4]
                members = tuple(map(int, parts[5].split(','))) if len(parts) > 5 else ()
                groups.pop(name, None)
                if members:
                    groups[name] = members
                await callback({STATE: payload(*(row(k, v) for k, v in groups.items()))})
                self.queue.put_nowait(json.dumps({'dgroup_update_result': {'id': name}}))
            elif message.startswith('audio/grouped/'):
                self.sent.append(message)
                _, _, mode, raw = message.split('/')
                self.queue.put_nowait(json.dumps({f'grouped_{mode}_result': {'players': [{'playerid': int(p), 'mode': mode} for p in raw.split(',')]}}))
            elif message.startswith('audio/') and message.rsplit('/', 1)[1] in ('play', 'pause'):
                self.sent.append(message)
                self.queue.put_nowait(json.dumps({message.rsplit('/', 1)[1] + '_result': True}))
            else:
                await super().send(message)

    def connect(*args, **kwargs):
        socket = Socket(rsa_key)
        sockets.append(socket)
        return socket

    monkeypatch.setattr(wire, 'connect', connect)

    async def volume_sent(event):
        writes.append(dict(event.data))
        first_sent.set()
        if accepting:
            player = next(p for p in ids if action(p) == event.data['uuid'])
            await callback({f'volume-{player}': int(event.data['value'].split('/')[1])})

    async def ongoing_progress():
        await first_sent.wait()
        while not finished.is_set():
            index = len(progress) + 1
            await audio_setup.queues[0].put(json.dumps({'audio_event': [{'playerid': first, 'mode': 'play', 'audiopath': 'library:local:track:synthetic-owner', 'time': index, 'duration': 600, 'plshuffle': False, 'plrepeat': 0, 'pbr': 63}]}))
            await callback({f'play-{first}': 2})
            progress.append(index)
            await asyncio.sleep(.25)

    def capture(label):
        snapshots.append({'label': label, 'target': ids[first], 'states': {eid: hass.states.get(eid).as_dict() for eid in ids.values()}})

    async def call(domain, service, player, **data):
        try:
            await hass.services.async_call(domain, service, data, target={'entity_id': ids[player]}, blocking=True)
            result = 'success'
        except HomeAssistantError as error:
            result = type(error).__name__
        outcomes.append({'domain': domain, 'service': service, 'player': player, 'data': data, 'result': result})
        await hass.async_block_till_done()
        return result

    async def manage(which, kind, members=(), group_id=None):
        descriptor = owner.control_descriptor(which)
        revision = descriptor['revision'] if descriptor else 'missing-after-volume-timeout'
        return await call('loxone', 'audio_group_manage', which, action=kind, revision=revision, members=[ids[p] for p in members], **({'group_id': group_id} if group_id else {}))

    remove = hass.bus.async_listen(SENDDOMAIN, volume_sent)
    producer = asyncio.create_task(ongoing_progress())
    try:
        capture('before')
        start = time.monotonic()
        failure = await call('media_player', 'volume_set', second, volume_level=.07)
        elapsed = time.monotonic() - start
        finished.set()
        await producer
        capture('after-unconfirmed-volume')
        assert failure == 'HomeAssistantError'
        assert 7.8 <= elapsed < 11, elapsed
        assert len(progress) >= 20
        assert writes == [{'uuid': action(first), 'value': 'volume/0'}]
        co.api.send_websocket_command.assert_awaited_once_with(action(first), 'volume/0')
        assert g.entities[ids[first]]._room_volume_percent == 10
        assert g.entities[ids[second]]._room_volume_percent == 38
        assert owner.native.snapshot is original_snapshot
        assert owner.native._generation >= initial_generation
        assert not owner.native._scope and not owner.native._tasks and not owner.native._requests
        assert not owner.native._lock.locked()
        # No fresh grouping frame/reset/cache injection occurs between failure
        # and these actual services. Try every route even on the RED baseline.
        for p in (second, outside[1], free[0]):
            for service in ('media_play', 'media_pause'):
                await call('media_player', service, p)
        for p in (first, second):
            for mode in ('pause', 'play'):
                await call('loxone', 'audio_room_transport', p, action=mode)
        accepting = True
        await call('loxone', 'audio_room_volume', second, volume_percent=21)
        await manage(first, 'add', (free[0],), 'owner-pair')
        await manage(free[0], 'remove', group_id='owner-pair')
        await manage(first, 'destroy', group_id='owner-pair')
        await manage(free[1], 'create', (free[2],))
        await manage(free[2], 'remove', group_id='fresh-created')
        capture('after-followup-journey')
        replay = [m for s in sockets for m in s.sent if m.startswith('audio/') and m != 'audio/cfg/getkey/full']
        report = {'players': players, 'elapsed_seconds': elapsed, 'deadline': owner.native.timeout, 'progress_frames': len(progress), 'first_write_only_before_timeout': writes[:1], 'volume_writes': writes, 'outcomes': outcomes, 'native_requests': replay, 'snapshots': snapshots, 'topology_uncertain': owner.native.uncertain, 'no_physical_cause_claim': True}
        output(f'owner-volume-{first}-{second}.json', report)
        assert [x['result'] for x in outcomes[1:]] == ['success'] * (len(outcomes) - 1), report
        assert groups == {'untouched': outside}
        assert writes == [{'uuid': action(first), 'value': 'volume/0'}, {'uuid': action(second), 'value': 'volume/21'}]
        assert all(s.closed for s in sockets) and co.audio_commands._socket is None
        assert not owner.native._scope and not owner.native._tasks and not owner.native._requests
        assert not owner.native.uncertain
        assert all(not e._transport_tasks for e in g.entities.values())
    finally:
        finished.set()
        producer.cancel()
        await asyncio.gather(producer, return_exceptions=True)
        remove()
