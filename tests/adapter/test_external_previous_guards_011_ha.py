"""External-only remembered playback does not bypass current native ownership."""
import asyncio
import json
from unittest.mock import AsyncMock
import pytest
from homeassistant.exceptions import HomeAssistantError
from test_audioserver_ha import audio_setup
from test_native_source_return_ha import install_sources, library_row, RADIO
from custom_components.loxone.pyloxone_api import audioserver as wire


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['account', 'native-selection'])
async def test_external_only_source_return_rechecks_account_and_native_identity(hass, audio_setup, monkeypatch, change):
    entity, emit, writes = await install_sources(hass, audio_setup, monkeypatch, spotify=True)
    monkeypatch.setattr(wire.AudioServerCommands, 'async_recent_sources', AsyncMock(return_value={'items': []}))
    await entity._async_refresh_native_sources()
    await emit(library_row(audiopath='spotify:track:original', parent={'id': 'spotify:playlist:original'}, sourceName='Synthetic owner', time=0))
    await emit({'playerid': 7, 'audiopath': RADIO, 'mode': 'play', 'eventype': 0})
    assert writes == [] and entity._source_generation == 0
    assert 'Spotify' in entity.source_list
    original_accounts = wire.AudioServerCommands.async_service_accounts
    async def changed_accounts(client):
        if change == 'account':
            return [{'cmd': 'spotify', 'id': 'replacement-account', 'name': 'Synthetic', 'user': 'Replacement user', 'configerror': False}]
        seen = asyncio.Event()
        remove = entity._audio_metadata.async_add_listener(7, seen.set)
        audio_setup.queues[0].put_nowait(json.dumps({'audio_event': [{
            'playerid': 7, 'audiopath': 'tunein:station:new-household-selection', 'mode': 'play', 'eventype': 0,
        }]}))
        try:
            await asyncio.wait_for(seen.wait(), 1)
        finally:
            remove()
        return await original_accounts(client)
    monkeypatch.setattr(wire.AudioServerCommands, 'async_service_accounts', changed_accounts)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call('media_player', 'select_source', {
            'entity_id': entity.entity_id, 'source': 'Spotify',
        }, blocking=True)
    assert writes == []
    assert not entity._audio_commands.source_fences
    if change == 'account':
        assert 'Spotify' not in entity.source_list
    else:
        assert entity._audio_metadata.get(7).audio_path == 'tunein:station:new-household-selection'
