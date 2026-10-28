"""Unchanged ownership/no-replay guarantees on the simplified real HA path."""
# ruff: noqa: S101, SLF001, INP001, F811, F401, PLR2004
from __future__ import annotations
import asyncio
import json
from copy import deepcopy
from urllib.parse import unquote
from typing import Any

import pytest
from homeassistant.exceptions import HomeAssistantError

from test_audioserver_ha import audio_setup
from test_source_simple_session_ha import session_room
from test_native_source_return_ha import library_row, RADIO, TRACK as LIBRARY, PARENT
from custom_components.loxone.pyloxone_api import audioserver as wire


@pytest.mark.asyncio
@pytest.mark.parametrize('conflict', ['device', 'profile', 'native-account'])
async def test_native_session_return_preserves_foreign_identity_rejection(hass, audio_setup, monkeypatch, conflict):
    entity, _emit, writes, session, _row = await session_room(hass, audio_setup, monkeypatch)
    if conflict == 'device':
        session.current['device']['id'] = 'e' * 40
    elif conflict == 'profile':
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        request = session.async_request
        async def foreign_profile(method, url, **kwargs):
            if url.endswith('/me'):
                return SimpleNamespace(status=200, json=AsyncMock(return_value={'id': 'foreign-owner'}), release=lambda: None)
            return await request(method, url, **kwargs)
        monkeypatch.setattr(session, 'async_request', foreign_profile)
    else:
        async def accounts():
            return [{'cmd': 'spotify', 'id': 'synthetic-account', 'user': 'different-native-user', 'configerror': True}]
        monkeypatch.setattr(entity._audio_commands, 'async_service_accounts', accounts)
    if conflict == 'native-account':
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call('media_player', 'select_source', {'entity_id': entity.entity_id, 'source': 'Spotify'}, blocking=True)
        assert writes == []
    else:
        await hass.services.async_call('media_player', 'select_source', {'entity_id': entity.entity_id, 'source': 'Spotify'}, blocking=True)
        assert writes and _row['audiopath'].replace(':', '%3A') in writes[0]
    assert session.calls == [], 'Unrelated HA receiver/profile is not native room authority'
    assert all(method == 'GET' for method, _, _ in session.calls)




@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['error', 'cancel'])
async def test_ambiguous_native_resume_is_not_replayed_and_new_other_source_can_proceed(hass, audio_setup, monkeypatch, failure):
    entity, _emit, writes, session, _row = await session_room(hass, audio_setup, monkeypatch)
    original = wire.AudioServerCommands._async_request
    async def request(client, command, key, *, is_current, on_send, **kwargs):
        if '/serviceplay/spotify/' in command:
            assert is_current()
            on_send()
            writes.append(command)
            if failure == 'cancel':
                raise asyncio.CancelledError
            raise wire.AudioCommandError('Synthetic sent-but-unconfirmed handoff')
        return await original(client, command, key, is_current=is_current, on_send=on_send, **kwargs)
    monkeypatch.setattr(wire.AudioServerCommands, '_async_request', request)
    with pytest.raises((HomeAssistantError, asyncio.CancelledError)):
        await hass.services.async_call('media_player', 'select_source', {'entity_id': entity.entity_id, 'source': 'Spotify'}, blocking=True)
    assert writes == ['audio/7/serviceplay/spotify/synthetic-account/' + _row['audiopath'].replace(':', '%3A') + '/noshuffle']
    assert 7 in entity._audio_commands.source_fences
    assert entity._source_task is None
    await hass.services.async_call('media_player', 'select_source', {'entity_id': entity.entity_id, 'source': 'Local Library'}, blocking=True)
    assert len([command for command in writes if '/serviceplay/spotify/' in command]) == 1
    assert entity._audio_metadata.get(7).source == 'Local Library'
    assert not entity._audio_commands.source_fences


@pytest.mark.asyncio
@pytest.mark.parametrize('away', ['Local Library', 'TuneIn'])
async def test_repeated_native_spotify_returns_leave_queue_and_position_to_spotify(hass, audio_setup, monkeypatch, away):
    entity, _emit, writes, session, spotify = await session_room(hass, audio_setup, monkeypatch)
    original_queue = deepcopy(session.queue)
    if away == 'TuneIn':
        entity._audio_commands.async_recent_sources.return_value['items'].append({'type': 2, 'audiopath': RADIO, 'title': 'Synthetic station'})
    async def request(client, command, key, *, is_current, on_send, **kwargs):
        assert is_current()
        if on_send is not None:
            on_send()
        writes.append(command)
        bits = command.split('/')
        if bits[2:4] == ['serviceplay', 'spotify']:
            assert unquote(bits[5]) == spotify['audiopath'], 'Return exact room content, never unrelated HA Spotify content'
            row = {**spotify, 'time': 0}
            session.current['is_playing'] = True
        elif bits[2:4] == ['serviceplay', 'radio']:
            row = {'playerid': 7, 'mode': 'play', 'eventype': 0, 'audiopath': RADIO}
            session.current['is_playing'] = False
        elif bits[2:4] == ['library', 'play']:
            # A native folder selection reports the resulting track, not a playing folder.
            selected = unquote(bits[4])
            row = library_row(audiopath=selected if ":track:" in selected else LIBRARY, time=0)
            session.current['is_playing'] = False
        elif bits[2] == 'position':
            snapshot = entity._audio_metadata.get(7)
            row = library_row(audiopath=snapshot.audio_path, parent={'id': snapshot.parent_id}, sourceName=snapshot.source_name, time=float(bits[3]))
        else:
            raise AssertionError(command)
        asyncio.get_running_loop().call_soon(audio_setup.queues[0].put_nowait, json.dumps({'audio_event': [row]}))
        if bits[2] == 'position':
            return [{'position': float(bits[3])}]
    monkeypatch.setattr(wire.AudioServerCommands, '_async_request', request)
    for _ in range(3):
        await hass.services.async_call('media_player', 'select_source', {'entity_id': entity.entity_id, 'source': 'Spotify'}, blocking=True)
        await hass.services.async_call('media_player', 'select_source', {'entity_id': entity.entity_id, 'source': away}, blocking=True)
    assert sum('/serviceplay/spotify/' in command for command in writes) == 3
    assert session.queue == original_queue
    assert all(method == 'GET' and not url.endswith('/queue') for method, url, _ in session.calls)
    assert entity._source_task is None
    assert not entity._audio_commands.source_fences
    assert not hasattr(entity, '_spotify_return')
