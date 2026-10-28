"""Room-scoped previous sources via real HA, never Browse-folder history alone."""
import json
from unittest.mock import AsyncMock
import pytest
from homeassistant.exceptions import HomeAssistantError
from test_audioserver_ha import audio_setup, zone_entity_id
from test_native_source_return_ha import install_sources, library_row, RADIO
from custom_components.loxone.audio_radio import RADIO_MEDIA_TYPE
from custom_components.loxone.pyloxone_api import audioserver as wire


@pytest.mark.asyncio
async def test_browse_folder_history_and_folder_visits_do_not_advertise_previous_content(hass, audio_setup, monkeypatch):
    entity, _emit, writes = await install_sources(hass, audio_setup, monkeypatch, spotify=True)
    assert not entity.source_list, 'Configured presence and recent folders are not previous playable content'
    root = await entity.async_browse_media()
    assert any(item.title == 'Radio' for item in root.children)
    for child in root.children:
        if child.title in {'Local Library', 'Spotify'}:
            await entity.async_browse_media(child.media_content_type, child.media_content_id)
    assert not entity.source_list
    assert writes == []
    assert not entity._radio_catalogue.source_sessions


@pytest.mark.asyncio
@pytest.mark.parametrize('service', ['library', 'spotify', 'radio'])
async def test_external_native_playback_populates_only_its_room_without_ha_play_request(hass, audio_setup, monkeypatch, service):
    entity, emit, writes = await install_sources(hass, audio_setup, monkeypatch, spotify=True)
    other = hass.data['media_player'].get_entity(zone_entity_id(hass, 8))
    row = library_row()
    label = 'Local Library'
    if service == 'spotify':
        row.update(audiopath='spotify:track:external', parent={'id': 'spotify:playlist:external'}, sourceName='Synthetic owner')
        label = 'Spotify'
    elif service == 'radio':
        row = {'playerid': 7, 'audiopath': RADIO, 'mode': 'play', 'eventype': 0}
        label = 'TuneIn'
    await emit(row)
    assert entity.source_list == [label]
    assert not other.source_list
    assert writes == []
    await entity.async_browse_media()
    await entity._async_refresh_native_sources()
    assert entity.source_list == [label]
    assert entity._radio_catalogue.source_session(label).audio_path == row['audiopath']


@pytest.mark.asyncio
async def test_room_recent_concrete_station_is_usable_but_another_rooms_history_is_not(hass, audio_setup, monkeypatch):
    entity, _emit, writes = await install_sources(hass, audio_setup, monkeypatch)
    other = hass.data['media_player'].get_entity(zone_entity_id(hass, 8))
    async def history(client, player):
        return {'items': [{'type': 2, 'audiopath': RADIO, 'title': 'Selected room station'}] if player == 7 else []}
    monkeypatch.setattr(wire.AudioServerCommands, 'async_recent_sources', history)
    await entity._async_refresh_native_sources()
    await other._async_refresh_native_sources()
    assert entity.source_list == ['TuneIn']
    assert not other.source_list
    assert writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize('source,guide', [('TuneIn', 'Browse media > Radio'), ('Local Library', 'Browse media > Local Library'), ('Spotify', 'Browse media > Spotify')])
async def test_first_use_errors_explain_actual_browse_location_without_dispatch(hass, audio_setup, monkeypatch, source, guide):
    entity, _emit, writes = await install_sources(hass, audio_setup, monkeypatch, spotify=True)
    monkeypatch.setattr(wire.AudioServerCommands, 'async_player_status', AsyncMock(return_value=wire.parse_audio_events({'audio_event': [{'playerid': 7, 'mode': 'stop', 'eventype': 0}]})[0]))
    with pytest.raises(HomeAssistantError) as error:
        await hass.services.async_call('media_player', 'select_source', {
            'entity_id': entity.entity_id, 'source': source,
        }, blocking=True)
    assert guide in str(error.value)
    assert 'play' in str(error.value).lower()
    assert writes == []
    assert not entity.source_list
