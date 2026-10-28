"""Repeated real HA native returns, independent of unrelated HA Spotify state.

Historical case names retained for baseline identity accounting. No provider
controller exists in 0.1.1; the native entity owns cleanup and exact-item seek.
"""
from copy import deepcopy
import asyncio
import json
import pytest
from custom_components.loxone.pyloxone_api import audioserver as wire
from test_audioserver_ha import audio_setup
from test_spotify_library_return_ha import library_journey


@pytest.mark.asyncio
@pytest.mark.parametrize('provider_state', ['paused', 'detached'])
async def test_same_controller_supports_repeated_library_spotify_returns(
    hass, audio_setup, monkeypatch, tmp_path, provider_state,
):
    entity, session, _provider, source, writes, _saved, entry = await library_journey(
        hass, audio_setup, monkeypatch, tmp_path, provider_state,
    )
    preview = deepcopy(session.queue)
    for cycle in range(3):
        saved = entity._radio_catalogue.source_session('Spotify')
        before = list(writes)
        await source('Spotify')
        added = writes[len(before):]
        assert writes[:len(before)] == before
        assert len(added) == 2
        assert saved.audio_path.replace(':', '%3A') in added[0]
        assert added[1] == 'audio/7/position/' + str(saved.position)
        assert not entity._audio_commands.source_fences
        assert entity._source_task is None
        assert not hasattr(entity, '_spotify_return')
        assert session.queue == preview
        if cycle < 2:
            await source('Local Library')
            assert entity._source_task is None
            assert entity._audio_metadata.get(7).source == 'Local Library'
    assert session.calls == []
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.asyncio
@pytest.mark.parametrize('provider_state', ['paused', 'detached'])
async def test_same_controller_supports_repeated_tunein_spotify_returns(
    hass, audio_setup, monkeypatch, tmp_path, provider_state,
):
    entity, session, _provider, source, writes, _saved, entry = await library_journey(
        hass, audio_setup, monkeypatch, tmp_path, provider_state,
    )
    await source('Spotify')
    preview = deepcopy(session.queue)
    tunein = 'tunein:station:synthetic'
    entity._audio_commands.async_recent_sources.return_value['items'].append({
        'audiopath': tunein, 'type': 2, 'title': 'Synthetic radio',
    })
    previous_request = wire.AudioServerCommands._async_request

    async def request(self, command, key, *, is_current=None, on_send=None, **kwargs):
        if command.split('/')[2:5] == ['serviceplay', 'radio', 'world']:
            assert is_current()
            on_send()
            writes.append(command)
            session.current = None
            asyncio.get_running_loop().call_soon(audio_setup.queues[-1].put_nowait,
                json.dumps({'audio_event': [{'playerid': 7, 'audiopath': tunein, 'mode': 'play', 'eventype': 0}]}))
            return True
        return await previous_request(self, command, key, is_current=is_current, on_send=on_send, **kwargs)

    monkeypatch.setattr(wire.AudioServerCommands, '_async_request', request)
    for _ in range(3):
        await source('TuneIn')
        assert entity._audio_metadata.get(7).source == 'TuneIn'
        before = list(writes)
        saved = entity._radio_catalogue.source_session('Spotify')
        await source('Spotify')
        added = writes[len(before):]
        assert len(added) == 2
        assert '/serviceplay/spotify/native-owner/' in added[0]
        assert saved.audio_path.replace(':', '%3A') in added[0]
        assert added[1] == 'audio/7/position/' + str(saved.position)
        assert not entity._audio_commands.source_fences
        assert entity._source_task is None
        assert session.queue == preview
    assert session.calls == []
    await hass.config_entries.async_unload(entry.entry_id)
