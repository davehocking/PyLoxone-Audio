"""Independent review regressions: real HA, synthetic I/O, no household access."""
# ruff: noqa: S101, SLF001, INP001, F811, F401, PLR2004
from __future__ import annotations
import asyncio
import json
from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from aiohttp import ClientError
from homeassistant.exceptions import HomeAssistantError

from test_audioserver_ha import audio_setup
from test_native_source_return_ha import install_sources, library_row, RADIO, PARENT
from test_source_simple_session_ha import session_room
from custom_components.loxone.pyloxone_api import audioserver as wire


@pytest.mark.asyncio
@pytest.mark.parametrize('bad', ['missing', 'unsupported', 'paused'])
async def test_incomplete_or_paused_only_item_cannot_replace_confirmed_a1(hass, audio_setup, monkeypatch, bad):
    entity, emit, _writes = await install_sources(hass, audio_setup, monkeypatch)
    await emit(library_row())
    a1 = entity._radio_catalogue.source_session('Local Library')
    changes = {'audiopath': None} if bad == 'missing' else {'audiopath': 'library:local:folder:not-track'} if bad == 'unsupported' else {'audiopath': 'library:local:track:paused-only', 'mode': 'pause', 'time': 12}
    await emit(library_row(**changes))
    assert entity._radio_catalogue.source_session('Local Library') is a1


@pytest.mark.asyncio
@pytest.mark.parametrize('missing', ['prefix', 'network'])
async def test_unusable_optional_parent_does_not_prevent_exact_item_start(hass, audio_setup, monkeypatch, missing):
    entity, emit, writes = await install_sources(hass, audio_setup, monkeypatch)
    await emit(library_row(parent={'id': 'unexpected:context'} if missing == 'prefix' else {'id': PARENT}))
    await emit({'playerid': 7, 'mode': 'play', 'eventype': 0, 'audiopath': RADIO})
    folder = wire.AudioServerCommands.async_media_folder
    async def broken(client, service, account, path, offset):
        if path == PARENT:
            raise ClientError('Synthetic optional folder unavailable')
        return await folder(client, service, account, path, offset)
    monkeypatch.setattr(wire.AudioServerCommands, 'async_media_folder', broken)
    await hass.services.async_call('media_player', 'select_source', {'entity_id': entity.entity_id, 'source': 'Local Library'}, blocking=True)
    assert writes[0] == 'audio/7/library/play/library%3Alocal%3Atrack%3Afive'


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['source', 'seek'])
async def test_stop_is_ordered_after_dispatched_transport_cleanup(hass, audio_setup, monkeypatch, action):
    entity, emit, writes = await install_sources(hass, audio_setup, monkeypatch, spotify=True, previous_spotify=True)
    await emit(library_row())
    entered, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    bus = []
    from custom_components.loxone.const import SENDDOMAIN
    hass.bus.async_listen(SENDDOMAIN, lambda event: bus.append(event.data))
    original = wire.AudioServerCommands._async_request
    async def request(client, command, key, *, is_current, on_send, **kwargs):
        assert is_current()
        on_send()
        writes.append(command)
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            closing.set()
            await release.wait()
    monkeypatch.setattr(wire.AudioServerCommands, '_async_request', request)
    name = 'select_source' if action == 'source' else 'media_seek'
    data = {'source': 'Spotify'} if action == 'source' else {'seek_position': 80}
    old = asyncio.create_task(hass.services.async_call('media_player', name, {'entity_id': entity.entity_id, **data}, blocking=True))
    stop = None
    try:
        await asyncio.wait_for(entered.wait(), 1)
        stop = asyncio.create_task(hass.services.async_call('media_player', 'media_stop', {'entity_id': entity.entity_id}, blocking=True))
        await asyncio.wait_for(closing.wait(), 1)
        for _ in range(6):
            await asyncio.sleep(0)
        assert bus == [] and not stop.done(), 'Stop may not overtake an outstanding source/seek'
        release.set()
        await asyncio.wait_for(stop, 2)
        await asyncio.gather(old, return_exceptions=True)
        await hass.async_block_till_done()
        assert len(bus) == 1 and bus[0]['value'] == 'pause'
        assert len(writes) == 1 and entity._source_task is None
    finally:
        release.set()
        for task in (old, stop):
            if task:
                task.cancel()
        await asyncio.gather(*(task for task in (old, stop) if task), return_exceptions=True)


@pytest.mark.asyncio
async def test_new_source_supersedes_seek_without_seek_finally_clearing_new_owner(hass, audio_setup, monkeypatch):
    entity, emit, writes = await install_sources(hass, audio_setup, monkeypatch, spotify=True, previous_spotify=True)
    await emit(library_row())
    entered, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original = wire.AudioServerCommands._async_request
    async def request(client, command, key, **kwargs):
        if '/position/' in command:
            kwargs['on_send']()
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                closing.set()
                await release.wait()
        return await original(client, command, key, **kwargs)
    monkeypatch.setattr(wire.AudioServerCommands, '_async_request', request)
    old = asyncio.create_task(hass.services.async_call('media_player', 'media_seek', {'entity_id': entity.entity_id, 'seek_position': 80}, blocking=True))
    new = None
    try:
        await asyncio.wait_for(entered.wait(), 1)
        new = asyncio.create_task(hass.services.async_call('media_player', 'select_source', {'entity_id': entity.entity_id, 'source': 'Spotify'}, blocking=True))
        await asyncio.wait_for(closing.wait(), 1)
        assert not new.done()
        release.set()
        await asyncio.wait_for(new, 2)
        assert isinstance((await asyncio.gather(old, return_exceptions=True))[0], asyncio.CancelledError)
        assert entity._audio_metadata.get(7).source == 'Spotify'
        assert entity._source_task is None
    finally:
        release.set()
        for task in (old, new):
            if task:
                task.cancel()
        await asyncio.gather(*(task for task in (old, new) if task), return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('optional', ['absent', 'unavailable', 'read-error'])
async def test_paused_exact_native_spotify_resume_never_replaces_item_or_queue(hass, audio_setup, monkeypatch, optional):
    entity, emit, writes, session, spotify = await session_room(hass, audio_setup, monkeypatch)
    await emit({**spotify, 'mode': 'pause'})
    if optional == 'absent':
        assert not hasattr(entity, '_spotify_return')
    else:
        async def unavailable(*args, **kwargs):
            raise ClientError('Unrelated HA Spotify must never be consulted')
        monkeypatch.setattr(session, 'async_request', unavailable)
    async def request(client, command, key, *, is_current, on_send, **kwargs):
        assert is_current()
        on_send()
        writes.append(command)
        assert command == 'audio/7/serviceplay/spotify/synthetic-account/'
        asyncio.get_running_loop().call_soon(audio_setup.queues[0].put_nowait, json.dumps({'audio_event': [spotify]}))
    monkeypatch.setattr(wire.AudioServerCommands, '_async_request', request)
    await hass.services.async_call('media_player', 'select_source', {'entity_id': entity.entity_id, 'source': 'Spotify'}, blocking=True)
    assert writes == ['audio/7/serviceplay/spotify/synthetic-account/']
    assert entity._audio_metadata.get(7).native_mode == 'play'


@pytest.mark.asyncio
async def test_confirmed_newer_provider_session_is_last_good_before_immediate_departure(hass, audio_setup, monkeypatch):
    entity, emit, writes, session, spotify = await session_room(hass, audio_setup, monkeypatch)
    current = 'spotify:track:' + 'Z' * 22
    context = 'spotify:playlist:' + 'Y' * 22
    session.current['item']['uri'] = current
    session.current['context'] = {'uri': context}
    original = wire.AudioServerCommands._async_request
    async def request(client, command, key, *, is_current, on_send, **kwargs):
        if '/serviceplay/spotify/' in command:
            assert is_current()
            on_send()
            writes.append(command)
            asyncio.get_running_loop().call_soon(audio_setup.queues[0].put_nowait, json.dumps({'audio_event': [{**spotify, 'audiopath': current, 'parent': {'id': context}}]}))
        else:
            return await original(client, command, key, is_current=is_current, on_send=on_send, **kwargs)
    monkeypatch.setattr(wire.AudioServerCommands, '_async_request', request)
    previous = entity._radio_catalogue.source_session('Spotify')
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call('media_player', 'select_source', {'entity_id': entity.entity_id, 'source': 'Spotify'}, blocking=True)
    assert entity._radio_catalogue.source_session('Spotify') is previous
    # A wrong return is not success; later independently corroborated playback
    # of a different item remains eligible under the ordinary passive rule.
    independent = {**spotify, 'audiopath': current + '-independent', 'parent': {'id': context}}
    await emit(independent)
    await emit({**independent, 'time': independent['time'] + 1})
    current = independent['audiopath']
    assert entity._radio_catalogue.source_session('Spotify').audio_path == current
    await hass.services.async_call('media_player', 'select_source', {'entity_id': entity.entity_id, 'source': 'Local Library'}, blocking=True)
    session.current = None
    media_id = await entity._radio_catalogue.async_source_return('Spotify')
    target = entity._radio_catalogue.resolve(media_id)
    assert target.audio_path == current


@pytest.mark.asyncio
async def test_two_old_timestamp_frames_cannot_overwrite_newer_any_app_success(hass, audio_setup, monkeypatch):
    entity, emit, _writes = await install_sources(hass, audio_setup, monkeypatch)
    await emit(library_row(audiopath='library:local:track:A3'))
    saved = entity._radio_catalogue.source_session('Local Library')
    from datetime import timedelta
    for index in (2, 1):
        old = replace(saved, audio_path='library:local:track:A2', position=20-index, received_at=saved.received_at-timedelta(seconds=index))
        entity._audio_metadata._client._receiver._metadata[7] = old
        entity._update_audio_metadata()
    assert entity._radio_catalogue.source_session('Local Library') is saved
    await emit(library_row(audiopath='library:local:track:external', time=12))
    await emit(library_row(audiopath='library:local:track:external', time=13))
    assert entity._radio_catalogue.source_session('Local Library').audio_path == 'library:local:track:external'
