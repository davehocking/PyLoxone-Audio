"""Fourth review regressions, real HA with synthetic transports only."""
# ruff: noqa: S101, SLF001, INP001, F811, F401, PLR2004
import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError
from test_audioserver_ha import audio_setup
from test_native_source_return_ha import install_sources, library_row, RADIO
from test_source_simple_session_ha import session_room
from custom_components.loxone.audio_radio import RADIO_MEDIA_TYPE, RadioTarget
from custom_components.loxone.audio_sources import AudioFavourite
from custom_components.loxone.pyloxone_api import audioserver as wire


async def select(hass,entity,source):
    return await hass.services.async_call('media_player','select_source',{'entity_id':entity.entity_id,'source':source},blocking=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('newest',['source','stop','third'])
async def test_new_source_and_stop_wait_for_ordinary_play_transport_cleanup(hass,audio_setup,monkeypatch,newest):
    entity,emit,writes=await install_sources(hass,audio_setup,monkeypatch,spotify=True)
    await emit(library_row())
    await emit({'playerid':7,'mode':'play','eventype':0,'audiopath':RADIO})
    entered,closing,release,closed=asyncio.Event(),asyncio.Event(),asyncio.Event(),asyncio.Event()
    request=wire.AudioServerCommands._async_request
    async def delayed(client,command,key,**kwargs):
        if command=='audio/7/play':
            assert kwargs['is_current'](); writes.append(command); entered.set()
            try: await asyncio.Event().wait()
            finally: closing.set(); await release.wait(); closed.set()
        else: return await request(client,command,key,**kwargs)
    monkeypatch.setattr(wire.AudioServerCommands,'_async_request',delayed)
    old=asyncio.create_task(hass.services.async_call('media_player','media_play',{'entity_id':entity.entity_id},blocking=True))
    actions=[]
    try:
        await asyncio.wait_for(entered.wait(),1)
        if newest=='stop':
            new=asyncio.create_task(hass.services.async_call('media_player','media_stop',{'entity_id':entity.entity_id},blocking=True))
        else: new=asyncio.create_task(select(hass,entity,'Local Library'))
        actions.append(new)
        for _ in range(60): await asyncio.sleep(0)
        assert closing.is_set(), 'New explicit intent must cancel outstanding ordinary-play transport'
        assert not closed.is_set() and not new.done()
        assert writes==['audio/7/play']
        audio_setup.apis[0].send_websocket_command.assert_not_awaited()
        if newest=='third':
            actions.append(asyncio.create_task(select(hass,entity,'Spotify')))
            for _ in range(30): await asyncio.sleep(0)
            assert writes==['audio/7/play'] and not closed.is_set()
        release.set(); await asyncio.gather(old,*actions,return_exceptions=True)
        assert closed.is_set() and entity._source_task is None
        assert not entity._transport_tasks
    finally:
        release.set()
        for task in [old,*actions]: task.cancel()
        await asyncio.gather(old,*actions,return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('spotify',[False,True])
async def test_external_success_without_optional_clock_is_remembered_after_ha_completion(hass,audio_setup,monkeypatch,spotify):
    entity,emit,writes=await install_sources(hass,audio_setup,monkeypatch,spotify=True, previous_spotify=True)
    await emit(library_row())
    await select(hass,entity,'Spotify')
    source='Spotify' if spotify else 'Local Library'
    path='spotify:track:clockless' if spotify else 'library:local:track:clockless'
    row=library_row(audiopath=path,time=None,sourceName='Synthetic owner' if spotify else None,parent={'id':None})
    before=len(writes)
    await emit(row)
    await emit({**row,'title':'Only presentation changed'})
    saved=entity._radio_catalogue.source_session(source)
    assert saved is not None and saved.audio_path==path, 'Qualified playing item does not require optional position'
    assert len(writes)==before
    await emit({'playerid':7,'mode':'play','eventype':0,'audiopath':RADIO})
    async def request(client,command,key,*,is_current,on_send,**kwargs):
        assert is_current(); on_send(); writes.append(command)
        audio_setup.queues[0].put_nowait(json.dumps({'audio_event':[row]}))
    monkeypatch.setattr(wire.AudioServerCommands,'_async_request',request)
    await select(hass,entity,source)
    assert path.replace(':','%3A') in writes[before]


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['library-context','library-playlist','spotify-track','spotify-context'])
async def test_successful_favourite_replaces_prior_success_before_immediate_departure(hass,audio_setup,monkeypatch,kind):
    entity,emit,writes=await install_sources(hass,audio_setup,monkeypatch,spotify=True)
    spotify=kind.startswith('spotify')
    source='Spotify' if spotify else 'Local Library'
    prefix='spotify:' if spotify else 'library:local:'
    user='Synthetic owner' if spotify else None
    await emit(library_row(audiopath=prefix+'track:old',sourceName=user))
    context=kind.endswith(('context','playlist'))
    native=('playlist:synthetic' if kind=='library-playlist' else prefix+('playlist:favourite' if spotify and context else 'folder:favourite' if context else 'track:favourite'))
    path=native.replace('spotify:','spotify@synthetic-account:',1) if spotify else native
    favourite=AudioFavourite(7,42,'Synthetic favourite',path,context)
    favourite_kind='spotify_playlist' if spotify and context else 'spotify_track' if spotify else 'playlist' if kind=='library-playlist' else 'library_folder'
    monkeypatch.setattr(wire.AudioServerCommands,'async_room_favourites',AsyncMock(return_value=[{'id':7,'start':0,'totalitems':1,'items':[{'id':42,'name':'Synthetic favourite','type':favourite_kind,'audiopath':path}]}]))
    item=entity._radio_catalogue._item(RadioTarget('favourite','Synthetic favourite',favourite=favourite))
    row=library_row(audiopath=prefix+'track:favourite',parent={'id':native if context else None},sourceName=user)
    async def request(client,command,key,*,is_current,on_send,**kwargs):
        assert is_current(); on_send(); writes.append(command)
        audio_setup.queues[0].put_nowait(json.dumps({'audio_event':[row]}))
    monkeypatch.setattr(wire.AudioServerCommands,'_async_request',request)
    await hass.services.async_call('media_player','play_media',{'entity_id':entity.entity_id,'media_content_type':RADIO_MEDIA_TYPE,'media_content_id':item.media_content_id},blocking=True)
    saved=entity._radio_catalogue.source_session(source)
    assert saved.audio_path==row['audiopath'], 'Successful favourite must commit exact playback before departure'
    await emit({'playerid':7,'mode':'play','eventype':0,'audiopath':RADIO})
    assert entity._radio_catalogue.source_session(source).audio_path==row['audiopath']


@pytest.mark.asyncio
@pytest.mark.parametrize('loss',['history-error','inventory-omission'])
async def test_radio_last_success_beats_missing_or_unconfirmed_history(hass,audio_setup,monkeypatch,loss):
    entity,emit,writes=await install_sources(hass,audio_setup,monkeypatch)
    await emit({'playerid':7,'mode':'play','eventype':0,'audiopath':RADIO})
    await emit(library_row())
    if loss=='inventory-omission':
        original=wire.AudioServerCommands.async_radio_services
        monkeypatch.setattr(wire.AudioServerCommands,'async_radio_services',AsyncMock(return_value=[]))
        await entity._async_refresh_native_sources()
        monkeypatch.setattr(wire.AudioServerCommands,'async_radio_services',original)
        monkeypatch.setattr(wire.AudioServerCommands,'async_recent_sources',AsyncMock(return_value={'items':[{'type':2,'audiopath':'tunein:station:unconfirmed','title':'Not played'}],'ts':2}))
        await entity._async_refresh_native_sources()
    else:
        monkeypatch.setattr(wire.AudioServerCommands,'async_recent_sources',AsyncMock(side_effect=wire.AudioCommandError('Synthetic optional history loss')))
    async def request(client,command,key,*,is_current,on_send,**kwargs):
        assert is_current(); on_send(); writes.append(command)
        audio_setup.queues[0].put_nowait(json.dumps({'audio_event':[{'playerid':7,'mode':'play','eventype':0,'audiopath':RADIO}]}))
    monkeypatch.setattr(wire.AudioServerCommands,'_async_request',request)
    await select(hass,entity,'TuneIn')
    assert writes==['audio/7/serviceplay/radio/world/tunein%3Astation%3Asynthetic']
    assert entity._source_task is None
