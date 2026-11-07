"""Owning HA transport journey with invented rooms and authenticated synthetic peer."""
import asyncio
import json
import pytest
from homeassistant.exceptions import HomeAssistantError
from custom_components.loxone.pyloxone_api import audioserver as wire
from test_audio_grouping_ha import STATE, payload, row, action
from test_audio_grouping_ha import grouped_setup as grouped_setup
from test_audio_grouping_ha import audio_setup as audio_setup
from test_audioserver_playback import SyntheticAudioSocket
from test_audioserver_playback import rsa_key as rsa_key


@pytest.mark.parametrize('service,mode', [('media_play','play'), ('media_pause','pause')])
async def test_owning_group_transport_uses_current_all_members_not_opaque_id_or_leader(
    hass, grouped_setup, monkeypatch, rsa_key, service, mode
):
    g = grouped_setup
    entry, co, ids = await g.setup()
    await g.feed(entry, row('opaque-dynamic', (2,1,3)), row('outside', (5,6)))
    # Owner journey: leader playing; native followers remain paused.
    await g.callbacks[entry.entry_id]['callback']({'play-2': 2, 'play-1': 1, 'play-3': 1})
    await hass.async_block_till_done()
    before = {p: hass.states.get(ids[p]).state for p in ids}
    co.audio_commands._credentials = lambda: ('synthetic-user','synthetic-active-token')
    sockets = []
    class Socket(SyntheticAudioSocket):
        async def send(self, message):
            if message.startswith('audio/grouped/'):
                self.sent.append(message)
                self.queue.put_nowait(json.dumps({f'grouped_{mode}_result': {'players': [
                    {'playerid': p, 'mode': mode} for p in (3,2,1)
                ]}}))
                return
            if message in ('audio/1/play', 'audio/1/pause'):
                self.sent.append(message)
                self.queue.put_nowait(json.dumps({mode+'_result': True}))
                return
            await super().send(message)
    def connect(*args, **kwargs):
        socket = Socket(rsa_key); sockets.append(socket); return socket
    monkeypatch.setattr(wire, 'connect', connect)
    await hass.services.async_call('media_player', service, {'entity_id': ids[1]}, blocking=True)
    sent = [m for s in sockets for m in s.sent if m.startswith('audio/') and m != 'audio/cfg/getkey/full']
    assert sent == [f'audio/grouped/{mode}/2,1,3']
    assert all(s.closed for s in sockets)
    assert co.audio_commands._socket is None
    assert co.audio_grouping.native._scope == frozenset()
    assert all(not e._transport_tasks for e in g.entities.values())
    # ACK is not optimistic HA state, volume, source, queue or bookmark feedback.
    assert {p: hass.states.get(ids[p]).state for p in ids} == before
    co.api.send_websocket_command.assert_not_awaited()
    await g.callbacks[entry.entry_id]['callback']({f'play-{p}':2 if mode == 'play' else 1 for p in (1,2,3)})
    await hass.async_block_till_done()
    assert all(hass.states.get(ids[p]).state == ('playing' if mode == 'play' else 'paused') for p in (1,2,3))
    assert all(hass.states.get(ids[p]).state == before[p] for p in (4,5,6))


@pytest.mark.parametrize('when', ['auth', 'reply', 'cleanup'])
@pytest.mark.parametrize('change', ['token', 'registry', 'topology', 'generation', 'group', 'source', 'announcement', 'source-fence', 'announcement-fence', 'spotify-fence', 'unavailable'])
async def test_all_participants_are_fenced_through_auth_reply_and_socket_cleanup(
    hass, grouped_setup, monkeypatch, rsa_key, when, change
):
    from homeassistant.helpers import entity_registry as er
    g = grouped_setup
    entry, co, ids = await g.setup()
    await g.feed(entry, row('native', (1,2)))
    co.audio_commands._credentials = lambda: ('synthetic-user','synthetic-active-token')
    sockets = []
    def perturb():
        e = g.entities[ids[2]]
        if change == 'token': co.audio_commands._credentials = lambda: ('synthetic-user','changed')
        elif change == 'registry': er.async_get(hass).async_remove(ids[2])
        elif change == 'topology': co.api.structure_file['controls'][action(2)]['details']['server'] = action(99)
        elif change == 'generation': e._source_generation += 1
        elif change == 'group': co.audio_grouping.native.observe(payload(row('native', (1,3))))
        elif change == 'source': e._source_task = asyncio.current_task()
        elif change == 'announcement': e._announcement_task = asyncio.current_task()
        elif change == 'source-fence': co.audio_commands.source_fences[2] = lambda: None
        elif change == 'announcement-fence': co.audio_commands.announcement_fences[2] = lambda: None
        elif change == 'spotify-fence': monkeypatch.setattr('custom_components.loxone.media_player.spotify_room_uncertain', lambda hass,room,player: player == 2)
        elif change == 'unavailable': e._audio_removed = True
    class Socket(SyntheticAudioSocket):
        async def send(self, message):
            if message.startswith('audio/grouped/'):
                self.sent.append(message)
                assert co.audio_grouping.native._scope == frozenset({1,2})
                assert all(asyncio.current_task() in g.entities[ids[p]]._transport_tasks for p in (1,2))
                if when == 'reply': perturb()
                self.queue.put_nowait(json.dumps({'grouped_play_result': {'players': [{'playerid':p,'mode':'play'} for p in (1,2)]}}))
                return
            await super().send(message)
            if message.startswith('secure/authenticate/') and when == 'auth': perturb()
        async def __aexit__(self, *args):
            if when == 'cleanup': perturb()
            await super().__aexit__(*args)
    def connect(*a, **k):
        s = Socket(rsa_key); sockets.append(s); return s
    monkeypatch.setattr(wire, 'connect', connect)
    try:
        with pytest.raises((HomeAssistantError, asyncio.CancelledError)):
            await hass.services.async_call('media_player','media_play',{'entity_id':ids[1]},blocking=True)
        sent = [m for s in sockets for m in s.sent if m.startswith('audio/grouped/')]
        assert sent == ([] if when == 'auth' else ['audio/grouped/play/1,2'])
        assert all(s.closed for s in sockets)
        assert co.audio_commands._socket is None
        assert not co.audio_grouping.native._scope
        assert all(not e._transport_tasks for e in g.entities.values())
        assert not co.audio_grouping.native.uncertain
    finally:
        for e in g.entities.values(): e._source_task = e._announcement_task = None
        co.audio_commands.source_fences.clear()
        co.audio_commands.announcement_fences.clear()


@pytest.mark.parametrize('bad', ['missing', 'duplicate', 'foreign', 'mode', 'false', 'timeout', 'disconnect'])
async def test_bad_group_reply_never_falls_back_retries_or_silently_succeeds(hass, grouped_setup, monkeypatch, rsa_key, bad):
    g = grouped_setup
    entry, co, ids = await g.setup()
    await g.feed(entry, row('native', (1,2)))
    co.audio_commands._credentials = lambda: ('synthetic-user','synthetic-active-token')
    co.audio_commands._timeout = .05
    sockets = []
    class Socket(SyntheticAudioSocket):
        async def send(self, message):
            if message.startswith('audio/grouped/'):
                self.sent.append(message)
                players = [1,2] if bad == 'mode' else [1] if bad == 'missing' else [1,1] if bad == 'duplicate' else [1,3]
                result = False if bad == 'false' else {'players':[{'playerid':p,'mode':'pause' if bad == 'mode' else 'play'} for p in players]}
                if bad == 'disconnect': self.queue.put_nowait(None)
                elif bad != 'timeout': self.queue.put_nowait(json.dumps({'grouped_play_result':result}))
                return
            await super().send(message)
    def connect(*a, **k):
        s = Socket(rsa_key); sockets.append(s); return s
    monkeypatch.setattr(wire, 'connect', connect)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call('media_player','media_play',{'entity_id':ids[1]},blocking=True)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call('media_player','media_play',{'entity_id':ids[2]},blocking=True)
    assert [m for s in sockets for m in s.sent if m.startswith('audio/grouped/')] == ['audio/grouped/play/1,2', 'audio/grouped/play/1,2']
    assert all(s.closed for s in sockets)
    assert not co.audio_grouping.native.uncertain
    co.api.send_websocket_command.assert_not_awaited()


async def test_grouped_fresh_source_and_browse_start_are_honestly_refused_not_leader_only(hass, grouped_setup, monkeypatch):
    from unittest.mock import AsyncMock
    g = grouped_setup
    entry, co, ids = await g.setup()
    await g.feed(entry, row('native', (1,2)))
    send = AsyncMock()
    monkeypatch.setattr(co.audio_commands, '_async_request', send)
    for p in (1,2):
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call('media_player','select_source',{'entity_id':ids[p],'source':'Local Library'},blocking=True)
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call('media_player','play_media',{'entity_id':ids[p],'media_content_type':'music','media_content_id':'library:local:track:synthetic'},blocking=True)
    send.assert_not_awaited()
    co.api.send_websocket_command.assert_not_awaited()


async def test_room_volume_is_only_its_own_native_target_and_never_changes_group(hass, grouped_setup):
    g = grouped_setup
    entry, co, ids = await g.setup()
    await g.feed(entry, row('native', (2,1,3)))
    await g.callbacks[entry.entry_id]['callback']({**{f'volume-{p}':p*10 for p in ids}, **{f'play-{p}':0 for p in ids}})
    await hass.async_block_till_done()
    before = {p:hass.states.get(ids[p]).attributes['volume_level'] for p in ids}
    from custom_components.loxone.const import SENDDOMAIN
    sent=asyncio.Event()
    async def on_sent(event):
        sent.set()
    remove=hass.bus.async_listen(SENDDOMAIN,on_sent)
    task=asyncio.create_task(hass.services.async_call('loxone','audio_room_volume',{'entity_id':ids[1],'volume_percent':17},blocking=True))
    try:
        await asyncio.wait_for(sent.wait(),2)
        # A bus send/ACK alone changes neither raw feedback nor public state.
        assert {p:hass.states.get(ids[p]).attributes['volume_level'] for p in ids} == before
        assert not task.done()
        await g.callbacks[entry.entry_id]['callback']({'volume-1':17})
        await task
        await hass.async_block_till_done()
    finally:
        remove()
        if not task.done():task.cancel()
        await asyncio.gather(task,return_exceptions=True)
    co.api.send_websocket_command.assert_awaited_once_with(action(1), 'volume/17')
    assert {p:hass.states.get(ids[p]).attributes['loxone_room_volume_level'] for p in ids} == {p:(17 if p==1 else p*10)/100 for p in ids}
    assert co.audio_grouping.native.snapshot.groups[0].players == (2,1,3)


@pytest.mark.parametrize('boundary', ['cancel', 'unload', 'disconnect'])
async def test_pending_group_transport_closes_exact_socket_and_releases_all_owners(hass, grouped_setup, monkeypatch, rsa_key, boundary):
    g = grouped_setup
    entry, co, ids = await g.setup()
    commands, grouping = co.audio_commands, co.audio_grouping
    await g.feed(entry, row('native', (1,2)))
    co.audio_commands._credentials = lambda: ('synthetic-user','synthetic-active-token')
    ready = asyncio.Event()
    sockets = []
    class Socket(SyntheticAudioSocket):
        async def send(self, message):
            if message.startswith('audio/grouped/'):
                self.sent.append(message)
                ready.set()
                return  # No reply, so cancellation must own cleanup.
            await super().send(message)
    def connect(*a, **k):
        s = Socket(rsa_key); sockets.append(s); return s
    monkeypatch.setattr(wire, 'connect', connect)
    task = asyncio.create_task(hass.services.async_call('media_player','media_play',{'entity_id':ids[1]},blocking=True))
    try:
        await asyncio.wait_for(ready.wait(), 2)
        if boundary == 'unload':
            assert await hass.config_entries.async_unload(entry.entry_id)
        elif boundary == 'disconnect':
            co.audio_grouping.connection_state('disconnected')
        else:
            task.cancel()
        result = (await asyncio.wait_for(asyncio.gather(task,return_exceptions=True),2))[0]
        assert isinstance(result, (asyncio.CancelledError,HomeAssistantError))
        assert all(s.closed for s in sockets)
        assert commands._socket is None
        assert not grouping.native._scope
        assert not grouping.native._tasks
        assert all(not e._transport_tasks for e in g.entities.values())
        assert [m for s in sockets for m in s.sent if m.startswith('audio/grouped/')] == ['audio/grouped/play/1,2']
        co.api.send_websocket_command.assert_not_awaited()
    finally:
        if not task.done(): task.cancel()
        await asyncio.gather(task,return_exceptions=True)
