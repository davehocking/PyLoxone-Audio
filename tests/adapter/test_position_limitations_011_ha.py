"""Characterise retained one-shot native restore; synthetic evidence, not a fix."""
import pytest
from test_audioserver_ha import audio_setup
from test_native_source_return_ha import install_sources, library_row, RADIO
from custom_components.loxone.pyloxone_api import audioserver as wire


@pytest.mark.parametrize('spotify', [False, True])
@pytest.mark.parametrize('failure', ['transport', 'timeout', 'invalid-reply'])
async def test_optional_seek_failure_keeps_confirmed_source_without_retry(hass, audio_setup, monkeypatch, caplog, spotify, failure):
    entity, emit, calls = await install_sources(hass, audio_setup, monkeypatch, spotify=spotify)
    row = library_row()
    if spotify:
        row.update(audiopath='spotify:track:original', parent={'id': 'spotify:playlist:original'}, sourceName='Synthetic owner')
    await emit(row)
    await emit({'playerid': 7, 'mode': 'play', 'eventype': 0, 'audiopath': RADIO})
    original = wire.AudioServerCommands._async_request
    attempts = []

    async def request(client, command, key, **kwargs):
        if '/position/' in command:
            assert kwargs['is_current']()
            attempts.append(command)
            if failure == 'transport':
                raise wire.AudioCommandError('Synthetic seek unavailable')
            if failure == 'timeout':
                raise TimeoutError('Synthetic optional timeout')
            return [{'position': 'invalid'}]
        return await original(client, command, key, **kwargs)

    monkeypatch.setattr(wire.AudioServerCommands, '_async_request', request)
    await hass.services.async_call('media_player', 'select_source', {
        'entity_id': entity.entity_id, 'source': 'Spotify' if spotify else 'Local Library',
    }, blocking=True)
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert attempts == ['audio/7/position/45.0']
    assert entity._audio_metadata.get(7).audio_path == row['audiopath']
    assert entity._audio_metadata.get(7).position == 0
    assert entity._source_task is None
    assert not entity._audio_commands.source_fences
    assert 'Optional audio position restore failed; confirmed source playback is retained' in caplog.text
    assert 'Synthetic' not in caplog.text
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()
