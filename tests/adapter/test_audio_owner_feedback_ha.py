"""Real HA service/lifecycle acceptance for revised native Source semantics."""
# ruff: noqa: S101, INP001, ANN001, ANN202, D103, SLF001, PLC0415, F811, F401
import asyncio,json
from unittest.mock import AsyncMock
import pytest
from homeassistant.components.media_player import MediaPlayerEntityFeature
from homeassistant.exceptions import HomeAssistantError
from test_audioserver_ha import audio_setup,zone_entity_id
from test_audio_catalogue import catalogue_commands
from custom_components.loxone.pyloxone_api import audioserver as wire

@pytest.mark.asyncio
async def test_native_source_switches_last_provider_selection_and_keeps_favourites_in_browse(hass,audio_setup,monkeypatch):
    commands=catalogue_commands()
    # Real catalogue availability, not search categories or recent history.
    commands.async_media_folder.side_effect=lambda service,*_: [{'start':0,'totalitems':1,'items':[{'type':2,'id':'library:local:track:one','name':'Song'}]}] if service=='library' else [{'start':0,'totalitems':0,'items':[]}]
    commands.async_recent_sources=AsyncMock(return_value={'items':[{'type':2,'audiopath':'tunein:station:latest','title':'Latest station'},{'type':7,'audiopath':'spotify@owner:playlist:one','title':'Playlist'},{'type':2,'audiopath':'library:local:track:one','title':'Song'}],'ts':123})
    commands.async_room_favourites=AsyncMock(side_effect=lambda p:[{'id':p,'start':0,'totalitems':1,'items':[{'id':1,'name':'A saved favourite','type':'tunein','audiopath':'tunein:station:favourite'}]}])
    for name,value in vars(commands).items():monkeypatch.setattr(wire.AudioServerCommands,name,value)
    await audio_setup.setup(playback=True)
    entity=hass.data['media_player'].get_entity(zone_entity_id(hass,7))
    assert set(entity.source_list)=={'Line-In','TuneIn','Spotify','Local Library'}
    assert entity.supported_features & MediaPlayerEntityFeature.SELECT_SOURCE
    favs=await entity.async_browse_media('pyloxone_radio','pyloxone-radio:favourites')
    assert [x.title for x in favs.children]==['A saved favourite']
    assert 'A saved favourite'not in entity.source_list
    await audio_setup.queues[0].put(json.dumps({'audio_event':[{'playerid':7,'mode':'stop','audiopath':'tunein:station:before'}]}));await hass.async_block_till_done()
    calls=[]
    async def play(self,player,service,account,item,*,is_current,on_send):
        assert is_current();on_send();calls.append((player,service,account,item))
        asyncio.get_running_loop().call_soon(audio_setup.queues[0].put_nowait,json.dumps({'audio_event':[{'playerid':7,'mode':'play','audiopath':'linein:'+item}]}))
    monkeypatch.setattr(wire.AudioServerCommands,'async_play_catalogue',play)
    await hass.services.async_call('media_player','select_source',{'entity_id':entity.entity_id,'source':'Line-In'},blocking=True)
    assert calls==[(7,'linein','nouser','ABCDEF123456#1000001')]
    assert entity.source=='Line-In'
    with pytest.raises(HomeAssistantError):await entity.async_select_source('A saved favourite')
    assert len(calls)==1
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()
