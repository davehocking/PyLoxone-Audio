"""Concrete REVIEW03 gaps; real HA entity, synthetic owned task cleanup."""
# ruff: noqa: S101, SLF001, INP001, F811, F401, ANN001, D103
from __future__ import annotations
import asyncio

import pytest
from custom_components.loxone import LoxoneEntity
from dataclasses import replace
from datetime import timedelta
from test_native_source_return_ha import install_sources, library_row, RADIO
from custom_components.loxone.pyloxone_api import audioserver as wire
from unittest.mock import AsyncMock
from test_audioserver_ha import audio_setup
from test_source_simple_session_ha import session_room


@pytest.mark.asyncio
@pytest.mark.parametrize('first_role',['discovery','transport'])
async def test_repeated_unload_cancellation_waits_all_owned_tasks_and_superclass(hass,audio_setup,monkeypatch,first_role):
    entity, _emit, _writes, _session, _spotify = await session_room(hass,audio_setup,monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    roles, closed = {}, []
    ready=[]
    async def owned():
        ready.append(asyncio.current_task())
        try:
            await asyncio.Event().wait()
        finally:
            entered.set()
            await release.wait()
            closed.append(roles[asyncio.current_task()])
    tasks=[asyncio.create_task(owned()),asyncio.create_task(owned())]
    while len(ready)!=2:
        await asyncio.sleep(0)
    # Pick the exact iteration order of the implementation's deduplicated set,
    # assigning roles afterward to exercise BOTH orders without scheduler luck.
    ordered=[task for task in {*tasks,None} if task is not None]
    roles[ordered[0]]=first_role
    roles[ordered[1]]='transport' if first_role=='discovery' else 'discovery'
    discovery=next(task for task,role in roles.items() if role=='discovery')
    transport=next(task for task,role in roles.items() if role=='transport')
    entity._discovery_tasks.add(discovery)
    entity._transport_tasks.add(transport)
    entity._source_task=transport
    removed=[]
    original=LoxoneEntity.async_will_remove_from_hass
    async def removal(self):
        if self is entity:
            assert all(task.done() for task in tasks)
            removed.append(True)
        await original(self)
    monkeypatch.setattr(LoxoneEntity,'async_will_remove_from_hass',removal)
    unload=asyncio.create_task(entity.async_will_remove_from_hass())
    try:
        await asyncio.wait_for(entered.wait(),1)
        for _ in range(3):
            unload.cancel()
            await asyncio.sleep(0)
            assert not unload.done()
        release.set()
        result=await asyncio.gather(unload,return_exceptions=True)
        assert isinstance(result[0],asyncio.CancelledError)
        assert all(task.done() for task in tasks), 'Unload cancellation detached a remaining owned task'
        assert set(closed)=={'discovery','transport'}
        assert removed==[True], 'Superclass removal was skipped'
    finally:
        release.set()
        for task in [*tasks,unload]:
            task.cancel()
        await asyncio.gather(*tasks,unload,return_exceptions=True)
        entity._source_task=None
        entity._discovery_tasks.discard(discovery)
        entity._transport_tasks.discard(transport)


@pytest.mark.asyncio
async def test_settled_same_successful_item_keeps_corrected_pause_position(hass, audio_setup, monkeypatch):
    entity, emit, writes = await install_sources(hass, audio_setup, monkeypatch)
    await emit(library_row())
    # An ordinary completed HA action must not permanently veto enrichment.
    await hass.services.async_call('media_player', 'select_source',
        {'entity_id': entity.entity_id, 'source': 'Local Library'}, blocking=True)
    await emit(library_row(time=46))
    await emit(library_row(time=47))
    await emit(library_row(mode='pause', time=52))
    assert entity._radio_catalogue.source_session('Local Library').position == 52
    await emit(library_row(mode='pause', time=80, audiopath='library:local:track:never-played'))
    assert entity._radio_catalogue.source_session('Local Library').audio_path == library_row()['audiopath']
    await emit({'playerid': 7, 'mode': 'play', 'eventype': 0, 'audiopath': RADIO})
    writes.clear()
    await hass.services.async_call('media_player', 'select_source',
        {'entity_id': entity.entity_id, 'source': 'Local Library'}, blocking=True)
    assert 'audio/7/position/52.0' in writes


@pytest.mark.asyncio
async def test_radio_retains_newest_success_despite_older_qualified_pair(hass, audio_setup, monkeypatch):
    entity, emit, writes = await install_sources(hass, audio_setup, monkeypatch)
    # Use real source confirmation while limiting transport replacement to this
    # unrelated Library action; radio return below is resolved by the catalogue.
    await emit(library_row())
    await hass.services.async_call('media_player', 'select_source',
        {'entity_id': entity.entity_id, 'source': 'Local Library'}, blocking=True)
    await emit({'playerid':7,'mode':'play','eventype':0,'audiopath':'tunein:station:A3'})
    await emit({'playerid':7,'mode':'play','eventype':0,'audiopath':'tunein:station:A3'})
    saved = entity._audio_metadata.get(7)
    assert entity._radio_catalogue.source_choices['TuneIn'].audio_path == 'tunein:station:A3'
    for offset in (2, 1):
        old = replace(saved, audio_path='tunein:station:A2', received_at=saved.received_at-timedelta(seconds=offset))
        entity._audio_metadata._client._receiver._metadata[7] = old
        entity._update_audio_metadata()
    assert entity._radio_catalogue.source_choices['TuneIn'].audio_path == 'tunein:station:A3'
    media_id = await entity._radio_catalogue.async_source_return('TuneIn')
    assert entity._radio_catalogue.resolve(media_id).audio_path == 'tunein:station:A3'
    for offset in (1, 2):
        newer = replace(saved, audio_path='tunein:station:A4', received_at=saved.received_at+timedelta(seconds=offset))
        entity._audio_metadata._client._receiver._metadata[7] = newer
        entity._update_audio_metadata()
    assert entity._radio_catalogue.source_choices['TuneIn'].audio_path == 'tunein:station:A4'
