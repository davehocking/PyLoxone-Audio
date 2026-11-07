"""Group-source regression through real HA entities; all transport is synthetic."""
import pytest
from homeassistant.components.media_player import MediaPlayerEntityFeature as F
from homeassistant.exceptions import HomeAssistantError
from test_audio_grouping_ha import grouped_setup, row  # noqa: F401
from test_audioserver_ha import audio_setup  # noqa: F401

@pytest.mark.asyncio
async def test_confirmed_dynamic_leader_keeps_native_browse_without_enabling_announcements(hass, grouped_setup):
    g = grouped_setup
    entry, co, ids = await g.setup()
    await g.feed(entry, row('shared', (2, 1)))
    leader, follower = g.entities[ids[2]], g.entities[ids[1]]
    assert leader.supported_features & F.BROWSE_MEDIA
    assert leader.supported_features & F.SEARCH_MEDIA
    assert leader.supported_features & F.PLAY_MEDIA
    assert not leader.supported_features & F.MEDIA_ANNOUNCE
    root = await leader.async_browse_media()
    assert root.can_expand and root.children
    assert not follower.supported_features & (F.BROWSE_MEDIA | F.SELECT_SOURCE | F.PLAY_MEDIA)
    with pytest.raises(HomeAssistantError):
        await follower.async_browse_media()
    assert g.calls == []
    assert list(co.audio_grouping.members(2)) == [ids[2], ids[1]]


@pytest.mark.asyncio
async def test_group_leader_native_search_play_and_source_return_keep_membership(hass, grouped_setup, audio_setup, monkeypatch):
    import asyncio
    import json
    from unittest.mock import AsyncMock
    from homeassistant.components.media_player import SearchMediaQuery
    from custom_components.loxone.pyloxone_api import audioserver
    g = grouped_setup
    g_audio = audio_setup
    station = {"type": 2, "name": "Synthetic station", "audiopath": "tunein:station:found"}
    monkeypatch.setattr(audioserver.AudioServerCommands, "async_global_search", AsyncMock(return_value={"tunein": {"station": {"items": [station]}}}))
    calls = []
    async def play(self, player, service, path, *, is_current, on_send):
        assert is_current()
        on_send()
        calls.append((player, service, path))
        asyncio.get_running_loop().call_later(0.01, g_audio.queues[0].put_nowait,
            json.dumps({"audio_event": [{"playerid": player, "mode": "play", "audiopath": path}]}))
    monkeypatch.setattr(audioserver.AudioServerCommands, "async_play_radio_station", play)
    entry, co, ids = await g.setup()
    await g.feed(entry, row('shared', (2, 1)))
    leader, follower = g.entities[ids[2]], g.entities[ids[1]]
    await leader.async_browse_media()  # Native browser discovers the leader's provider inventory first.
    result = await leader.async_search_media(SearchMediaQuery(search_query='synthetic'))
    selection = result.result[0]
    await g_audio.queues[0].put(json.dumps({"audio_event": [{"playerid": 2, "mode": "stop", "audiopath": "spotify:track:before"}]}))
    await hass.async_block_till_done()
    await hass.services.async_call('media_player', 'play_media', {'entity_id': ids[2], 'media_content_type': selection.media_content_type, 'media_content_id': selection.media_content_id}, blocking=True)
    assert calls == [(2, 'world', 'tunein:station:found')]
    assert leader.source_list
    await leader.async_select_source(leader.source_list[0])
    assert len(calls) == 1
    with pytest.raises(HomeAssistantError):
        await follower.async_play_media(selection.media_content_type, selection.media_content_id)
    assert g.calls == []
    assert tuple(co.audio_grouping.native.snapshot.groups[0].players) == (2, 1)


@pytest.mark.asyncio
async def test_export_grouped_source_native_fixture(hass, grouped_setup):
    import json, os
    from pathlib import Path
    from test_audio_grouping_ha import STATE, payload
    g = grouped_setup
    entry, co, ids = await g.setup()
    snapshots = []
    async def capture(label, groups):
        await g.feed(entry, *groups)
        await g.callbacks[entry.entry_id]['callback']({**{f'play-{p}':1 for p in ids}, **{f'volume-{p}':10 for p in ids}})
        await hass.async_block_till_done()
        snapshots.append({'scenario':label,'target':ids[1],'states':{eid:hass.states.get(eid).as_dict() for eid in ids.values()}})
    await capture('initial', [row('shared',(2,1)),row('other',(3,4))])
    await capture('changed-leader', [row('shared',(3,1)),row('other',(2,4))])
    await capture('restored-leader', [row('shared',(2,1)),row('other',(3,4))])
    await capture('became-leader', [row('shared',(1,2)),row('other',(3,4))])
    await capture('independent', [row('other',(3,4))])
    assert g.calls == []
    output=os.environ.get('GM03_BROWSER_STATES')
    if output:
        Path(output).write_text(json.dumps({'snapshots':snapshots,'display_registry':{'entities':[{'ei':eid,'pl':'loxone','lb':[]}for eid in ids.values()],'entity_categories':{}},'device_registry':[],'provenance':'Real HA grouped source adapter; invented structure/state/transports; no household data'},default=str,indent=2))


@pytest.mark.asyncio
async def test_group_leader_learns_own_native_source_history_but_follower_does_not(hass, grouped_setup, audio_setup):
    import json
    g=grouped_setup
    entry,co,ids=await g.setup()
    await g.feed(entry,row('shared',(2,1)))
    leader,follower=g.entities[ids[2]],g.entities[ids[1]]
    await leader.async_browse_media()
    for _ in range(2):
        await audio_setup.queues[0].put(json.dumps({'audio_event':[{'playerid':2,'mode':'play','audiopath':'tunein:station:external','title':'Synthetic external radio'},{'playerid':1,'mode':'play','audiopath':'tunein:station:external','title':'Synthetic external radio'}]}))
        await hass.async_block_till_done()
    assert leader.source_list
    assert not follower.source_list
    assert g.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize('refusal', ['static','uncertain','busy','missing-member','disabled-member'])
async def test_group_source_refuses_unqualified_group_without_widening_announcements(hass, grouped_setup, refusal):
    from homeassistant.helpers import entity_registry as er
    g=grouped_setup
    entry,co,ids=await g.setup()
    await g.feed(entry,row('shared',(2,1),kind='static' if refusal=='static' else 'dynamic'))
    owner=co.audio_grouping
    if refusal=='uncertain':owner.native.uncertain=True
    if refusal=='busy':owner.native._scope=frozenset({1,2})
    if refusal=='missing-member':owner.entities.pop(1)
    if refusal=='disabled-member':er.async_get(hass).async_update_entity(ids[1], disabled_by=er.RegistryEntryDisabler.USER)
    entity=g.entities[ids[2]]
    assert not entity.supported_features & (F.BROWSE_MEDIA|F.SEARCH_MEDIA|F.PLAY_MEDIA|F.MEDIA_ANNOUNCE)
    with pytest.raises(HomeAssistantError):await entity.async_browse_media()
    assert g.calls==[]


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['leader','membership','invalid','authentication'])
async def test_inflight_browse_never_returns_an_obsolete_group_context(hass, grouped_setup, monkeypatch, change):
    import asyncio
    from test_audio_grouping_ha import STATE,payload
    g=grouped_setup
    entry,co,ids=await g.setup()
    await g.feed(entry,row('shared',(2,1)))
    entity=g.entities[ids[2]]
    original=entity._radio_catalogue.async_browse
    entered,release=asyncio.Event(),asyncio.Event()
    async def delayed(*args):
        entered.set()
        await release.wait()
        return await original(*args)
    monkeypatch.setattr(entity._radio_catalogue,'async_browse',delayed)
    task=asyncio.create_task(entity.async_browse_media())
    try:
        await asyncio.wait_for(entered.wait(),2)
        if change=='leader':co.audio_grouping.observe({STATE:payload(row('shared',(1,2)))})
        elif change=='membership':co.audio_grouping.observe({STATE:payload(row('shared',(2,1,3)))})
        elif change=='invalid':co.audio_grouping.observe({STATE:'invalid-synthetic-group-frame'})
        else:
            co.api.get_token_dict=lambda:{'token':'different-synthetic-token'}
            co.audio_grouping.notify()
        release.set()
        with pytest.raises(HomeAssistantError):await asyncio.wait_for(task,3)
    finally:
        release.set()
        if not task.done():task.cancel()
        await asyncio.gather(task,return_exceptions=True)
    assert g.calls==[]


@pytest.mark.asyncio
async def test_source_start_cannot_outlive_a_group_leader_change(hass, grouped_setup, audio_setup, monkeypatch):
    import asyncio,json
    from unittest.mock import AsyncMock
    from homeassistant.components.media_player import SearchMediaQuery
    from custom_components.loxone.pyloxone_api import audioserver
    from test_audio_grouping_ha import STATE,payload
    g=grouped_setup
    station={'type':2,'name':'Synthetic race station','audiopath':'tunein:station:race'}
    monkeypatch.setattr(audioserver.AudioServerCommands,'async_global_search',AsyncMock(return_value={'tunein':{'station':{'items':[station]}}}))
    entered,release=asyncio.Event(),asyncio.Event();sent=[]
    async def delayed(self,player,service,path,*,is_current,on_send):
        entered.set();await release.wait()
        if not is_current():raise audioserver.AudioCommandError('Synthetic stale source context')
        on_send();sent.append((player,service,path))
    monkeypatch.setattr(audioserver.AudioServerCommands,'async_play_radio_station',delayed)
    entry,co,ids=await g.setup();await g.feed(entry,row('shared',(2,1)))
    entity=g.entities[ids[2]];await entity.async_browse_media()
    selection=(await entity.async_search_media(SearchMediaQuery(search_query='race'))).result[0]
    await audio_setup.queues[0].put(json.dumps({'audio_event':[{'playerid':2,'mode':'stop','audiopath':'spotify:track:before'}]}));await hass.async_block_till_done()
    task=asyncio.create_task(entity.async_play_media(selection.media_content_type,selection.media_content_id))
    try:
        await asyncio.wait_for(entered.wait(),3)
        co.audio_grouping.observe({STATE:payload(row('shared',(1,2)))})
        release.set()
        with pytest.raises((asyncio.CancelledError,HomeAssistantError)):await asyncio.wait_for(task,3)
    finally:
        release.set()
        if not task.done():task.cancel()
        await asyncio.gather(task,return_exceptions=True)
    assert sent==[] and g.calls==[]


@pytest.mark.asyncio
@pytest.mark.parametrize('restore_token',[False,True],ids=['auth-change','auth-ABA'])
@pytest.mark.parametrize('request_mode',['play','source-return'])
async def test_source_preparation_does_not_rebind_to_new_authentication(hass,grouped_setup,audio_setup,monkeypatch,restore_token,request_mode):
    import asyncio,json
    from unittest.mock import AsyncMock
    from homeassistant.components.media_player import SearchMediaQuery
    from custom_components.loxone.pyloxone_api import audioserver
    g=grouped_setup
    station={'type':2,'name':'Synthetic auth station','audiopath':'tunein:station:auth'}
    monkeypatch.setattr(audioserver.AudioServerCommands,'async_global_search',AsyncMock(return_value={'tunein':{'station':{'items':[station]}}}))
    sent=[]
    async def play(self,player,service,path,*,is_current,on_send):
        assert is_current();on_send();sent.append((player,service,path))
        asyncio.get_running_loop().call_later(.01,audio_setup.queues[0].put_nowait,json.dumps({'audio_event':[{'playerid':player,'mode':'play','audiopath':path}]}))
    monkeypatch.setattr(audioserver.AudioServerCommands,'async_play_radio_station',play)
    entry,co,ids=await g.setup();await g.feed(entry,row('shared',(2,1)))
    entity=g.entities[ids[2]];await entity.async_browse_media()
    selection=(await entity.async_search_media(SearchMediaQuery(search_query='auth'))).result[0]
    await audio_setup.queues[0].put(json.dumps({'audio_event':[{'playerid':2,'mode':'stop','audiopath':'spotify:track:before'}]}));await hass.async_block_till_done()
    if request_mode=='source-return':
        await entity.async_play_media(selection.media_content_type,selection.media_content_id)
        assert entity.source_list
        sent.clear()
        await audio_setup.queues[0].put(json.dumps({'audio_event':[{'playerid':2,'mode':'stop','audiopath':'spotify:track:before-return'}]}));await hass.async_block_till_done()
    entered,release=asyncio.Event(),asyncio.Event();original=entity._async_ensure_source_snapshot
    async def preparing(*args,**kwargs):
        entered.set();await release.wait();return await original(*args,**kwargs)
    monkeypatch.setattr(entity,'_async_ensure_source_snapshot',preparing)
    action=entity.async_select_source(entity.source_list[0]) if request_mode=='source-return' else entity.async_play_media(selection.media_content_type,selection.media_content_id)
    task=asyncio.create_task(action)
    try:
        await asyncio.wait_for(entered.wait(),3)
        old=co.api.get_token_dict
        co.api.get_token_dict=lambda:{'token':'different-synthetic-token'};co.audio_grouping.notify()
        if restore_token:co.api.get_token_dict=old;co.audio_grouping.notify()
        release.set()
        with pytest.raises(HomeAssistantError):await asyncio.wait_for(task,3)
    finally:
        release.set()
        if not task.done():task.cancel()
        await asyncio.gather(task,return_exceptions=True)
    assert sent==[] and g.calls==[]
    assert not co.audio_grouping.native._requests
