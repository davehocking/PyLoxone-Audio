"""Second review's concrete regressions on existing HA entities and boundaries."""
# ruff: noqa: S101, SLF001, INP001, F811, F401, PLR2004
from __future__ import annotations
import asyncio
import json
from dataclasses import replace
from datetime import timedelta

import pytest
from homeassistant.exceptions import HomeAssistantError
from test_audioserver_ha import audio_setup
from test_native_source_return_ha import install_sources, library_row
from test_source_simple_session_ha import session_room
from custom_components.loxone.audio_catalogue import CatalogueTarget
from custom_components.loxone.audio_radio import RADIO_MEDIA_TYPE
from custom_components.loxone.pyloxone_api import audioserver as wire


@pytest.mark.asyncio
@pytest.mark.parametrize('bad', ['empty-library', 'empty-spotify', 'cross-library', 'cross-spotify'])
async def test_malformed_source_item_does_not_poison_either_last_success_or_choice(hass, audio_setup, monkeypatch, bad):
    entity, emit, _writes, _session, spotify = await session_room(hass, audio_setup, monkeypatch)
    await emit(library_row())
    source = 'Spotify' if bad.endswith('spotify') else 'Local Library'
    saved = entity._radio_catalogue.source_session(source)
    sessions = dict(entity._radio_catalogue.source_sessions)
    choices = dict(entity._radio_catalogue.source_choices)
    paths = {'empty-library':'library:local:track:', 'empty-spotify':'spotify:track:', 'cross-library':spotify['audiopath'], 'cross-spotify':'library:local:track:five'}
    malformed = replace(saved, audio_path=paths[bad], received_at=saved.received_at + timedelta(seconds=1))
    entity._radio_catalogue.remember_source(malformed)
    assert entity._radio_catalogue.source_sessions == sessions
    assert entity._radio_catalogue.source_choices == choices
    media = await entity._radio_catalogue.async_source_return(source)
    assert entity._radio_catalogue.resolve(media).audio_path == saved.audio_path


@pytest.mark.asyncio
async def test_paused_native_same_track_foreign_user_is_not_confirmation(hass, audio_setup, monkeypatch):
    entity, emit, writes, _session, spotify = await session_room(hass, audio_setup, monkeypatch)
    await emit({**spotify, 'mode':'pause'})

    sent = asyncio.Event()
    async def request(client, command, key, *, is_current, on_send, **kwargs):
        assert is_current()
        on_send()
        writes.append(command)
        sent.set()
    monkeypatch.setattr(wire.AudioServerCommands, '_async_request', request)
    old = entity._radio_catalogue.source_session('Spotify')
    action = asyncio.create_task(hass.services.async_call('media_player','select_source',{'entity_id':entity.entity_id,'source':'Spotify'},blocking=True))
    try:
        await asyncio.wait_for(sent.wait(), 1)
        seen = asyncio.Event()
        remove = entity._audio_metadata.async_add_listener(7, lambda: seen.set() if entity._audio_metadata.get(7).source_name == 'Another native account' else None)
        try:
            audio_setup.queues[0].put_nowait(json.dumps({'audio_event': [{**spotify,'sourceName':'Another native account'}]}))
            await asyncio.wait_for(seen.wait(), 1)
        finally:
            remove()
        for _ in range(5):
            await asyncio.sleep(0)
        assert not action.done(), 'Same URI from a foreign account cannot confirm a resume'
        assert entity._radio_catalogue.source_session('Spotify') is old
        audio_setup.queues[0].put_nowait(json.dumps({'audio_event': [spotify]}))
        await asyncio.wait_for(action, 2)
        assert len(writes) == 1
    finally:
        action.cancel()
        await asyncio.gather(action,return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['folder', 'search_group'])
@pytest.mark.parametrize('phase', ['waiting', 'cleanup'])
async def test_invalid_playable_kind_cannot_cancel_valid_existing_owner(hass, audio_setup, monkeypatch, kind, phase):
    entity, _emit, writes, _session, _spotify = await session_room(hass, audio_setup, monkeypatch)
    entered, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original = wire.AudioServerCommands._async_request
    if phase == 'waiting':
        accounts = entity._audio_commands.async_service_accounts
        async def waiting_accounts():
            entered.set()
            await release.wait()
            return await accounts()
        monkeypatch.setattr(entity._audio_commands, 'async_service_accounts', waiting_accounts)
    else:
        async def request(client, command, key, *, is_current, on_send, **kwargs):
            if '/serviceplay/spotify/' in command:
                on_send()
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    closing.set()
                    await release.wait()
            else:
                return await original(client,command,key,is_current=is_current,on_send=on_send,**kwargs)
        monkeypatch.setattr(wire.AudioServerCommands,'_async_request',request)
    action = asyncio.create_task(hass.services.async_call('media_player','select_source',{'entity_id':entity.entity_id,'source':'Spotify'},blocking=True))
    newer = None
    try:
        for _ in range(30):
            await asyncio.sleep(0)
            if entity._source_task is not None:
                break
        if phase == 'cleanup':
            await asyncio.wait_for(entered.wait(),1)
            newer = asyncio.create_task(hass.services.async_call('media_player','select_source',{'entity_id':entity.entity_id,'source':'Local Library'},blocking=True))
            await asyncio.wait_for(closing.wait(),1)
        owner, generation = entity._source_task, entity._source_generation
        media_id = entity._radio_catalogue._item(CatalogueTarget(kind,'Not playable','library',folder='library:local:folder:unplayable')).media_content_id
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call('media_player','play_media',{'entity_id':entity.entity_id,'media_content_type':RADIO_MEDIA_TYPE,'media_content_id':media_id},blocking=True)
        assert entity._source_generation == generation
        assert entity._source_task is owner and not owner.done()
    finally:
        release.set()

        for task in (action,newer):
            if task:
                task.cancel()
        await asyncio.gather(*(task for task in (action,newer) if task),return_exceptions=True)


@pytest.mark.asyncio
async def test_unload_repeated_cancellation_does_not_interrupt_open_transport_cleanup(hass, audio_setup, monkeypatch):
    entity, emit, _writes = await install_sources(hass,audio_setup,monkeypatch,spotify=True, previous_spotify=True)
    await emit(library_row())
    entered, closing, release, closed = asyncio.Event(), asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def request(client, command, key, *, is_current, on_send, **kwargs):
        on_send()
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            closing.set()
            await release.wait()
            closed.set()
    monkeypatch.setattr(wire.AudioServerCommands,'_async_request',request)
    action=asyncio.create_task(hass.services.async_call('media_player','select_source',{'entity_id':entity.entity_id,'source':'Spotify'},blocking=True))
    unload=None
    try:
        await asyncio.wait_for(entered.wait(),1)
        entity._source_task.cancel()
        await asyncio.wait_for(closing.wait(),1)
        unload=asyncio.create_task(entity.async_will_remove_from_hass())
        for _ in range(5):
            await asyncio.sleep(0)
        unload.cancel()
        for _ in range(5):
            await asyncio.sleep(0)
        assert not unload.done(), 'Cancelled teardown must still await owned socket cleanup'
        release.set()
        await asyncio.gather(unload,action,return_exceptions=True)
        assert closed.is_set()
        assert entity._source_task is None
    finally:
        release.set()
        for task in (action,unload):
            if task:
                task.cancel()
        await asyncio.gather(*(task for task in (action,unload) if task),return_exceptions=True)
