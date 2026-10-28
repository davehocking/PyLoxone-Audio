"""Actual HA return after qualified external native visits; no HA-started content."""
import asyncio
import json
from unittest.mock import AsyncMock
from urllib.parse import unquote
import pytest
from test_audioserver_ha import audio_setup, zone_entity_id
from test_native_source_return_ha import install_sources, library_row, RADIO
from custom_components.loxone.pyloxone_api import audioserver as wire


@pytest.mark.asyncio
@pytest.mark.parametrize('service,label', [('library', 'Local Library'), ('spotify', 'Spotify'), ('radio', 'TuneIn')])
@pytest.mark.parametrize('history_outage', [False, True])
async def test_external_only_visit_returns_through_actual_service_without_recent_fallback(hass, audio_setup, monkeypatch, service, label, history_outage):
    entity, emit, writes = await install_sources(hass, audio_setup, monkeypatch, spotify=True)
    history = AsyncMock(return_value={'items': []})
    monkeypatch.setattr(wire.AudioServerCommands, 'async_recent_sources', history)
    await entity._async_refresh_native_sources()
    assert not entity.source_list and not entity._radio_catalogue.source_sessions
    row = library_row(time=0)
    if service == 'spotify':
        row.update(audiopath='spotify:track:original', parent={'id': 'spotify:playlist:original'}, sourceName='Synthetic owner')
    elif service == 'radio':
        row = {'playerid': 7, 'audiopath': RADIO, 'mode': 'play', 'eventype': 0}
    await emit(row)
    await emit({**row, 'title': 'Ordinary native metadata update'})
    assert label in entity.source_list
    assert writes == [] and entity._source_generation == 0
    await emit(library_row(audiopath='library:local:track:away', time=0) if service == 'radio' else {
        'playerid': 7, 'audiopath': RADIO, 'mode': 'play', 'eventype': 0,
    })
    if service == 'radio':
        async def radio(client, player, provider, path, *, is_current, on_send):
            assert player == 7 and path == RADIO and is_current()
            on_send()
            writes.append('audio/7/radio/' + path)
            asyncio.get_running_loop().call_soon(audio_setup.queues[0].put_nowait, json.dumps({'audio_event': [row]}))
        monkeypatch.setattr(wire.AudioServerCommands, 'async_play_radio_station', radio)
    if history_outage:
        history.side_effect = TimeoutError('Synthetic unavailable room history')
    await hass.services.async_call('media_player', 'select_source', {
        'entity_id': entity.entity_id, 'source': label,
    }, blocking=True)
    assert len(writes) == 1
    assert row['audiopath'] in unquote(writes[0])
    if service == 'spotify': assert '/serviceplay/spotify/synthetic-account/' in writes[0]
    confirmed = entity._audio_metadata.get(7)
    assert confirmed.audio_path == row['audiopath'] and confirmed.native_mode == 'play'
    assert entity.source == label and not entity._audio_commands.source_fences


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['missing-path', 'missing-user', 'ambiguous-user', 'other-room', 'phone-only', 'label-only'])
async def test_insufficient_external_identity_never_advertises_spotify(hass, audio_setup, monkeypatch, case):
    entity, emit, writes = await install_sources(hass, audio_setup, monkeypatch, spotify=True)
    monkeypatch.setattr(wire.AudioServerCommands, 'async_recent_sources', AsyncMock(return_value={'items': []}))
    await entity._async_refresh_native_sources()
    row = library_row(audiopath='spotify:track:original', parent={'id': 'spotify:playlist:original'}, sourceName='Synthetic owner', time=0)
    if case == 'missing-path': row.pop('audiopath')
    if case in {'missing-user', 'label-only'}: row.pop('sourceName')
    if case == 'label-only': row = {'playerid': 7, 'source': 'Spotify', 'title': 'A provider label', 'mode': 'play', 'eventype': 0}
    if case == 'other-room': row['playerid'] = 8
    if case == 'ambiguous-user':
        monkeypatch.setattr(wire.AudioServerCommands, 'async_service_accounts', AsyncMock(return_value=[
            {'cmd': 'spotify', 'id': name, 'user': 'Synthetic owner', 'name': name, 'configerror': False}
            for name in ['synthetic-account', 'another-account']
        ]))
        await entity._async_refresh_native_sources()
    if case != 'phone-only': await emit(row)
    assert not any(label.startswith('Spotify') for label in entity.source_list or [])
    assert not any(key.service == 'spotify' for key in entity._radio_catalogue.source_sessions)
    assert writes == []


@pytest.mark.asyncio
async def test_exact_input_remains_last_when_optional_history_is_unavailable(hass, audio_setup, monkeypatch):
    from test_configured_sources import configured_commands
    commands = configured_commands()
    commands.async_recent_sources.side_effect = TimeoutError('Synthetic history outage')
    for name, value in vars(commands).items(): monkeypatch.setattr(wire.AudioServerCommands, name, value)
    await audio_setup.setup(playback=True)
    entity = hass.data['media_player'].get_entity(zone_entity_id(hass, 7))
    assert entity.source_list == ['Line-In']
