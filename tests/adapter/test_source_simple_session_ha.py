"""Agreed native session and any-app memory via real HA, synthetic boundaries."""
# ruff: noqa: S101, SLF001, INP001, F811, F401, PLR2004
from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError

from test_audioserver_ha import audio_setup
from test_native_source_return_ha import install_sources, library_row, RADIO, TRACK as LIBRARY
from test_spotify_continuity import Session, native, CONFIG, TRACK, CONTEXT
from custom_components.loxone.pyloxone_api import audioserver as wire



async def session_room(hass: Any, audio_setup: Any, monkeypatch: Any) -> Any:
    entity, emit, writes = await install_sources(hass, audio_setup, monkeypatch, spotify=True)
    session = Session([native()])
    session.current['is_playing'] = False
    provider = SimpleNamespace(domain='spotify', unique_id=CONFIG['user_id'], entry_id=CONFIG['entry_id'],
                               state=ConfigEntryState.LOADED, runtime_data=SimpleNamespace(session=session))
    get = hass.config_entries.async_get_entry
    monkeypatch.setattr(hass.config_entries, 'async_get_entry', lambda key: provider if key == provider.entry_id else get(key))

    spotify = library_row(audiopath=TRACK, parent={'id': CONTEXT}, sourceName='Synthetic owner')
    await emit(library_row())
    await emit(spotify)
    await emit({'playerid': 7, 'mode': 'play', 'eventype': 0, 'audiopath': RADIO})
    return entity, emit, writes, session, spotify


@pytest.mark.asyncio
async def test_any_app_new_playback_after_settled_ha_updates_memory_without_permanent_target_pin(hass, audio_setup, monkeypatch):
    entity, emit, writes = await install_sources(hass, audio_setup, monkeypatch, spotify=True, previous_spotify=True)
    await emit(library_row())
    await hass.services.async_call('media_player', 'select_source', {'entity_id': entity.entity_id, 'source': 'Spotify'}, blocking=True)
    before = entity._radio_catalogue.source_session('Local Library')
    external = library_row(audiopath='library:local:track:external', time=12)
    await emit(external)
    assert entity._radio_catalogue.source_session('Local Library') is before, 'One unexpected frame is not corroborated playback'
    await emit({**external, 'time': 13})
    assert entity._radio_catalogue.source_session('Local Library').audio_path == external['audiopath']
    assert entity._radio_catalogue.source_session('Local Library').position == 13
    assert len(writes) == 1, 'Passive memory must not issue any command'


@pytest.mark.asyncio
async def test_valid_native_spotify_session_resumes_empty_path_without_capture_queue_or_replacement(hass, audio_setup, monkeypatch):
    entity, emit, writes, session, spotify = await session_room(hass, audio_setup, monkeypatch)
    # Native paused room metadata, not HA provider state, authorises resume.
    await emit({**spotify, 'mode': 'pause'})
    session.current['item']['uri'] = 'spotify:track:' + 'Z' * 22  # Newer valid session beats remembered TRACK.
    session.current['progress_ms'] = 67000
    queue = deepcopy(session.queue)
    received = asyncio.Event()
    release = asyncio.Event()
    async def request(client, command, key, *, is_current, on_send, **kwargs):
        assert is_current()
        on_send()
        writes.append(command)
        received.set()
        await release.wait()
        assert is_current()
        row = {**spotify, 'audiopath': session.current['item']['uri'], 'time': 67}
        audio_setup.queues[0].put_nowait(json.dumps({'audio_event': [row]}))
    monkeypatch.setattr(wire.AudioServerCommands, '_async_request', request)
    action = asyncio.create_task(hass.services.async_call('media_player', 'select_source', {'entity_id': entity.entity_id, 'source': 'Spotify'}, blocking=True))
    try:
        await asyncio.wait_for(received.wait(), 1)
        assert writes == ['audio/7/serviceplay/spotify/synthetic-account/']
        assert not action.done(), 'Send is not playback confirmation'
        release.set()
        await asyncio.wait_for(action, 2)
        assert session.queue == queue
        assert all(method == 'GET' and not url.endswith('/queue') for method, url, _ in session.calls)
        assert entity._audio_metadata.get(7).position == 67
        assert not entity._audio_commands.source_fences
    finally:
        release.set()
        action.cancel()
        await asyncio.gather(action, return_exceptions=True)




@pytest.mark.asyncio
async def test_last_good_exact_item_is_returnable_when_prior_parent_listing_unavailable(hass, audio_setup, monkeypatch):
    entity, emit, writes = await install_sources(hass, audio_setup, monkeypatch)
    await emit(library_row())
    await emit({'playerid': 7, 'mode': 'play', 'eventype': 0, 'audiopath': RADIO})
    folder = wire.AudioServerCommands.async_media_folder
    async def missing(client, service, account, path, offset):
        if path == 'library:local:folder:album':
            raise wire.AudioCommandError('Synthetic context no longer available')
        return await folder(client, service, account, path, offset)
    monkeypatch.setattr(wire.AudioServerCommands, 'async_media_folder', missing)
    await hass.services.async_call('media_player', 'select_source', {'entity_id': entity.entity_id, 'source': 'Local Library'}, blocking=True)
    assert writes[0] == 'audio/7/library/play/library%3Alocal%3Atrack%3Afive'
    assert entity._radio_catalogue.source_session('Local Library').audio_path == LIBRARY
