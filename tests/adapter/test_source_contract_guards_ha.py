"""Unchanged contracts on current native-session real HA path, synthetic only."""
# ruff: noqa: S101, SLF001, INP001, F811, F401, PLR2004
from __future__ import annotations
import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import ClientError
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError

from test_audioserver_ha import audio_setup, zone_entity_id
from test_source_simple_session_ha import session_room
from test_native_source_return_ha import install_sources, library_row, RADIO
from test_spotify_continuity import TRACK, CONTEXT
from custom_components.loxone.audio_catalogue import CatalogueTarget
from custom_components.loxone.audio_radio import RADIO_MEDIA_TYPE, RadioTarget
from custom_components.loxone.pyloxone_api import audioserver as wire


async def select(hass, entity, source='Spotify'):
    await hass.services.async_call('media_player','select_source',{'entity_id':entity.entity_id,'source':source},blocking=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('optional', ['healthy','missing-entry','disabled','unloaded','missing-session','outage','malformed-device','missing-item','native-only'])
@pytest.mark.parametrize('kind', ['track','episode','missing-optional-fields'])
async def test_active_owned_spotify_repeated_selection_never_restarts_or_seeks(hass,audio_setup,monkeypatch,optional,kind,caplog):
    entity,emit,writes,session,row=await session_room(hass,audio_setup,monkeypatch)
    row={**row,'time':95,'audiopath':('spotify:episode:' if kind=='episode' else 'spotify:track:')+'X'*22}
    if kind=='missing-optional-fields':
        row.update(time=None,duration=None,pbr=None)
    session.current['item']['uri']=row['audiopath']
    session.current['is_playing']=False  # Paused provider view cannot restart native playing.
    if optional=='missing-entry':
        get=hass.config_entries.async_get_entry
        monkeypatch.setattr(hass.config_entries,'async_get_entry',lambda key: None if key=='synthetic-entry' else get(key))
    elif optional in ('disabled','unloaded','missing-session'):
        entry=hass.config_entries.async_get_entry('synthetic-entry')
        if optional=='disabled': entry.disabled_by='user'
        elif optional=='unloaded': entry.state=ConfigEntryState.NOT_LOADED
        else: entry.runtime_data.session=None
    elif optional in ('outage','malformed-device','missing-item'):
        if optional=='outage': monkeypatch.setattr(session,'async_request',AsyncMock(side_effect=ClientError('Synthetic optional outage')))
        elif optional=='malformed-device': session.current['device']=None
        else: session.current['item']=None
    elif optional=='native-only':
        assert not hasattr(entity, '_spotify_return')
    await emit(row)
    history=AsyncMock(side_effect=AssertionError('Active playback must not consult history'))
    monkeypatch.setattr(wire.AudioServerCommands,'async_recent_sources',history)
    before=entity._radio_catalogue.source_session('Spotify')
    for _ in range(3): await select(hass,entity)
    assert writes==[]
    history.assert_not_awaited()
    assert entity._audio_metadata.get(7).audio_path==row['audiopath']
    assert entity._radio_catalogue.source_session('Spotify').audio_path==before.audio_path
    assert all(m=='GET' and not u.endswith('/queue') for m,u,_ in session.calls)
    assert not [r for r in caplog.records if r.name.startswith('custom_components.loxone') and r.levelno>=30]


@pytest.mark.asyncio
@pytest.mark.parametrize('missing', ['device','item','response','auth'])
async def test_retained_success_remains_visible_and_exact_fallback_dispatches_without_history(hass,audio_setup,monkeypatch,missing):
    entity,emit,writes,session,row=await session_room(hass,audio_setup,monkeypatch)
    # Current fixture has positively played this exact synthetic item earlier.
    if missing=='device': session.current['device']=None
    elif missing=='item': session.current['item']=None
    elif missing=='response': session.current=None
    else:
        assert not hasattr(entity, '_spotify_return')
    monkeypatch.setattr(wire.AudioServerCommands,'async_recent_sources',AsyncMock(return_value={'items':[],'ts':2}))
    await entity._async_refresh_native_sources()
    assert 'Spotify' in entity.source_list
    async def request(client,command,key,*,is_current,on_send,**kwargs):
        assert is_current(); on_send(); writes.append(command)
        bits=command.split('/')
        assert bits[2:4]==['serviceplay','spotify']
        assert bits[5], "Native return requires the room's remembered content"
        assert TRACK.replace(":", "%3A") in bits[5]
        audio_setup.queues[0].put_nowait(json.dumps({'audio_event':[{**row,'time':0,'pbr':0}]}))
    monkeypatch.setattr(wire.AudioServerCommands,'_async_request',request)
    await select(hass,entity)
    assert len(writes)==1
    assert all(m=='GET' and not u.endswith('/queue') for m,u,_ in session.calls)






@pytest.mark.asyncio
async def test_failed_new_spotify_item_preserves_old_success_for_next_explicit_return(hass,audio_setup,monkeypatch):
    entity,emit,writes=await install_sources(hass,audio_setup,monkeypatch,spotify=True)
    old=library_row(audiopath='spotify:track:original',parent={'id':'spotify:playlist:original'},sourceName='Synthetic owner')
    await emit(old)
    await emit({'playerid':7,'mode':'play','eventype':0,'audiopath':RADIO})
    target=CatalogueTarget('item','Attempted new item','spotify',folder='spotify@synthetic-account:track:newer',account='synthetic-account',audio_path='spotify:track:newer')
    item=entity._radio_catalogue._item(target)
    original=wire.AudioServerCommands._async_request
    async def failed(client,command,key,*,is_current,on_send,**kwargs):
        if 'newer' in command:
            assert is_current(); on_send(); writes.append(command)
            raise wire.AudioCommandError('Synthetic new item failed')
        return await original(client,command,key,is_current=is_current,on_send=on_send,**kwargs)
    monkeypatch.setattr(wire.AudioServerCommands,'_async_request',failed)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call('media_player','play_media',{'entity_id':entity.entity_id,'media_content_type':RADIO_MEDIA_TYPE,'media_content_id':item.media_content_id},blocking=True)
    assert entity._radio_catalogue.source_session('Spotify').audio_path==old['audiopath']
    await select(hass,entity)
    assert 'newer' in writes[0]
    assert 'spotify%3Atrack%3Aoriginal' in writes[1]
    assert len(writes)==3
    assert entity._source_task is None


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['track','context'])
async def test_explicit_spotify_browse_overrides_resumable_session_without_early_success(hass,audio_setup,monkeypatch,kind):
    entity,_emit,writes,session,row=await session_room(hass,audio_setup,monkeypatch)
    target_path='spotify@synthetic-account:'+('track:' if kind=='track' else 'playlist:')+'N'*22
    target=CatalogueTarget('item','Chosen new content','spotify',folder=target_path,account='synthetic-account',audio_path=target_path,is_context=kind=='context')
    item=entity._radio_catalogue._item(target)
    received,release=asyncio.Event(),asyncio.Event()
    previous=entity._radio_catalogue.source_session('Spotify')
    async def request(client,command,key,*,is_current,on_send,**kwargs):
        assert is_current(); on_send(); writes.append(command); received.set(); await release.wait()
        audio_setup.queues[0].put_nowait(json.dumps({'audio_event':[{**row,'audiopath':'spotify:track:'+'N'*22,'parent':{'id':'spotify:playlist:'+'N'*22}}]}))
    monkeypatch.setattr(wire.AudioServerCommands,'_async_request',request)
    action=asyncio.create_task(hass.services.async_call('media_player','play_media',{'entity_id':entity.entity_id,'media_content_type':RADIO_MEDIA_TYPE,'media_content_id':item.media_content_id},blocking=True))
    try:
        await asyncio.wait_for(received.wait(),1)
        assert entity._radio_catalogue.source_session('Spotify') is previous
        assert writes[0].endswith(target_path.replace(':','%3A').replace('@','%40') + ('/noshuffle' if kind == 'track' else ''))
        assert session.calls==[], 'Explicit content must not consult/resume a different session'
        release.set(); await asyncio.wait_for(action,2)
        assert entity._radio_catalogue.source_session('Spotify').audio_path=='spotify:track:'+'N'*22
    finally:
        release.set(); action.cancel(); await asyncio.gather(action,return_exceptions=True)


@pytest.mark.asyncio
async def test_deliberate_native_account_b_remains_independent_of_bound_account_a(hass,audio_setup,monkeypatch):
    entity,emit,writes,session,_row=await session_room(hass,audio_setup,monkeypatch)
    accounts=[{'cmd':'spotify','id':'synthetic-account','user':'Synthetic owner','configerror':False},
              {'cmd':'spotify','id':'account-b','user':'Native B','configerror':False}]
    monkeypatch.setattr(wire.AudioServerCommands,'async_service_accounts',AsyncMock(return_value=accounts))
    history=AsyncMock(return_value={'items':[{'type':2,'audiopath':RADIO,'title':'Synthetic station'}],'ts':2})
    monkeypatch.setattr(wire.AudioServerCommands,'async_recent_sources',history)
    await entity._async_refresh_native_sources()
    path='spotify@account-b:track:'+'B'*22
    item=entity._radio_catalogue._item(CatalogueTarget('item','Native B track','spotify',folder=path,account='account-b',audio_path=path))
    row=library_row(audiopath='spotify:track:'+'B'*22,sourceName='Native B')
    async def request(client,command,key,*,is_current,on_send,**kwargs):
        assert is_current(); on_send(); writes.append(command)
        event=row if '/serviceplay/spotify/account-b/' in command else {'playerid':7,'mode':'play','eventype':0,'audiopath':RADIO}
        audio_setup.queues[0].put_nowait(json.dumps({'audio_event':[event]}))
    monkeypatch.setattr(wire.AudioServerCommands,'_async_request',request)
    await hass.services.async_call('media_player','play_media',{'entity_id':entity.entity_id,'media_content_type':RADIO_MEDIA_TYPE,'media_content_id':item.media_content_id},blocking=True)
    label=next(label for label,descriptor in entity._radio_catalogue.source_descriptors.items() if descriptor.account=='account-b')
    await select(hass,entity,label)
    assert len(writes)==1, 'Already playing native account B must not restart old account A history'
    await select(hass,entity,'TuneIn')
    assert len(writes)==2 and writes[-1].startswith('audio/7/serviceplay/radio/world/')
    assert session.calls==[], 'Account B and departure must not consult bound account A'
    assert entity._radio_catalogue.source_session(label).source_name=='Native B'
    assert entity._source_task is None


@pytest.mark.asyncio
async def test_overlapping_two_players_do_not_share_intent_cleanup_or_success(hass,audio_setup,monkeypatch):
    import test_audioserver_ha as fixtures
    structure=deepcopy(fixtures.STRUCTURE)
    prototype=next(iter(structure['controls'].values()))
    structure['controls']={}
    for pid in (7,8):
        zone=deepcopy(prototype)
        zone.update(uuidAction=f'synthetic-zone-{pid}',details={'playerid':pid},states={'volume':f'volume-{pid}','playState':f'play-{pid}'})
        structure['controls'][zone['uuidAction']]=zone
    monkeypatch.setattr(fixtures,'STRUCTURE',structure)
    entity,emit,writes=await install_sources(hass,audio_setup,monkeypatch,spotify=True, previous_spotify=True)
    peer=hass.data['media_player'].get_entity(zone_entity_id(hass,8))
    for pid in (7,8):
        await emit(library_row(playerid=pid))
        await emit({'playerid':pid,'mode':'play','eventype':0,'audiopath':RADIO})
    peer_good=peer._radio_catalogue.source_session('Local Library')
    entered,closing,release=asyncio.Event(),asyncio.Event(),asyncio.Event()
    original=wire.AudioServerCommands._async_request
    async def delayed(client,command,key,*,is_current,on_send,**kwargs):
        if command.startswith('audio/7/serviceplay/spotify/'):
            assert is_current(); on_send(); writes.append(command); entered.set()
            try: await asyncio.Event().wait()
            finally:
                closing.set(); await release.wait()
        else: return await original(client,command,key,is_current=is_current,on_send=on_send,**kwargs)
    monkeypatch.setattr(wire.AudioServerCommands,'_async_request',delayed)
    old=asyncio.create_task(select(hass,entity))
    newer=None
    try:
        await asyncio.wait_for(entered.wait(),1)
        newer=asyncio.create_task(select(hass,entity,'Local Library'))
        await asyncio.wait_for(closing.wait(),1)
        await asyncio.wait_for(select(hass,peer,'Local Library'),2)
        assert not newer.done(), 'Player7 cleanup remains pending; player8 can independently complete'
        assert peer._radio_catalogue.source_session('Local Library').audio_path==peer_good.audio_path
        assert peer._source_task is None
        release.set(); await asyncio.gather(old,newer,return_exceptions=True)
        assert entity._source_task is None
        assert entity._audio_metadata.get(7).source=='Local Library'
        assert peer._audio_metadata.get(8).source=='Local Library'
        assert any(c.startswith('audio/8/library/play/') for c in writes)
    finally:
        release.set()
        for task in (old,newer):
            if task: task.cancel()
        await asyncio.gather(*(t for t in (old,newer) if t),return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('choice', ['Local Library', 'Spotify'])
@pytest.mark.parametrize('optional', ['healthy', 'outage'])
async def test_old_provider_uncertainty_is_not_a_veto_on_new_explicit_native_choice(hass,audio_setup,monkeypatch,choice,optional):
    from custom_components.loxone import spotify_continuity as continuity
    entity,emit,writes,session,row=await session_room(hass,audio_setup,monkeypatch)
    await emit(library_row())
    await emit({'playerid':7,'mode':'play','eventype':0,'audiopath':RADIO})
    if optional=='outage':
        monkeypatch.setattr(session,'async_request',AsyncMock(side_effect=ClientError('Synthetic optional loss')))
    original=wire.AudioServerCommands._async_request
    async def request(client,command,key,*,is_current,on_send,**kwargs):
        if '/serviceplay/spotify/' in command:
            assert is_current(); on_send(); writes.append(command)
            audio_setup.queues[0].put_nowait(json.dumps({'audio_event':[{**row,'time':0}]}))
            return None
        return await original(client,command,key,is_current=is_current,on_send=on_send,**kwargs)
    monkeypatch.setattr(wire.AudioServerCommands,'_async_request',request)
    marker=(entity.unique_id,7)
    entity.hass.data.setdefault(continuity._ROOM_FENCES,set()).add(marker)
    before=entity._radio_catalogue.source_session(choice)
    try:
        await select(hass,entity,choice)
        assert writes and ('/library/play/' if choice=='Local Library' else '/serviceplay/spotify/') in writes[0]
        assert entity._radio_catalogue.source_session(choice).audio_path==before.audio_path
        assert marker in entity.hass.data[continuity._ROOM_FENCES], 'Do not clear unknown old write markers to manufacture success'
        assert entity._source_task is None
    finally:
        entity.hass.data[continuity._ROOM_FENCES].discard(marker)
