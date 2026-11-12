"""Grouped mode ownership through actual HA services and authenticated native I/O."""
import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from homeassistant.components.media_player import MediaPlayerEntityFeature as F
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from test_audio_grouping_ha import grouped_setup, row, payload, STATE, structure
from test_audioserver_ha import audio_setup
from test_audioserver_playback import SyntheticAudioSocket, rsa_key
from custom_components.loxone.pyloxone_api import audioserver as wire

GREETING = 'LWSS V 17.2.02.01 | ~API:1.6~ | Session-Token: synthetic-audio-session'
FULL = 2048 | 4096 | 8192 | 32


async def harness(hass, grouped_setup, audio_setup, monkeypatch, rsa_key, *, count=12):
    g = grouped_setup
    g.source.clear()
    g.source.update(structure(count))
    entry, co, _ = await g.setup()
    entities = {e._audio_player_id: e for e in g.entities.values()}
    commands, metadata = co.audio_commands, co.audio_metadata
    co.api.get_token_dict = lambda: {'token': 'synthetic-active-token'}
    commands._credentials = lambda: ('synthetic-user', co.api.get_token_dict()['token'])
    commands._timeout = .5
    rows, writes, sockets = {}, [], []
    state = SimpleNamespace(auth_hook=None, cleanup_hook=None, feedback=True, auth_seen=0)

    async def emit(pid, **updates):
        rows[pid] = {**rows[pid], **updates}
        done = asyncio.get_running_loop().create_future()
        remove = metadata.async_add_listener(pid, lambda: done.done() or done.set_result(None))
        try:
            audio_setup.queues[0].put_nowait(json.dumps({'audio_event': [rows[pid]]}))
            await asyncio.wait_for(done, 2)
        finally:
            remove()

    class Socket(SyntheticAudioSocket):
        def __init__(self):
            super().__init__(rsa_key)
            self.queue.get_nowait()
            self.queue.put_nowait(GREETING)

        async def send(self, message):
            if message.startswith('audio/') and not message.startswith('audio/cfg/'):
                self.sent.append(message)
                writes.append(message)
                _, pid, operation, value = message.split('/')
                assert operation in ('shuffle', 'repeat'), 'Modes must not dispatch playback, group, volume, source or seek'
                value = value == 'enable' if operation == 'shuffle' else int(value)
                if state.feedback:
                    await emit(int(pid), **{'plshuffle' if operation == 'shuffle' else 'plrepeat': value})
                self.queue.put_nowait(json.dumps({operation + '_result': {operation: value}}))
                return
            await super().send(message)
            if message.startswith('secure/authenticate/'):
                state.auth_seen += 1
                if state.auth_hook:
                    await state.auth_hook()

        async def __aexit__(self, *args):
            result = await super().__aexit__(*args)
            if state.cleanup_hook:
                await state.cleanup_hook()
            return result

    def connect(*_a, **_kw):
        socket = Socket()
        sockets.append(socket)
        return socket

    monkeypatch.setattr(wire, 'connect', connect)
    audio_setup.queues[0].put_nowait(GREETING)
    for pid in entities:
        rows[pid] = {'playerid': pid, 'eventype': 0, 'mode': 'play', 'pbr': FULL,
                     'audiopath': f'library:local:track:synthetic-{pid}', 'sourceName': 'Synthetic library',
                     'parent': {'id': 'library:local:album:synthetic'}, 'title': f'Synthetic item {pid}',
                     'time': 20 + pid, 'duration': 300, 'plshuffle': False, 'plrepeat': 0}
        await emit(pid)
    await g.feed(entry)
    await g.callbacks[entry.entry_id]['callback']({f'play-{pid}': 2 for pid in entities})
    await hass.async_block_till_done()
    return SimpleNamespace(g=g, entry=entry, co=co, entities=entities, rows=rows, emit=emit,
                           writes=writes, sockets=sockets, state=state, metadata=metadata)


async def request(hass, entity, operation, value):
    await hass.services.async_call('media_player', operation + '_set',
                                  {'entity_id': entity.entity_id, operation: value}, blocking=True)


def modes(hass, entity):
    state = hass.states.get(entity.entity_id)
    return state.attributes.get('shuffle'), state.attributes.get('repeat'), state.attributes['supported_features']


@pytest.mark.parametrize('role', ['solo', 'leader', 'follower'])
@pytest.mark.parametrize('operation,value,route', [('shuffle', True, 'shuffle/enable'), ('repeat', 'one', 'repeat/3')])
async def test_modes_route_once_to_current_confirmed_leader_and_publish_followers(hass, grouped_setup, audio_setup, monkeypatch, rsa_key, role, operation, value, route):
    h = await harness(hass, grouped_setup, audio_setup, monkeypatch, rsa_key)
    if role != 'solo':
        await h.g.feed(h.entry, row('shared', (2, 1)), row('other', (3, 4)))
    caller = h.entities[1 if role != 'leader' else 2]
    target = 1 if role == 'solo' else 2
    before = {p: copy.copy(e._radio_catalogue.source_sessions) for p, e in h.entities.items()}
    assert caller.supported_features & F.SHUFFLE_SET
    assert caller.supported_features & F.REPEAT_SET
    await request(hass, caller, operation, value)
    await hass.async_block_till_done()
    assert h.writes == [f'audio/{target}/{route}']
    for pid in ([1] if role == 'solo' else [1, 2]):
        attrs = hass.states.get(h.entities[pid].entity_id).attributes
        assert attrs[operation] == value
        assert attrs['supported_features'] & (F.SHUFFLE_SET | F.REPEAT_SET) == (F.SHUFFLE_SET | F.REPEAT_SET)
    assert all(s.closed for s in h.sockets)
    assert h.co.audio_commands._socket is None
    assert not h.co.audio_grouping.native._requests
    assert not any(e._source_task or e._transport_tasks for e in h.entities.values())
    assert all(e._radio_catalogue.source_sessions == before[p] for p, e in h.entities.items())
    assert all('/' + forbidden + '/' not in route for forbidden in ['volume', 'position', 'serviceplay', 'dgroup'])
    if role != 'solo':
        assert tuple(h.co.audio_grouping.native.snapshot.groups[0].players) == (2, 1)
        assert not h.entities[1].supported_features & (F.BROWSE_MEDIA | F.SELECT_SOURCE | F.SEEK | F.MEDIA_ANNOUNCE)
        assert not h.entities[2].supported_features & F.MEDIA_ANNOUNCE


@pytest.mark.parametrize('leader', range(1, 13))
async def test_every_room_uses_leader_modes_and_current_leader_capabilities(hass, grouped_setup, audio_setup, monkeypatch, rsa_key, leader):
    h = await harness(hass, grouped_setup, audio_setup, monkeypatch, rsa_key)
    follower = leader % 12 + 1
    await h.g.feed(h.entry, row('shared', (leader, follower)))
    await h.emit(follower, pbr=0, plshuffle=False, plrepeat=0)
    await h.emit(leader, plshuffle=True, plrepeat=3)
    await hass.async_block_till_done()
    for pid in (leader, follower):
        shuffle, repeat, features = modes(hass, h.entities[pid])
        assert shuffle is True and repeat == 'one'
        assert features & F.SHUFFLE_SET and features & F.REPEAT_SET
    await h.emit(leader, pbr=0, plshuffle=None, plrepeat=None)
    await hass.async_block_till_done()
    assert modes(hass, h.entities[follower])[:2] == (None, None)
    assert not modes(hass, h.entities[follower])[2] & (F.SHUFFLE_SET | F.REPEAT_SET)
    assert h.writes == []


async def test_external_feedback_and_releader_republish_without_optimistic_write(hass, grouped_setup, audio_setup, monkeypatch, rsa_key):
    h = await harness(hass, grouped_setup, audio_setup, monkeypatch, rsa_key)
    await h.g.feed(h.entry, row('shared', (2, 1)))
    await h.emit(2, plshuffle=True, plrepeat=3)
    await h.emit(3, plshuffle=False, plrepeat=1)
    await hass.async_block_till_done()
    assert modes(hass, h.entities[1])[:2] == (True, 'one')
    await h.g.feed(h.entry, row('shared', (3, 1)))
    assert modes(hass, h.entities[1])[:2] == (False, 'all')
    h.state.feedback = False
    await request(hass, h.entities[1], 'shuffle', True)
    await hass.async_block_till_done()
    assert h.writes == ['audio/3/shuffle/enable']
    assert modes(hass, h.entities[1])[:2] == (False, 'all')
    await h.emit(3, plshuffle=True)
    await hass.async_block_till_done()
    assert modes(hass, h.entities[1])[:2] == (True, 'all')


@pytest.mark.parametrize('change', ['leader', 'leader-ABA', 'membership', 'invalid', 'auth', 'auth-ABA', 'leader-disabled', 'caller-removed', 'busy', 'metadata', 'metadata-ABA'])
@pytest.mark.parametrize('phase', ['auth', 'cleanup'])
async def test_group_modes_latch_stale_auth_membership_lifecycle_and_metadata_no_replay(hass, grouped_setup, audio_setup, monkeypatch, rsa_key, change, phase):
    h = await harness(hass, grouped_setup, audio_setup, monkeypatch, rsa_key)
    await h.g.feed(h.entry, row('shared', (2, 1)))
    observed = []
    async def alter():
        observed.append(change)
        owner = h.co.audio_grouping
        if change.startswith('leader') and change != 'leader-disabled':
            owner.observe({STATE: payload(row('shared', (3, 1)))})
            if change.endswith('ABA'):
                owner.observe({STATE: payload(row('shared', (2, 1)))})
        elif change == 'membership':owner.observe({STATE: payload(row('shared', (2, 1, 3)))})
        elif change == 'invalid':owner.observe({STATE: 'invalid-grouping'})
        elif change.startswith('auth'):
            previous = h.co.api.get_token_dict
            h.co.api.get_token_dict = lambda: {'token': 'synthetic-new-token'}
            owner.notify()
            if change.endswith('ABA'):
                h.co.api.get_token_dict = previous
                owner.notify()
        elif change == 'leader-disabled':
            er.async_get(hass).async_update_entity(h.entities[2].entity_id, disabled_by=er.RegistryEntryDisabler.USER)
            owner.notify()
        elif change == 'caller-removed':
            h.entities[1]._audio_removed = True
            owner.notify()
        elif change == 'busy':
            owner.native._scope = frozenset({1, 2})
            owner.notify()
        else:
            old = h.rows[2]['audiopath']
            await h.emit(2, audiopath='library:local:track:different')
            if change.endswith('ABA'):await h.emit(2, audiopath=old)
    setattr(h.state, 'auth_hook' if phase == 'auth' else 'cleanup_hook', alter)
    with pytest.raises((HomeAssistantError, asyncio.CancelledError)):
        await request(hass, h.entities[1], 'repeat', 'one')
    assert observed == [change], 'The real owning operation must reach the selected native boundary'
    assert h.writes == ([] if phase == 'auth' else ['audio/2/repeat/3'])
    assert all(s.closed for s in h.sockets)
    assert h.co.audio_commands._socket is None
    assert not h.co.audio_grouping.native._requests


@pytest.mark.parametrize('refusal', ['unknown', 'static', 'uncertain', 'busy', 'missing-leader', 'leader-unavailable', 'leader-disabled', 'capability', 'leader-fence', 'caller-fence'])
async def test_unqualified_mode_groups_reject_advertisement_and_direct_owning_call(hass, grouped_setup, audio_setup, monkeypatch, rsa_key, refusal):
    h = await harness(hass, grouped_setup, audio_setup, monkeypatch, rsa_key)
    await h.g.feed(h.entry, row('shared', (2, 1), kind='static' if refusal == 'static' else 'dynamic'))
    owner = h.co.audio_grouping
    if refusal == 'unknown':owner.observe({STATE: 'unknown'})
    elif refusal == 'uncertain':owner.native.uncertain = True
    elif refusal == 'busy':owner.native._scope = frozenset({1, 2})
    elif refusal == 'missing-leader':owner.entities.pop(2)
    elif refusal == 'leader-unavailable':h.entities[2]._attr_available = False
    elif refusal == 'leader-disabled':er.async_get(hass).async_update_entity(h.entities[2].entity_id, disabled_by=er.RegistryEntryDisabler.USER)
    elif refusal == 'capability':await h.emit(2, pbr=0)
    elif refusal == 'leader-fence':h.co.audio_commands.source_fences[2] = lambda: None
    elif refusal == 'caller-fence':h.co.audio_commands.announcement_fences[1] = lambda: None
    for pid in (1, 2):
        entity = h.entities[pid]
        assert not entity.supported_features & (F.SHUFFLE_SET | F.REPEAT_SET)
        with pytest.raises(HomeAssistantError):await entity.async_set_shuffle(True)
        with pytest.raises(HomeAssistantError):await entity.async_set_repeat('one')
    assert h.writes == [] and h.sockets == []


async def test_export_actual_ha_native_mode_states(hass, grouped_setup, audio_setup, monkeypatch, rsa_key):
    h = await harness(hass, grouped_setup, audio_setup, monkeypatch, rsa_key)
    snapshots = []
    async def capture(label):
        await hass.async_block_till_done()
        snapshots.append({'scenario': label, 'target': h.entities[1].entity_id,
                          'states': {e.entity_id: hass.states.get(e.entity_id).as_dict() for e in h.entities.values()}})
    await capture('independent')
    await h.g.feed(h.entry, row('shared', (2, 1)))
    await h.emit(2, plshuffle=True, plrepeat=3)
    await capture('initial')
    await h.g.feed(h.entry, row('shared', (3, 1)))
    await h.emit(3, plshuffle=False, plrepeat=1)
    await capture('changed-leader')
    await h.emit(3, pbr=0, plshuffle=None, plrepeat=None)
    await capture('unsupported')
    assert not h.writes and not h.sockets
    import os
    if output := os.environ.get('GM03_BROWSER_STATES'):
        Path(output).write_text(json.dumps({'snapshots': snapshots,
            'display_registry': {'entities': [{'ei': e.entity_id, 'pl': 'loxone', 'lb': []} for e in h.entities.values()], 'entity_categories': {}},
            'device_registry': [], 'provenance': 'Actual owning-HA published state; synthetic structure, native I/O and credentials only'}, default=str, indent=2) + '\n')
