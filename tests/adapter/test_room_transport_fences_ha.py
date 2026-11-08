"""Room scope/lifecycle guards on actual HA, with invented authenticated I/O."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from custom_components.loxone.pyloxone_api import audioserver as wire
from test_audio_grouping_ha import action, row, payload
from test_audio_grouping_ha import grouped_setup as grouped_setup
from test_audio_grouping_ha import audio_setup as audio_setup
from test_audioserver_playback import SyntheticAudioSocket
from test_audioserver_playback import rsa_key as rsa_key


@pytest.fixture
async def room_peer(hass, grouped_setup, audio_setup, monkeypatch, rsa_key):
    g = grouped_setup
    entry, co, ids = await g.setup()
    await g.feed(entry, row('native', (2, 1, 3)), row('other', (5, 6)))
    token = ['synthetic-active-token']
    co.api.get_token_dict = lambda: {'token': token[0]}
    co.audio_commands._credentials = lambda: ('synthetic-user', token[0])
    peer = SimpleNamespace(g=g, entry=entry, co=co, ids=ids, sockets=[], token=token,
                           phase=None, hook=None, reply=True, auth='authentication successful')

    async def emit(player=1, **fields):
        delivered = asyncio.get_running_loop().create_future()
        remove = co.audio_metadata.async_add_listener(player, lambda: delivered.done() or delivered.set_result(None))
        try:
            audio_setup.queues[0].put_nowait(json.dumps({'audio_event': [{
                'playerid': player, 'mode': 'pause', 'eventype': 0,
                'audiopath': f'library:local:track:synthetic-{player}', 'sourceName': 'Local Library',
                'parent': {'id': 'library:local:album:synthetic'}, **fields,
            }]}))
            await asyncio.wait_for(delivered, 1)
        finally:
            remove()

    async def hook(phase):
        if peer.phase == phase and peer.hook is not None:
            await peer.hook()

    class Socket(SyntheticAudioSocket):
        def __init__(self):
            super().__init__(rsa_key)
            self.auth_result = peer.auth

        async def send(self, message):
            if message.startswith('audio/') and message != 'audio/cfg/getkey/full':
                self.sent.append(message)
                parts = message.split('/')
                assert len(parts) == 3 and parts[1].isdecimal() and parts[2] in ('play', 'pause'), message
                target = int(parts[1])
                assert co.audio_grouping.native._scope == frozenset({target})
                assert asyncio.current_task() in g.entities[ids[target]]._transport_tasks
                assert all(not g.entities[ids[p]]._transport_tasks for p in ids if p != target)
                await hook('reply')
                if peer.reply == 'disconnect':
                    self.queue.put_nowait(None)
                elif peer.reply != 'silent':
                    self.queue.put_nowait(json.dumps({parts[2]+'_result': peer.reply}))
                return
            await super().send(message)
            if message.startswith('secure/authenticate/'):
                await hook('auth')

        async def __aexit__(self, *args):
            try:
                await hook('cleanup')
            finally:
                await super().__aexit__(*args)

    def connect(*args, **kwargs):
        socket = Socket()
        peer.sockets.append(socket)
        return socket

    monkeypatch.setattr(wire, 'connect', connect)
    peer.emit = emit
    peer.sent = lambda: [m for s in peer.sockets for m in s.sent if m.startswith('audio/') and m != 'audio/cfg/getkey/full']
    peer.call = lambda: hass.services.async_call('loxone', 'audio_room_transport', {'action': 'play'}, target={'entity_id': ids[1]}, blocking=True)
    commands = co.audio_commands
    try:
        yield peer
    finally:
        for e in g.entities.values():
            e._source_task = e._announcement_task = None
        commands.source_fences.clear()
        commands.announcement_fences.clear()


def clean(peer, listeners, bus):
    co = peer.co
    assert all(s.closed for s in peer.sockets)
    assert co.audio_commands._socket is None
    assert not co.audio_grouping.native._scope
    assert not co.audio_grouping.native._tasks
    assert not co.audio_grouping.native._requests
    assert co.audio_grouping._transport_task is None
    assert all(not e._transport_tasks for e in peer.g.entities.values())
    # Registry removal may remove original listeners, never retain new ones.
    assert all(set(co.audio_metadata._listeners.get(p, ())) <= listeners[p] for p in peer.ids)
    assert {id(job) for job, _ in co.hass.bus._listeners.get(er.EVENT_ENTITY_REGISTRY_UPDATED, ())} <= bus
    co.api.send_websocket_command.assert_not_awaited()


BOUNDARIES = ['token', 'availability', 'registry', 'generation', 'topology', 'group',
              'source', 'announcement', 'source-fence', 'announcement-fence', 'spotify',
              'source-identity', 'account-identity', 'event', 'capability', 'capability-notify', 'removed']


async def perturb(peer, boundary, monkeypatch):
    co, g, ids = peer.co, peer.g, peer.ids
    e = g.entities[ids[1]]
    if boundary == 'token':
        for value in ('synthetic-replacement-token', 'synthetic-active-token'):
            peer.token[0] = value
            co._on_token_changed({'token': value})
    elif boundary == 'availability':
        for value in (False, True):
            co.connection_available = value
            co.audio_grouping.notify()
    elif boundary == 'registry':
        registry = er.async_get(co.hass)
        for value in (er.RegistryEntryDisabler.USER, None):
            registry.async_update_entity(ids[1], disabled_by=value)
            co.audio_grouping.notify()
    elif boundary == 'generation':
        e._source_generation += 1
    elif boundary == 'topology':
        original = co.api.structure_file['controls'][action(1)]['details']['server']
        for value in (action(99), original):
            co.api.structure_file['controls'][action(1)]['details']['server'] = value
            co.audio_grouping.native.observe_current()
    elif boundary == 'group':
        for members in ((2, 1, 4), (2, 1, 3)):
            co.audio_grouping.native.observe(payload(row('native', members), row('other', (5, 6))))
    elif boundary in ('source', 'announcement'):
        attr = '_source_task' if boundary == 'source' else '_announcement_task'
        for value in (asyncio.current_task(), None):
            setattr(e, attr, value)
            co.audio_grouping.notify()
    elif boundary in ('source-fence', 'announcement-fence'):
        fences = co.audio_commands.source_fences if boundary == 'source-fence' else co.audio_commands.announcement_fences
        fences[1] = lambda: None
        co.audio_grouping.notify()
        fences.pop(1)
        co.audio_grouping.notify()
    elif boundary == 'spotify':
        with monkeypatch.context() as m:
            m.setattr('custom_components.loxone.media_player.spotify_room_uncertain', lambda *args: True)
            await peer.emit(1)
    elif boundary in ('source-identity', 'account-identity', 'event'):
        fields = {'audiopath': 'tunein:station:synthetic-other'} if boundary == 'source-identity' else {'sourceName': 'Synthetic changed account'} if boundary == 'account-identity' else {'mode': 'play', 'eventype': 3}
        await peer.emit(1, **fields)
        await peer.emit(1)
    elif boundary == 'capability':
        with monkeypatch.context() as m:
            m.setattr(e, '_room_transport_supported', lambda action: False)
            await peer.emit(1)
    elif boundary == 'capability-notify':
        with monkeypatch.context() as m:
            m.setattr(e, '_room_transport_supported', lambda action: False)
            co.audio_grouping.notify()
        co.audio_grouping.notify()
    elif boundary == 'removed':
        for value in (True, False):
            e._audio_removed = value
            co.audio_grouping.notify()


@pytest.mark.parametrize('phase', ['auth', 'reply', 'cleanup'])
@pytest.mark.parametrize('boundary', BOUNDARIES)
async def test_room_revocation_is_sticky_through_authenticated_socket_cleanup(hass, room_peer, monkeypatch, phase, boundary):
    p = room_peer
    await p.emit(1)
    listeners = {i: set(p.co.audio_metadata._listeners[i]) for i in p.ids}
    bus = {id(job) for job, _ in hass.bus._listeners.get(er.EVENT_ENTITY_REGISTRY_UPDATED, ())}
    p.phase = phase
    p.hook = lambda: perturb(p, boundary, monkeypatch)
    with pytest.raises((HomeAssistantError, asyncio.CancelledError)):
        await p.call()
    assert p.sent() == ([] if phase == 'auth' else ['audio/1/play'])
    assert not p.co.audio_grouping.native.uncertain
    clean(p, listeners, bus)


@pytest.mark.parametrize('lock', ['owner', 'commands'])
@pytest.mark.parametrize('boundary', ['stable', 'token', 'availability', 'source-identity', 'account-identity', 'event', 'capability', 'capability-notify', 'registry', 'generation', 'source', 'announcement-fence', 'cancel'])
async def test_room_queued_request_never_revives_after_observed_reversion(hass, room_peer, monkeypatch, lock, boundary):
    p = room_peer
    await p.emit(1)
    listeners = {i: set(p.co.audio_metadata._listeners[i]) for i in p.ids}
    bus = {id(job) for job, _ in hass.bus._listeners.get(er.EVENT_ENTITY_REGISTRY_UPDATED, ())}
    mutex = p.co.audio_grouping.native._lock if lock == 'owner' else p.co.audio_commands._lock
    task = None
    try:
        async with mutex:
            task = asyncio.create_task(p.call())
            async with asyncio.timeout(2):
                while not p.co.audio_grouping.native._requests:
                    await asyncio.sleep(0)
            if boundary == 'cancel':
                task.cancel()
            elif boundary != 'stable':
                await perturb(p, boundary, monkeypatch)
        result = (await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 2))[0]
        assert (result is None) == (boundary == 'stable')
        if boundary != 'stable':
            assert isinstance(result, (HomeAssistantError, asyncio.CancelledError))
        assert p.sent() == (['audio/1/play'] if boundary == 'stable' else [])
        assert not p.co.audio_grouping.native.uncertain
        clean(p, listeners, bus)
    finally:
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize('reply', [False, 1, 'true', {}, 'silent', 'disconnect'])
async def test_room_negative_ambiguous_reply_is_uncertain_without_retry(hass, room_peer, reply):
    p = room_peer
    p.reply = reply
    p.co.audio_commands._timeout = .04
    with pytest.raises(HomeAssistantError):
        await p.call()
    with pytest.raises(HomeAssistantError):
        await p.call()
    assert p.sent() == ['audio/1/play', 'audio/1/play']
    assert not p.co.audio_grouping.native.uncertain
    assert all(s.closed for s in p.sockets)


@pytest.mark.parametrize('boundary', ['cancel', 'unload', 'disconnect'])
async def test_room_inflight_owns_cleanup_on_cancel_unload_disconnect(hass, room_peer, boundary):
    p = room_peer
    p.reply = 'silent'
    commands, owner = p.co.audio_commands, p.co.audio_grouping
    task = asyncio.create_task(p.call())
    try:
        async with asyncio.timeout(2):
            while not p.sent():
                await asyncio.sleep(0)
        if boundary == 'unload':
            assert await hass.config_entries.async_unload(p.entry.entry_id)
        elif boundary == 'disconnect':
            owner.connection_state('disconnected')
        else:
            task.cancel()
        result = (await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 2))[0]
        assert isinstance(result, (HomeAssistantError, asyncio.CancelledError))
        assert commands._socket is None
        assert not owner.native._requests and not owner.native._tasks and not owner.native._scope
        assert all(s.closed for s in p.sockets)
        assert p.sent() == ['audio/1/play']
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize('sibling', [2, 4])
async def test_room_reserves_no_sibling_or_unrelated_source_owner(hass, room_peer, sibling):
    p = room_peer
    entity = p.g.entities[p.ids[sibling]]
    sentinel = asyncio.create_task(asyncio.Event().wait())
    entity._source_task = sentinel
    before = entity._source_generation
    try:
        await p.call()
        assert p.sent() == ['audio/1/play']
        assert entity._source_task is sentinel and not sentinel.done()
        assert entity._source_generation == before
    finally:
        entity._source_task = None
        sentinel.cancel()
        await asyncio.gather(sentinel, return_exceptions=True)
