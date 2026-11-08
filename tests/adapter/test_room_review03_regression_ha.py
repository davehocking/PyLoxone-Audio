"""Review03 regressions through registered HA callers and RSA/AES peers.

Invented source targets and identities only. This is not household evidence.
"""
import asyncio
import json
from types import SimpleNamespace

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from custom_components.loxone.pyloxone_api import audioserver as wire
from custom_components.loxone.audio_radio import RadioTarget
from test_audio_grouping_ha import grouped_setup as grouped_setup, audio_setup as audio_setup, row, action
from test_audioserver_playback import SyntheticAudioSocket, rsa_key as rsa_key


def assert_clean(p):
    assert all(s.closed for s in p.sockets)
    assert p.co.audio_commands._socket is None
    assert not p.co.audio_grouping.native._requests
    assert not p.co.audio_grouping.native._tasks
    assert not p.co.audio_grouping.native._scope
    assert p.co.audio_grouping._transport_task is None
    assert all(not e._transport_tasks for e in p.g.entities.values())
    p.co.api.send_websocket_command.assert_not_awaited()


@pytest.mark.parametrize('verb', ['play', 'pause'])
@pytest.mark.parametrize('kind', ['true', 'false', 'number', 'malformed', 'conflicting', 'identical', 'error'])
async def test_registered_room_duplicate_ack_fails_without_state_or_replay(hass, grouped_setup, monkeypatch, rsa_key, verb, kind):
    g = grouped_setup
    entry, co, ids = await g.setup()
    await g.feed(entry, row('native', (2, 1, 3)))
    co.audio_commands._credentials = lambda: ('synthetic-user', 'synthetic-active-token')
    co.audio_commands._timeout = .08
    key = verb + '_result'
    replies = {
        'true': json.dumps({key: True}), 'false': json.dumps({key: False}),
        'number': json.dumps({key: 1}), 'malformed': '{"'+key+'":tru}',
        'conflicting': '{"'+key+'":false,"'+key+'":true}',
        'identical': '{"'+key+'":true,"'+key+'":true}',
        'error': '{"error":"synthetic refusal","error":"","'+key+'":true}',
    }
    sockets = []
    class Socket(SyntheticAudioSocket):
        async def send(self, message):
            if message == f'audio/1/{verb}':
                self.sent.append(message)
                self.queue.put_nowait(replies[kind])
                return
            await super().send(message)
    def connect(*a, **kw):
        socket = Socket(rsa_key)
        sockets.append(socket)
        return socket
    monkeypatch.setattr(wire, 'connect', connect)
    before = {i: hass.states.get(i).state for i in ids.values()}
    call = hass.services.async_call('loxone', 'audio_room_transport', {'action': verb}, target={'entity_id': ids[1]}, blocking=True)
    if kind == 'true':
        await call
    else:
        with pytest.raises(HomeAssistantError):
            await call
    assert [m for s in sockets for m in s.sent if m.startswith('audio/1/')] == [f'audio/1/{verb}']
    assert not co.audio_grouping.native.uncertain
    assert {i: hass.states.get(i).state for i in ids.values()} == before
    assert_clean(SimpleNamespace(co=co, g=g, sockets=sockets))


@pytest.fixture
async def real_source_peer(hass, grouped_setup, audio_setup, monkeypatch, rsa_key):
    g = grouped_setup
    entry, co, ids = await g.setup()
    await g.feed(entry)
    token = ['synthetic-active-token']
    co.api.get_token_dict = lambda: {'token': token[0]}
    co.audio_commands._credentials = lambda: ('synthetic-user', token[0])
    co.audio_commands._timeout = 3
    p = SimpleNamespace(g=g, co=co, entry=entry, ids=ids, token=token, sockets=[],
                        source_sent=asyncio.Event(), drain=asyncio.Event(), release=asyncio.Event(),
                        hold_drain=False, phase=None, hook=None)
    async def emit(player=1, **fields):
        seen = asyncio.Event()
        remove = co.audio_metadata.async_add_listener(player, seen.set)
        try:
            audio_setup.queues[0].put_nowait(json.dumps({'audio_event': [{
                'playerid': player, 'mode': 'stop', 'eventype': 0,
                'audiopath': 'tunein:station:before', **fields,
            }]}))
            await asyncio.wait_for(seen.wait(), 1)
        finally:
            remove()
    p.emit = emit
    await emit(1)
    await emit(2)
    async def hook(phase):
        if p.phase == phase and p.hook is not None:
            await p.hook()
    class Socket(SyntheticAudioSocket):
        async def send(self, message):
            if message.startswith('audio/1/serviceplay/radio/'):
                self.sent.append(message)
                p.source_sent.set()
                await asyncio.Event().wait()
            elif message.startswith('audio/2/serviceplay/radio/'):
                self.sent.append(message)
                self.queue.put_nowait(json.dumps({'command': message}))
            elif message == 'audio/1/pause':
                self.sent.append(message)
                await hook('reply')
                self.queue.put_nowait('{"pause_result":true}')
            else:
                await super().send(message)
                if message.startswith('secure/authenticate/') and asyncio.current_task() is co.audio_grouping._transport_task:
                    await hook('auth')
        async def __aexit__(self, *args):
            try:
                if any(m.startswith('audio/1/serviceplay/') for m in self.sent):
                    p.drain.set()
                    if p.hold_drain:
                        await p.release.wait()
                elif 'audio/1/pause' in self.sent:
                    await hook('cleanup')
            finally:
                await super().__aexit__(*args)
    def connect(*a, **kw):
        s = Socket(rsa_key)
        p.sockets.append(s)
        return s
    monkeypatch.setattr(wire, 'connect', connect)
    def start(player):
        e = g.entities[ids[player]]
        item = e._radio_catalogue._item(RadioTarget('station', 'Synthetic station', 'world', audio_path='tunein:station:after'))
        return asyncio.create_task(hass.services.async_call('media_player', 'play_media', {
            'media_content_type': item.media_content_type, 'media_content_id': item.media_content_id,
        }, target={'entity_id': ids[player]}, blocking=True))
    p.source = start(1)
    await asyncio.wait_for(p.source_sent.wait(), 1)
    p.previous = g.entities[ids[1]]._source_task
    p.fence = co.audio_commands.source_fences[1]
    assert co.audio_commands.source_fence_owners[1] == (p.fence, p.previous)
    assert p.previous is not None and not p.previous.done()
    p.sibling = start(2)
    async with asyncio.timeout(1):
        while 2 not in co.audio_commands.source_fences:
            await asyncio.sleep(0)
    p.sibling_owner = g.entities[ids[2]]._source_task
    p.sessions = {i: dict(g.entities[ids[i]]._radio_catalogue.source_sessions) for i in (1, 2)}
    p.pause = lambda: hass.services.async_call('loxone', 'audio_room_transport', {'action': 'pause'}, target={'entity_id': ids[1]}, blocking=True)
    p.sent = lambda: [m for s in p.sockets for m in s.sent if m.startswith('audio/1/')]
    p.call = None
    try:
        yield p
    finally:
        p.release.set()
        for t in (p.source, p.sibling, p.call):
            if t is not None:
                t.cancel()
        await asyncio.gather(*(t for t in (p.source, p.sibling, p.call) if t is not None), return_exceptions=True)
        for release in tuple(co.audio_commands.source_fences.values()):
            release()
        co.audio_commands.announcement_fences.clear()
        assert not co.audio_commands.source_fences
        assert not co.audio_commands.source_fence_owners
        assert not co.audio_commands.source_observations
        assert_clean(p)


async def perturb(p, boundary, monkeypatch):
    e = p.g.entities[p.ids[1]]
    owner = p.co.audio_grouping
    if boundary == 'token':
        for value in ('synthetic-replacement-token', 'synthetic-active-token'):
            p.token[0] = value
            p.co._on_token_changed({'token': value})
    elif boundary == 'availability':
        for value in (False, True):
            p.co.connection_available = value
            owner.notify()
    elif boundary == 'registry':
        registry = er.async_get(p.co.hass)
        for value in (er.RegistryEntryDisabler.USER, None):
            registry.async_update_entity(p.ids[1], disabled_by=value)
            owner.notify()
    elif boundary == 'generation':
        e._source_generation += 1
        owner.notify()
    elif boundary == 'announcement-fence':
        p.co.audio_commands.announcement_fences[1] = lambda: None
        owner.notify()
        p.co.audio_commands.announcement_fences.pop(1)
        owner.notify()
    elif boundary == 'source-fence':
        original = p.co.audio_commands.source_fences.get(1)
        p.co.audio_commands.source_fences[1] = lambda: None
        owner.notify()
        if original is None:
            p.co.audio_commands.source_fences.pop(1)
        else:
            p.co.audio_commands.source_fences[1] = original
        owner.notify()
    elif boundary == 'capability':
        with monkeypatch.context() as m:
            m.setattr(e, '_room_transport_supported', lambda verb: False)
            owner.notify()
        owner.notify()
    elif boundary == 'event':
        await p.emit(1, mode='play', eventype=3)
        await p.emit(1)
    elif boundary == 'topology':
        original = p.co.api.structure_file['controls'][action(1)]['details']['server']
        for value in (action(99), original):
            p.co.api.structure_file['controls'][action(1)]['details']['server'] = value
            owner.native.observe_current()
    elif boundary == 'removed':
        for value in (True, False):
            e._audio_removed = value
            owner.notify()


@pytest.mark.parametrize('phase', ['before-cancel', 'drain', 'auth', 'reply', 'cleanup'])
@pytest.mark.parametrize('boundary', ['stable', 'token', 'availability', 'registry', 'generation', 'announcement-fence', 'source-fence', 'capability', 'event', 'topology', 'removed'])
async def test_real_source_pause_observes_revocation_before_cancel_through_cleanup(hass, real_source_peer, monkeypatch, phase, boundary):
    p = real_source_peer
    e = p.g.entities[p.ids[1]]
    if phase == 'before-cancel':
        begin = e._async_begin_source_action
        async def observed_begin():
            await perturb(p, boundary, monkeypatch)
            return await begin()
        monkeypatch.setattr(e, '_async_begin_source_action', observed_begin)
    elif phase == 'drain':
        p.hold_drain = True
    else:
        p.phase = phase
        p.hook = lambda: perturb(p, boundary, monkeypatch)
    p.call = asyncio.create_task(p.pause())
    if phase == 'drain':
        await asyncio.wait_for(p.drain.wait(), 1)
        assert not p.call.done() and len(p.sent()) == 1
        await perturb(p, boundary, monkeypatch)
        p.release.set()
    result = (await asyncio.wait_for(asyncio.gather(p.call, return_exceptions=True), 3))[0]
    assert (result is None) == (boundary == 'stable'), (phase, boundary, result)
    if boundary != 'stable':
        assert isinstance(result, (HomeAssistantError, asyncio.CancelledError))
    sent_pause = boundary == 'stable' or phase in ('reply', 'cleanup')
    assert [m for m in p.sent() if m.endswith('/pause')] == (['audio/1/pause'] if sent_pause else [])
    assert not p.co.audio_grouping.native.uncertain
    assert p.source.done() and p.source.cancelled()
    assert not p.sibling.done() and p.g.entities[p.ids[2]]._source_task is p.sibling_owner
    assert all(p.g.entities[p.ids[i]]._radio_catalogue.source_sessions == p.sessions[i] for i in (1, 2))
    assert e._source_task is None
    if 1 in p.co.audio_commands.source_fences:
        # A revoked/cancelled takeover cannot release an unresolved write on
        # behalf of a newer intent. Exact retained fence closes in fixture cleanup.
        assert not sent_pause and isinstance(result, asyncio.CancelledError)
        assert p.co.audio_commands.source_fences[1] is p.fence
        assert p.co.audio_commands.source_fence_owners[1] == (p.fence, p.previous)
    else:
        assert 1 not in p.co.audio_commands.source_fence_owners


@pytest.mark.parametrize('kind', ['orphan', 'foreign', 'announcement'])
async def test_real_own_source_takeover_refuses_non_owned_or_announcement_fence(real_source_peer, kind):
    p = real_source_peer
    commands = p.co.audio_commands
    original = commands.source_fence_owners[1]
    if kind == 'orphan':
        commands.source_fence_owners.pop(1)
    elif kind == 'foreign':
        commands.source_fence_owners[1] = (p.fence, p.sibling_owner)
    else:
        commands.announcement_fences[1] = lambda: None
    try:
        with pytest.raises(HomeAssistantError):
            await p.pause()
        assert not p.source.done() and not p.previous.cancelling()
        assert p.sent() and len(p.sent()) == 1
        assert commands.source_fences[1] is p.fence
        assert not p.sibling.done()
    finally:
        commands.source_fence_owners[1] = original
        commands.announcement_fences.clear()
