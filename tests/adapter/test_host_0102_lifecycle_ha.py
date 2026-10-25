"""Audio adapter acceptance with the actual 0.10.2 owning entrypoint/TextInput.

Only transport bootstrap is synthetic; all HA platforms, entities, service/event
routing, dispatcher callbacks, setup and unload implementations are real.
"""
import asyncio
import copy

from unittest.mock import AsyncMock
import pytest
from homeassistant.const import Platform
from homeassistant.helpers import entity_registry as er

from custom_components import loxone
from custom_components.loxone.const import LOXONE_PLATFORMS, EVENT
from custom_components.loxone.coordinator import LoxoneCoordinator
import test_audioserver_ha as fixtures
from test_audioserver_ha import audio_setup as audio_setup

@pytest.mark.asyncio
async def test_0102_owning_setup_text_dispatch_multi_entry_audio_unload(hass,audio_setup,monkeypatch):
    assert Platform.TEXT in LOXONE_PLATFORMS
    monkeypatch.setattr(loxone,'LOXONE_PLATFORMS',LOXONE_PLATFORMS)
    structure=copy.deepcopy(fixtures.STRUCTURE)
    structure['controls']['synthetic-text']={
        'uuidAction':'synthetic-text','name':'Synthetic message','type':'TextInput',
        'states':{'text':'synthetic-text-state'},'details':{},
    }
    monkeypatch.setattr(fixtures,'STRUCTURE',structure)
    refresh=LoxoneCoordinator.async_config_entry_first_refresh
    callbacks={}
    async def first_refresh(co):
        await refresh(co)
        async def run(**kwargs):
            callbacks[co.config_entry.entry_id]=kwargs
            await asyncio.Future()
        co.api.run=run
    monkeypatch.setattr(LoxoneCoordinator,'async_config_entry_first_refresh',first_refresh)
    entry=await audio_setup.setup(playback=True)
    co=hass.data['loxone'][entry.entry_id]
    assert co._listening_task is not None and not co._listening_task.done()
    text_id=er.async_get(hass).async_get_entity_id('text','loxone','synthetic-text')
    assert text_id
    assert hass.states.get(text_id).state=='unknown'
    await callbacks[entry.entry_id]['callback']({'synthetic-text-state':'Fresh text'})
    await hass.async_block_till_done()
    assert hass.states.get(text_id).state=='Fresh text'
    await hass.services.async_call('text','set_value',{'entity_id':text_id,'value':'Synthetic set'},blocking=True)
    await hass.async_block_till_done()
    co.api.send_websocket_command.assert_awaited_once_with('synthetic-text','Synthetic set')
    # No false optimistic update before real feedback.
    assert hass.states.get(text_id).state=='Fresh text'
    callbacks[entry.entry_id]['on_state']('disconnected')
    await hass.async_block_till_done()
    assert hass.states.get(text_id).state=='unavailable'
    callbacks[entry.entry_id]['on_state']('connected')
    await hass.async_block_till_done()
    assert hass.states.get(text_id).state=='Fresh text'
    structure2=copy.deepcopy(structure)
    structure2['controls']={k+'-two':{**v,'uuidAction':k+'-two'} for k,v in structure['controls'].items()}
    monkeypatch.setattr(fixtures,'STRUCTURE',structure2)
    second=await audio_setup.setup(host='second.example.invalid',title='Second synthetic entry')
    second_co=hass.data['loxone'][second.entry_id]
    # Real optional command and metadata resources are owned by the coordinator.
    commands=co.audio_commands;metadata=co.audio_metadata;task=co._listening_task
    close=AsyncMock(wraps=commands.async_close)
    stop=AsyncMock(wraps=metadata.async_stop)
    monkeypatch.setattr(commands,'async_close',close)
    monkeypatch.setattr(metadata,'async_stop',stop)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    close.assert_awaited_once();stop.assert_awaited_once()
    co.api.close.assert_awaited_once()
    assert task.done() and co._listening_task is None
    assert co.audio_commands is None and co.audio_metadata is None
    assert entry.entry_id not in hass.data['loxone']
    assert hass.data['loxone'][second.entry_id] is second_co
    assert not second_co._listening_task.done()
    second_co.api.close.assert_not_awaited()
    assert hass.services.has_service('loxone','event_websocket_command')
    assert len(audio_setup.closed)==1
