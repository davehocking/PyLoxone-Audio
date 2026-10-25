"""Real existing config-entry/entity path with synthetic external I/O only."""
from __future__ import annotations

import json

import pytest
from test_audioserver_ha import audio_setup, zone_entity_id

from custom_components.loxone.const import DOMAIN, EVENT


@pytest.mark.asyncio
async def test_real_source_policy_and_neutral_catalogue_convert_at_existing_ha_caller(hass, audio_setup, monkeypatch):
    from homeassistant.components.media_player import BrowseMedia, SearchMedia, SearchMediaQuery
    from custom_components.loxone import audio_sources

    await audio_setup.setup(playback=True)
    entity = hass.data['media_player'].get_entity(zone_entity_id(hass, 7))
    assert audio_sources.async_select_catalogue.__module__ == 'pyloxone_audio.sources'
    assert type(entity._radio_catalogue).__module__ == 'pyloxone_audio.catalogue'
    native = await entity._radio_catalogue.async_browse()
    assert type(native).__module__ == 'pyloxone_audio.models'
    assert not isinstance(native, BrowseMedia)
    root = await entity.async_browse_media()
    assert isinstance(root, BrowseMedia)
    assert all(isinstance(child, BrowseMedia) for child in root.children)
    assert [child.title for child in root.children] == [child.title for child in native.children]
    assert root.as_dict()['children'][0]['title'] == native.children[0].title
    from unittest.mock import AsyncMock
    monkeypatch.setattr(entity._radio_catalogue.commands, 'async_global_search', AsyncMock(return_value={
        'tunein': {'station': {'items': [{'type': 2, 'name': 'Synthetic radio', 'audiopath': 'tunein:station:test'}]}}
    }))
    search = await entity.async_search_media(SearchMediaQuery(search_query='nothing'))
    assert isinstance(search, SearchMedia)
    assert len(search.result) == 1
    assert all(isinstance(child, BrowseMedia) for child in search.result)


@pytest.mark.asyncio
async def test_real_native_library_updates_existing_entity_and_keeps_miniserver_controls(hass, audio_setup):
    entry = await audio_setup.setup(playback=True)
    entity = hass.data['media_player'].get_entity(zone_entity_id(hass, 7))
    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert type(coordinator.audio_metadata._client).__module__ == 'pyloxone_audio.native'
    assert type(coordinator.audio_commands).__module__ == 'pyloxone_audio.native'
    await audio_setup.queues[0].put(json.dumps({'audio_event': [
        {'playerid': 7, 'mode': 'play', 'audiopath': 'library:local:track:one',
         'title': 'Portable real parser', 'artist': 'Synthetic artist', 'time': 12, 'duration': 180, 'pbr': 32},
        {'playerid': 999, 'mode': 'play', 'title': 'Wrong player'}
    ]}))
    await hass.async_block_till_done()
    assert entity.media_title == 'Portable real parser'
    assert entity.media_artist == 'Synthetic artist'
    assert entity.media_position == 12
    assert entity.unique_id == 'synthetic-zone-7'
    assert type(coordinator.audio_metadata.get(7)).__module__ == 'pyloxone_audio.native'
    assert hass.states.get(zone_entity_id(hass, 8)).attributes.get('media_title') is None
    # Losing optional metadata cannot remove ordinary Miniserver controls.
    await audio_setup.queues[0].put(None)
    await hass.async_block_till_done()
    assert entity.media_title is None
    hass.bus.async_fire(EVENT, {'play-7': 2, 'volume-7': 21})
    await hass.async_block_till_done()
    assert entity.available
    await entity.async_set_volume_level(0.22)
    assert audio_setup.apis[0].send_websocket_command.await_count == 1
    assert coordinator.audio_metadata._client.get(7) is None
