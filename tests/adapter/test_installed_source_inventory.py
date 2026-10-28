"""Synthetic regressions for the observed installed partial source inventory.

Native discovery schema follows fresh-discovery01.json; private content omitted.
No device connection or command is made by these tests.
"""
# ruff: noqa: S101, INP001, ANN001, ANN202, D103, SLF001, PLC0415
from unittest.mock import AsyncMock

import pytest
from test_configured_sources import configured_commands
from test_spotify_continuity_review import entity_boundary

from custom_components.loxone.audio_catalogue import AudioCatalogue
from custom_components.loxone.pyloxone_api.audioserver import AudioCommandError

ALL = {'Line-In', 'Local Library', 'Loxone Radio', 'Spotify', 'TuneIn'}


@pytest.mark.asyncio
@pytest.mark.parametrize('capabilities', [{}, {'local': 'malformed'}, TimeoutError()])
async def test_available_sources_do_not_depend_on_searchability(capabilities):
    commands = configured_commands()
    if isinstance(capabilities, Exception):
        commands.async_search_capabilities.side_effect = capabilities
    else:
        commands.async_search_capabilities.return_value = capabilities
    catalogue = AudioCatalogue(commands, 7)
    await catalogue.async_refresh_sources()
    assert set(catalogue.source_descriptors) == ALL
    commands.async_search_capabilities.assert_not_awaited()
    commands.async_radio_services.assert_awaited_once()
    assert any(call.args == ('library', 'nouser', '0', 0) for call in commands.async_media_folder.await_args_list)
    assert not any(t.service in ('library', 'spotify', 'world') for t in catalogue.source_choices.values())


@pytest.mark.asyncio
@pytest.mark.parametrize('failed_provider,missing', [('radio', 'TuneIn'), ('library', 'Local Library'), ('loxoneradio', 'Loxone Radio')])
@pytest.mark.parametrize('failure', [TimeoutError, AudioCommandError, ValueError])
async def test_partial_inventory_is_not_ready_and_standard_browse_recovers(hass, failed_provider, missing, failure):
    entity, _, _, commands, _, _ = entity_boundary(hass, binding=None)
    configured = configured_commands()
    for name, value in vars(configured).items():
        setattr(commands, name, value)
    payload = configured.async_media_folder.side_effect
    failed = False

    async def folder(service, account, folder_id, offset=0):
        nonlocal failed
        if service == failed_provider and not failed:
            failed = True
            raise failure('Synthetic bounded inventory failure')
        return payload(service, account, folder_id, offset)

    async def radio():
        nonlocal failed
        if failed_provider == 'radio' and not failed:
            failed = True
            raise failure('Synthetic bounded inventory failure')
        return [{'cmd': 'world', 'root': 'root', 'name': 'World'}]

    commands.async_media_folder.side_effect = folder
    commands.async_radio_services.side_effect = radio
    await entity._async_refresh_native_sources()
    assert set(entity._radio_catalogue.source_descriptors) == ALL - {missing}
    assert not entity._audio_sources_ready
    assert (await entity.async_browse_media()).children
    assert set(entity._radio_catalogue.source_descriptors) == ALL
    assert entity._audio_sources_ready
    reads = (commands.async_radio_services.await_count, commands.async_media_folder.await_count, commands.async_recent_sources.await_count)
    assert (await entity.async_browse_media()).children
    assert reads == (commands.async_radio_services.await_count, commands.async_media_folder.await_count, commands.async_recent_sources.await_count)
    commands.async_play_catalogue.assert_not_awaited()
    commands.async_play_radio_station.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirmed_empty_catalogues_are_absent_despite_supported_search_and_stale_history(hass):
    entity, _, _, commands, _, _ = entity_boundary(hass, binding=None)
    for name, value in vars(configured_commands()).items():
        setattr(commands, name, value)
    await entity._async_refresh_native_sources()
    assert set(entity._radio_catalogue.source_descriptors) == ALL
    commands.async_radio_services.return_value = []
    commands.async_media_folder.side_effect = None
    commands.async_media_folder.return_value = [{'start': 0, 'totalitems': 0, 'items': []}]
    commands.async_recent_sources.return_value = {'items': [
        {'audiopath': 'tunein:station:old', 'title': 'Old'},
        {'audiopath': 'library:local:track:old', 'title': 'Old', 'type': 2}]}
    await entity._async_refresh_native_sources()
    assert set(entity._radio_catalogue.source_descriptors) == {'Line-In', 'Spotify'}
    assert entity._audio_sources_ready
    commands.async_search_capabilities.assert_not_awaited()
    counts = commands.async_radio_services.await_count, commands.async_media_folder.await_count
    await entity.async_browse_media()
    assert counts == (commands.async_radio_services.await_count, commands.async_media_folder.await_count)
    commands.async_play_catalogue.assert_not_awaited()


@pytest.mark.asyncio
async def test_malformed_radio_inventory_is_incomplete_not_confirmed_absence(hass):
    entity, _, _, commands, _, _ = entity_boundary(hass, binding=None)
    for name, value in vars(configured_commands()).items():
        setattr(commands, name, value)
    commands.async_radio_services.return_value = [{'cmd': 'world', 'root': 'root'}]
    await entity._async_refresh_native_sources()
    assert not entity._audio_sources_ready
    assert 'TuneIn' not in entity._radio_catalogue.source_descriptors
    commands.async_radio_services.return_value = [{'cmd': 'world', 'root': 'root', 'name': 'World'}]
    await entity.async_browse_media()
    assert entity._audio_sources_ready and set(entity._radio_catalogue.source_descriptors) == ALL
