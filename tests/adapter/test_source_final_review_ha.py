"""Final independent source-review regressions; real HA, synthetic I/O only."""
# ruff: noqa: S101, SLF001, INP001, F811, F401
import asyncio
import json
from dataclasses import replace
from datetime import timedelta

import pytest
from homeassistant.util import dt as dt_util
from test_audioserver_ha import audio_setup
from test_native_source_return_ha import install_sources, library_row, RADIO, TRACK
from custom_components.loxone.audio_catalogue import CatalogueTarget
from custom_components.loxone.audio_radio import RADIO_MEDIA_TYPE
from custom_components.loxone.pyloxone_api import audioserver as wire


async def select(hass, entity, source):
    await hass.services.async_call('media_player','select_source',{'entity_id':entity.entity_id,'source':source},blocking=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('frame_age',['before-attempt','during-preparation'])
async def test_pre_dispatch_old_visit_cannot_replace_retained_success(hass,audio_setup,monkeypatch,frame_age):
    entity,emit,writes=await install_sources(hass,audio_setup,monkeypatch)
    await emit(library_row())
    saved=entity._radio_catalogue.source_session('Local Library')
    await emit({'playerid':7,'mode':'play','eventype':0,'audiopath':RADIO})
    entered,release=asyncio.Event(),asyncio.Event()
    original_request=wire.AudioServerCommands._async_request
    async def blocked(client,command,key,**kwargs):
        if 'obsolete-A2' in command:
            entered.set();await release.wait()  # Native preparation, before on_send.
        return await original_request(client,command,key,**kwargs)
    monkeypatch.setattr(wire.AudioServerCommands,'_async_request',blocked)
    target=CatalogueTarget('item','Pending A2','library','library:local:track:obsolete-A2',audio_path='library:local:track:obsolete-A2')
    media_id=entity._radio_catalogue._item(target).media_content_id
    pre_attempt=dt_util.utcnow()
    action=asyncio.create_task(hass.services.async_call('media_player','play_media',{
        'entity_id':entity.entity_id,'media_content_type':RADIO_MEDIA_TYPE,'media_content_id':media_id},blocking=True))
    try:
        await asyncio.wait_for(entered.wait(),1)
        # Drive the real coordinator/entity callback with delayed old-visit data.
        observed=replace(saved,audio_path=target.audio_path,received_at=(pre_attempt if frame_age=='before-attempt' else dt_util.utcnow()),position_updated_at=pre_attempt,position=10)
        coordinator=entity._audio_metadata
        coordinator._client._receiver._metadata[7]=observed
        coordinator._on_update((observed,))
        # Restore actual radio presentation, then select B to obsolete A2.
        seen=asyncio.Event()
        remove=coordinator.async_add_listener(7,seen.set)
        try:
            audio_setup.queues[0].put_nowait(json.dumps({'audio_event':[{'playerid':7,'mode':'play','eventype':0,'audiopath':RADIO}]}))
            await asyncio.wait_for(seen.wait(),1)
        finally:remove()
        await select(hass,entity,'TuneIn')
        result=await asyncio.gather(action,return_exceptions=True)
        assert isinstance(result[0],asyncio.CancelledError)
        assert entity._radio_catalogue.source_session('Local Library') is saved
        release.set()
        await select(hass,entity,'Local Library')
        assert TRACK.replace(':','%3A') in writes[0]
        assert not any('obsolete-A2' in command for command in writes)
    finally:
        release.set();action.cancel();await asyncio.gather(action,return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('spotify',[False,True])
async def test_confirmed_explicit_seek_retains_position_for_immediate_return(hass,audio_setup,monkeypatch,spotify):
    entity,emit,writes=await install_sources(hass,audio_setup,monkeypatch,spotify=spotify)
    row=library_row()
    if spotify:row.update(audiopath='spotify:track:original',parent={'id':'spotify:playlist:original'},sourceName='Synthetic owner')
    await emit(row)
    source='Spotify' if spotify else 'Local Library'
    assert entity._radio_catalogue.source_session(source).position==45
    await hass.services.async_call('media_player','media_seek',{'entity_id':entity.entity_id,'seek_position':80},blocking=True)
    assert entity._radio_catalogue.source_session(source).position==80
    await emit({'playerid':7,'mode':'play','eventype':0,'audiopath':RADIO})
    writes.clear()
    await select(hass,entity,source)
    assert writes[-1]=='audio/7/position/80.0'
    assert entity._radio_catalogue.source_session(source).position==80


@pytest.mark.asyncio
@pytest.mark.parametrize('spotify',[False,True])
@pytest.mark.parametrize('placeholder',[0,None])
async def test_pause_placeholder_preserves_confirmed_seek_for_return(hass,audio_setup,monkeypatch,spotify,placeholder):
    entity,emit,writes=await install_sources(hass,audio_setup,monkeypatch,spotify=spotify)
    row=library_row()
    if spotify:row.update(audiopath='spotify:track:original',parent={'id':'spotify:playlist:original'},sourceName='Synthetic owner')
    source='Spotify' if spotify else 'Local Library'
    await emit(row)
    await hass.services.async_call('media_player','media_seek',{'entity_id':entity.entity_id,'seek_position':80},blocking=True)
    await emit({**row,'mode':'pause','time':placeholder})
    assert entity._radio_catalogue.source_session(source).position==80
    await emit({'playerid':7,'mode':'play','eventype':0,'audiopath':RADIO})
    writes.clear()
    await select(hass,entity,source)
    assert writes[-1]=='audio/7/position/80.0'


@pytest.mark.asyncio
@pytest.mark.parametrize('spotify',[False,True])
async def test_explicit_confirmed_seek_to_zero_is_not_a_placeholder(hass,audio_setup,monkeypatch,spotify):
    entity,emit,_writes=await install_sources(hass,audio_setup,monkeypatch,spotify=spotify)
    row=library_row()
    if spotify:row.update(audiopath='spotify:track:original',parent={'id':'spotify:playlist:original'},sourceName='Synthetic owner')
    source='Spotify' if spotify else 'Local Library'
    await emit(row)
    await hass.services.async_call('media_player','media_seek',{'entity_id':entity.entity_id,'seek_position':0},blocking=True)
    assert entity._radio_catalogue.source_session(source).position==0


@pytest.mark.asyncio
@pytest.mark.parametrize('spotify',[False,True])
@pytest.mark.parametrize('placeholder',[0,None])
async def test_passive_play_placeholder_also_preserves_confirmed_position(hass,audio_setup,monkeypatch,spotify,placeholder):
    entity,emit,writes=await install_sources(hass,audio_setup,monkeypatch,spotify=spotify)
    row=library_row()
    if spotify:row.update(audiopath='spotify:track:original',parent={'id':'spotify:playlist:original'},sourceName='Synthetic owner')
    source='Spotify' if spotify else 'Local Library'
    await emit(row)
    await hass.services.async_call('media_player','media_seek',{'entity_id':entity.entity_id,'seek_position':80},blocking=True)
    await emit({**row,'time':placeholder})
    assert entity._radio_catalogue.source_session(source).position==80
    await emit({'playerid':7,'mode':'play','eventype':0,'audiopath':RADIO})
    writes.clear()
    await select(hass,entity,source)
    assert writes[-1]=='audio/7/position/80.0'


@pytest.mark.asyncio
@pytest.mark.parametrize('spotify',[False,True])
async def test_exact_return_without_current_position_does_not_attempt_optional_seek(hass,audio_setup,monkeypatch,spotify):
    entity,emit,writes=await install_sources(hass,audio_setup,monkeypatch,spotify=spotify)
    row=library_row()
    if spotify:row.update(audiopath='spotify:track:original',parent={'id':'spotify:playlist:original'},sourceName='Synthetic owner')
    source='Spotify' if spotify else 'Local Library'
    await emit(row)
    await emit({'playerid':7,'mode':'play','eventype':0,'audiopath':RADIO})
    async def request(_client,command,_key,*,is_current,on_send,**_kwargs):
        assert is_current()
        if on_send is not None:
            on_send()
        writes.append(command)
        seen=asyncio.Event();remove=entity._audio_metadata.async_add_listener(7,seen.set)
        try:
            audio_setup.queues[0].put_nowait(json.dumps({'audio_event':[{**row,'time':None}]}))
            await asyncio.wait_for(seen.wait(),1)
        finally:remove()
    monkeypatch.setattr(wire.AudioServerCommands,'_async_request',request)
    await select(hass,entity,source)
    # Missing current progress does not veto an optional ordinary seek.
    expected_writes = 2
    assert len(writes) == expected_writes
    assert writes[-1] == "audio/7/position/45.0"
    assert entity._radio_catalogue.source_session(source).position==45


@pytest.mark.asyncio
@pytest.mark.parametrize('spotify',[False,True])
@pytest.mark.parametrize('sequence',[(None,0),(None,None,0),(0,None,0),(None,0,0)])
async def test_combined_play_placeholders_cannot_clear_confirmed_clock(hass,audio_setup,monkeypatch,spotify,sequence):
    entity,emit,writes=await install_sources(hass,audio_setup,monkeypatch,spotify=spotify)
    row=library_row()
    if spotify:row.update(audiopath='spotify:track:original',parent={'id':'spotify:playlist:original'},sourceName='Synthetic owner')
    source='Spotify' if spotify else 'Local Library'
    await emit(row)
    await hass.services.async_call('media_player','media_seek',{'entity_id':entity.entity_id,'seek_position':80},blocking=True)
    for position in sequence:await emit({**row,'time':position})
    assert entity._radio_catalogue.source_session(source).position==80
    await emit({'playerid':7,'mode':'play','eventype':0,'audiopath':RADIO})
    writes.clear()
    await select(hass,entity,source)
    assert writes[-1]=='audio/7/position/80.0'


# Owner message1563614353373134921 accepts qualified reported playback even
# when its causal origin cannot distinguish a cancelled visit from a new
# external selection of the same item. Original stricter test and failed
# receipts are preserved in parent-continuation300/owner-reported-playback01.
@pytest.mark.asyncio
@pytest.mark.parametrize('late_count',[2,3])
@pytest.mark.parametrize('external',[False,True])
async def test_repeated_post_supersession_playback_uses_reported_item(hass,audio_setup,monkeypatch,late_count,external):
    entity,emit,writes=await install_sources(hass,audio_setup,monkeypatch,spotify=True)
    await emit(library_row())
    saved=entity._radio_catalogue.source_session('Local Library')
    target=CatalogueTarget('item','Pending A2','library','library:local:track:a2',audio_path='library:local:track:a2')
    media_id=entity._radio_catalogue._item(target).media_content_id
    entered=asyncio.Event()
    original=wire.AudioServerCommands._async_request
    async def blocked(client,command,key,**kwargs):
        if 'library%3Alocal%3Atrack%3Aa2' in command:
            assert kwargs['is_current']()
            kwargs['on_send']();writes.append(command);entered.set()
            await asyncio.Event().wait()
        return await original(client,command,key,**kwargs)
    monkeypatch.setattr(wire.AudioServerCommands,'_async_request',blocked)
    action=asyncio.create_task(hass.services.async_call('media_player','play_media',{
        'entity_id':entity.entity_id,'media_content_type':RADIO_MEDIA_TYPE,'media_content_id':media_id},blocking=True))
    try:
        await asyncio.wait_for(entered.wait(),1)
        await select(hass,entity,'Spotify')
        assert isinstance((await asyncio.gather(action,return_exceptions=True))[0],asyncio.CancelledError)
        assert entity._source_task is None
        assert entity._radio_catalogue.source_session('Local Library') is saved
        writes_before=list(writes)
        observed='library:local:track:external-new' if external else target.audio_path
        for index in range(late_count):await emit(library_row(audiopath=observed,time=7+index))
        assert writes==writes_before,'Passive feedback cannot replay or seek'
        assert entity._radio_catalogue.source_session('Local Library').audio_path==observed
        assert entity._radio_catalogue.source_session('Local Library').position==6+late_count
        # Returning to the now-reported active native session must not replay
        # the former A1 bookmark or issue a corrective seek into current A2.
        await select(hass,entity,'Local Library')
        assert writes==writes_before,'Native-session return cannot replay or seek old last-good'
    finally:
        action.cancel();await asyncio.gather(action,return_exceptions=True)
