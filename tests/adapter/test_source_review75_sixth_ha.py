"""Sixth source-review regressions, real HA and synthetic-only endpoints."""
# ruff: noqa: S101, SLF001, INP001, F811, F401
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock

import pytest
from homeassistant.exceptions import HomeAssistantError
from test_audioserver_ha import audio_setup
from test_native_source_return_ha import install_sources,library_row,RADIO,PARENT
from test_source_simple_session_ha import session_room
from custom_components.loxone import spotify_continuity as continuity
from custom_components.loxone.pyloxone_api import audioserver as wire


async def select(hass,entity,source):
    await hass.services.async_call('media_player','select_source',{'entity_id':entity.entity_id,'source':source},blocking=True)


@pytest.mark.asyncio
async def test_wrong_return_parent_never_overwrites_retained_success(hass,audio_setup,monkeypatch):
    entity,emit,writes=await install_sources(hass,audio_setup,monkeypatch)
    await emit(library_row())
    saved=entity._radio_catalogue.source_session('Local Library')
    await emit({'playerid':7,'mode':'play','eventype':0,'audiopath':RADIO})
    async def wrong(client,command,key,*,is_current,on_send,**kwargs):
        assert is_current()
        if on_send is not None:
            on_send()
        writes.append(command)
        audio_setup.queues[0].put_nowait(json.dumps({'audio_event':[library_row(parent={'id':'library:local:folder:wrong'})]}))
    monkeypatch.setattr(wire.AudioServerCommands,'_async_request',wrong)
    await select(hass,entity,'Local Library')
    actual = entity._radio_catalogue.source_session('Local Library')
    assert actual is not saved
    assert actual.parent_id == 'library:local:folder:wrong'
    expected_writes = 2
    assert len(writes) == expected_writes and "/parentpath/" in writes[0]
    assert writes[-1] == "audio/7/position/45.0"


@pytest.mark.asyncio
@pytest.mark.parametrize('native',['playing','paused','radio'])
async def test_malformed_optional_json_is_quiet_and_unchanged_native_can_continue(hass,audio_setup,monkeypatch,native):
    entity,emit,writes,session,row=await session_room(hass,audio_setup,monkeypatch)
    if native!='radio': await emit({**row,'mode':'play' if native=='playing' else 'pause'})
    response=SimpleNamespace(status=200,json=AsyncMock(side_effect=ValueError('Synthetic invalid provider JSON')),release=Mock())
    original=session.async_request
    async def malformed(method,url,**kwargs):
        if url.endswith('/me/player'): return response
        return await original(method,url,**kwargs)
    monkeypatch.setattr(session,'async_request',malformed)
    async def request(client,command,key,*,is_current,on_send,**kwargs):
        assert is_current()
        if on_send is not None:
            on_send()
        writes.append(command)
        # Context lookup is unavailable in this fixture: confirm the exact
        # item without inventing the old parent/position enrichment.
        returned={**row,'parent':{},'time':0} if native=='radio' else row
        audio_setup.queues[0].put_nowait(json.dumps({'audio_event':[returned]}))
    monkeypatch.setattr(wire.AudioServerCommands,'_async_request',request)
    await select(hass,entity,'Spotify')
    assert len(writes) == {"playing": 0, "paused": 1, "radio": 2}[native]
    if native=='radio': assert row['audiopath'].replace(':','%3A') in writes[0]
    if native=='paused': assert writes[0].endswith('/synthetic-account/')
    assert response.release.called


@pytest.mark.asyncio
@pytest.mark.parametrize('control',['play','seek'])
async def test_confirmed_library_controls_ignore_only_historical_provider_marker(hass,audio_setup,monkeypatch,control):
    entity,emit,writes,session,row=await session_room(hass,audio_setup,monkeypatch)
    await emit(library_row())
    await emit({'playerid':7,'mode':'play','eventype':0,'audiopath':RADIO})
    marker=(entity.unique_id,7)
    entity.hass.data.setdefault(continuity._ROOM_FENCES,set()).add(marker)
    original=wire.AudioServerCommands._async_request
    async def request(client,command,key,**kwargs):
        if command in ('audio/7/pause','audio/7/play'):
            assert kwargs['is_current']()
            if kwargs.get('on_send'): kwargs['on_send']()
            writes.append(command); return True
        return await original(client,command,key,**kwargs)
    monkeypatch.setattr(wire.AudioServerCommands,'_async_request',request)
    try:
        await select(hass,entity,'Local Library')
        await hass.services.async_call('media_player','media_pause',{'entity_id':entity.entity_id},blocking=True)
        await emit(library_row(mode='pause'))
        if control=='play':
            await hass.services.async_call('media_player','media_play',{'entity_id':entity.entity_id},blocking=True)
            assert writes[-1]=='audio/7/play'
        else:
            await hass.services.async_call('media_player','media_seek',{'entity_id':entity.entity_id,'seek_position':80},blocking=True)
            assert writes[-1]=='audio/7/position/80.0'
        assert marker in entity.hass.data[continuity._ROOM_FENCES]
        assert entity._source_task is None
    finally: entity.hass.data[continuity._ROOM_FENCES].discard(marker)


@pytest.mark.asyncio
@pytest.mark.parametrize('external',['pause','item'])
async def test_malformed_optional_json_cannot_hide_intervening_native_action(hass,audio_setup,monkeypatch,external):
    entity,emit,writes,session,row=await session_room(hass,audio_setup,monkeypatch)
    await emit(row)
    entered,release=asyncio.Event(),asyncio.Event()
    async def decode():
        entered.set(); await release.wait()
        raise ValueError('Synthetic malformed JSON after external action')
    response=SimpleNamespace(status=200,json=decode,release=Mock())
    original=session.async_request
    async def malformed(method,url,**kwargs):
        if url.endswith('/me/player'): return response
        return await original(method,url,**kwargs)
    monkeypatch.setattr(session,'async_request',malformed)
    action=asyncio.create_task(select(hass,entity,'Spotify'))
    try:
        await asyncio.wait_for(entered.wait(),1)
        await emit({**row,**({'mode':'pause'} if external=='pause' else {'audiopath':'spotify:track:'+'N'*22})})
        release.set()
        result=await asyncio.gather(action,return_exceptions=True)
        assert isinstance(result[0],HomeAssistantError)
        assert writes==[] and response.release.called
        assert entity._source_task is None
    finally:
        release.set(); action.cancel(); await asyncio.gather(action,return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('fence',['source','announcement'])
@pytest.mark.parametrize('control',['media_play','media_seek'])
async def test_confirmed_library_never_bypasses_current_native_fences(hass,audio_setup,monkeypatch,fence,control):
    entity,emit,writes,session,row=await session_room(hass,audio_setup,monkeypatch)
    await emit(library_row())
    fences=entity._audio_commands.source_fences if fence=='source' else entity._audio_commands.announcement_fences
    fences[7]=lambda:None
    try:
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call('media_player',control,{'entity_id':entity.entity_id,**({'seek_position':80} if control=='media_seek' else {})},blocking=True)
        assert writes==[]
    finally: fences.pop(7,None)
