"""Review01 root content validation; synthetic provider-correct data only."""
# ruff: noqa: S101, INP001, ANN001, ANN202, D103, SLF001, PLC0415
import asyncio
from unittest.mock import AsyncMock

import pytest
from test_configured_sources import configured_commands
from test_spotify_continuity_review import entity_boundary
from custom_components.loxone.audio_catalogue import AudioCatalogue
from custom_components.loxone.pyloxone_api.audioserver import AudioCommandError

EXPECTED = {'Line-In', 'Local Library', 'Loxone Radio', 'Spotify', 'TuneIn'}


def healthy_root(service):
    if service == 'library':
        return {'type': 2, 'id': 'library:local:track:one', 'name': 'Synthetic local track'}
    return {'type': 2, 'audiopath': 'loxoneradio:station:one', 'name': 'Synthetic channel'}


def root_page(rows):
    return [{'start': 0, 'totalitems': len(rows), 'items': rows}]


BAD_ROWS = [
    None,
    {'type': True, 'name': 'Malformed type'},
    {'type': 2, 'name': 'Missing native identity'},
    {'type': 99, 'name': 'Unsupported content'},
    {'type': 2, 'name': 'Unplayable', 'unplayable': True},
    {'type': 2, 'name': 'Wrong provider', 'audiopath': 'tunein:station:foreign', 'id': 'tunein:station:foreign'},
]


@pytest.mark.asyncio
@pytest.mark.parametrize('service,missing', [('library', 'Local Library'), ('loxoneradio', 'Loxone Radio')])
@pytest.mark.parametrize('bad', BAD_ROWS)
async def test_malformed_or_unusable_root_is_incomplete_and_browse_recovers(hass, service, missing, bad):
    entity, _, _, commands, _, _ = entity_boundary(hass, binding=None)
    for name, value in vars(configured_commands()).items():
        setattr(commands, name, value)
    broken = True

    async def folder(kind, *_):
        return root_page([bad] if broken and kind == service else [healthy_root(kind)])

    commands.async_media_folder.side_effect = folder
    await entity._async_refresh_native_sources()
    assert set(entity._radio_catalogue.source_descriptors) == EXPECTED - {missing}
    assert not entity._audio_sources_ready
    broken = False
    await entity.async_browse_media()
    assert entity._audio_sources_ready and set(entity._radio_catalogue.source_descriptors) == EXPECTED
    commands.async_play_catalogue.assert_not_awaited()
    commands.async_play_radio_station.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('service,missing', [('library', 'Local Library'), ('loxoneradio', 'Loxone Radio')])
async def test_malformed_sibling_does_not_validate_a_root(service, missing):
    commands = configured_commands()
    commands.async_media_folder.side_effect = lambda kind, *_: root_page([healthy_root(kind), None] if kind == service else [healthy_root(kind)])
    catalogue = AudioCatalogue(commands, 7)
    await catalogue.async_refresh_sources()
    assert set(catalogue.source_descriptors) == EXPECTED - {missing}
    assert not catalogue.source_inventory_complete


@pytest.mark.asyncio
@pytest.mark.parametrize('service,missing', [('library', 'Local Library'), ('loxoneradio', 'Loxone Radio')])
async def test_filtered_only_root_supplies_no_visible_availability(service, missing):
    commands = configured_commands()
    commands.async_media_folder.side_effect = lambda kind, *_: root_page([{'name': '.private'}] if kind == service else [healthy_root(kind)])
    catalogue = AudioCatalogue(commands, 7)
    await catalogue.async_refresh_sources()
    assert set(catalogue.source_descriptors) == EXPECTED - {missing}
    assert catalogue.source_inventory_complete


@pytest.mark.asyncio
async def test_obsolete_incomplete_discovery_cannot_replace_new_complete_inventory():
    commands = configured_commands()
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def folder(service, *_):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await release.wait()
            return root_page([None])
        return root_page([healthy_root(service)])

    commands.async_media_folder.side_effect = folder
    catalogue = AudioCatalogue(commands, 7)
    task = asyncio.create_task(catalogue.async_refresh_sources())
    await entered.wait()
    try:
        await catalogue.async_refresh_sources()
    finally:
        release.set()
    outcome = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(outcome[0], AudioCommandError)
    assert catalogue.source_inventory_complete
    assert set(catalogue.source_descriptors) == EXPECTED
