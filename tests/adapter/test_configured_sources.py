"""Synthetic configured availability independent of room recent-history content."""
# ruff: noqa: S101, INP001, ANN001, D103, SLF001, PLC0415
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.config_entries import ConfigEntryState
from test_audio_catalogue import catalogue_commands
from test_audioserver_ha import audio_setup as audio_setup, zone_entity_id
from custom_components.loxone.audio_catalogue import AudioCatalogue
from custom_components.loxone.pyloxone_api import audioserver as wire


def configured_commands():
    commands = catalogue_commands()
    commands.async_recent_sources = AsyncMock(return_value={'items': []})
    # Available provider/root data, NOT playback or history. No default is chosen.
    def folder(service, *_):
        row = ({'type': 2, 'id': 'library:local:track:one', 'name': 'Synthetic local track'}
               if service == 'library' else
               {'type': 2, 'name': 'Synthetic channel', 'audiopath': 'loxoneradio:station:synthetic'})
        return [{'start': 0, 'totalitems': 1, 'items': [row]}]
    commands.async_media_folder.side_effect = folder
    return commands


@pytest.mark.asyncio
async def test_configured_radio_remains_visible_without_a_resume_target(hass, audio_setup, monkeypatch):
    commands = configured_commands()
    for name, value in vars(commands).items():
        monkeypatch.setattr(wire.AudioServerCommands, name, value)
    await audio_setup.setup(playback=True)
    entity = hass.data['media_player'].get_entity(zone_entity_id(hass, 7))
    assert set(entity.source_list) == {'Line-In', 'Local Library', 'Loxone Radio', 'Spotify', 'TuneIn'}
    assert 'Loxone Radio' not in entity._radio_catalogue.source_choices
    with pytest.raises(HomeAssistantError, match='Browse'):
        await hass.services.async_call('media_player', 'select_source',
            {'entity_id': entity.entity_id, 'source': 'Loxone Radio'}, blocking=True)
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()
    assert not entity._audio_commands.source_fences
    root = await entity.async_browse_media()
    radio = next(row for row in root.children if row.title == 'Loxone Radio')
    assert radio.can_expand and not radio.can_play
    page = await entity.async_browse_media(radio.media_content_type, radio.media_content_id)
    assert page.children[0].can_play


@pytest.mark.asyncio
@pytest.mark.parametrize('history', [[], [{'audiopath': 'tunein:station:chosen', 'title': 'Chosen'}],
    [{'audiopath': 'library:local:track:one', 'title': 'One', 'type': 2}]])
async def test_history_changes_content_not_configured_presence(history):
    commands = configured_commands()
    catalogue = AudioCatalogue(commands, 7)
    await catalogue.async_refresh_sources()
    before = dict(catalogue.source_descriptors)
    commands.async_recent_sources.return_value = {'items': history}
    await catalogue.async_refresh_sources()
    assert catalogue.source_descriptors == before
    assert set(before) == {'Line-In', 'Local Library', 'Loxone Radio', 'Spotify', 'TuneIn'}
    commands.async_recent_sources.assert_awaited_with(7)


@pytest.mark.asyncio
async def test_configured_presence_survives_optional_history_outage(hass, audio_setup, monkeypatch):
    commands = configured_commands()
    commands.async_recent_sources.side_effect = TimeoutError('synthetic history unavailable')
    for name, value in vars(commands).items():
        monkeypatch.setattr(wire.AudioServerCommands, name, value)
    await audio_setup.setup(playback=True)
    entity = hass.data['media_player'].get_entity(zone_entity_id(hass, 7))
    assert set(entity.source_list) == {'Line-In', 'Local Library', 'Loxone Radio', 'Spotify', 'TuneIn'}
    assert not entity._radio_catalogue.source_choices


@pytest.mark.asyncio
async def test_removed_configuration_is_not_advertised_or_resumed_from_stale_history():
    commands = configured_commands()
    commands.async_recent_sources.return_value = {'items': [
        {'type': 7, 'audiopath': 'spotify@owner:playlist:one', 'title': 'Old'},
        {'audiopath': 'tunein:station:old', 'title': 'Old radio'}]}
    catalogue = AudioCatalogue(commands, 7)
    await catalogue.async_refresh_sources()
    commands.async_service_accounts.return_value[0]['configerror'] = True
    commands.async_source_inputs.return_value[0]['power'] = 'off'
    commands.async_search_capabilities.return_value = {}
    commands.async_radio_services.return_value = []
    commands.async_media_folder.side_effect = wire.AudioCommandError('Synthetic unavailable catalogue')
    await catalogue.async_refresh_sources()
    assert not catalogue.source_descriptors
    with pytest.raises(ValueError):
        await catalogue.async_source_selection('TuneIn')


@pytest.mark.asyncio
async def test_multiple_accounts_and_inputs_remain_exact_without_content():
    commands = configured_commands()
    commands.async_service_accounts.return_value.append({
        'cmd': 'spotify', 'id': 'second', 'name': 'Synthetic Spotify', 'configerror': False})
    commands.async_source_inputs.return_value.append({
        'type': 6, 'id': 'ABCDEF123456#1000002', 'cmd': 'linein/ABCDEF123456#1000002',
        'name': 'Record player', 'valid': True, 'power': 'on'})
    catalogue = AudioCatalogue(commands, 7)
    await catalogue.async_refresh_sources()
    sources = catalogue.source_descriptors
    assert sources['Spotify · Synthetic Spotify · owner'].account == 'owner'
    assert sources['Spotify · Synthetic Spotify · second'].account == 'second'
    assert sources['Line-In · Record player · ABCDEF123456#1000001'].input_id == 'ABCDEF123456#1000001'
    assert sources['Line-In · Record player · ABCDEF123456#1000002'].input_id == 'ABCDEF123456#1000002'
    assert not any(target.service == 'spotify' for target in catalogue.source_choices.values())


@pytest.mark.asyncio
async def test_history_outage_publishes_configured_list_without_a_later_metadata_callback(hass):
    from test_spotify_continuity_review import entity_boundary
    entity, _, _, commands, _, _ = entity_boundary(hass)
    commands.async_recent_sources.side_effect = TimeoutError('Synthetic optional history outage')
    assert entity.source_list is None
    await entity._async_refresh_native_sources()
    assert entity.source_list == ['Spotify', 'TuneIn']
    assert not entity._audio_sources_ready


@pytest.mark.asyncio
async def test_exact_configured_input_selection_does_not_require_optional_content_history(hass):
    from test_spotify_continuity_review import entity_boundary
    from test_spotify_continuity import native
    entity, _, snapshots, commands, _, _ = entity_boundary(hass, binding=None)
    commands.async_source_inputs = configured_commands().async_source_inputs
    commands.async_recent_sources.side_effect = TimeoutError('Synthetic history outage')
    await entity._async_refresh_native_sources()
    snapshots[0] = native('tunein:station:before', mode='stop')

    async def play(_player, service, _account, path, *, is_current, on_send):
        assert service == 'linein' and is_current()
        on_send()
        snapshots[0] = native('linein:' + path)

    commands.async_play_catalogue.side_effect = play
    await entity.async_select_source('Line-In')
    commands.async_play_catalogue.assert_awaited_once()
    assert commands.async_play_catalogue.await_args.args[-1] == 'ABCDEF123456#1000001'


@pytest.mark.asyncio
async def test_descriptor_target_lookup_cannot_rebase_over_a_newer_household_selection(hass):
    from test_spotify_continuity_conflicts import _saved
    from test_spotify_continuity import native
    entity, session, snapshots, commands = await _saved(hass)
    hass.config_entries.async_get_entry('synthetic-entry').state=ConfigEntryState.NOT_LOADED
    target = entity._radio_catalogue.source_choices.pop('Spotify')

    async def changed(_player):
        snapshots[0] = native('tunein:station:newer-household-choice')
        return {'items': [{'audiopath': target.audio_path, 'title': 'Synthetic', 'type': 7}]}

    commands.async_recent_sources.side_effect = changed
    with pytest.raises(HomeAssistantError):
        await entity.async_select_source('Spotify')
    assert all(method == 'GET' for method, _, _ in session.calls)
    commands.async_recent_sources.assert_awaited_once()
    commands.async_play_catalogue.assert_not_awaited()
