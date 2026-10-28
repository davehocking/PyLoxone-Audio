"""Repeated native feedback ordering; entirely synthetic transports.

Historical case identities retained; retired provider reads cannot influence
confirmation, retries or lifecycle cleanup.
"""
import asyncio
from copy import deepcopy
import json
from unittest.mock import AsyncMock
from aiohttp import ClientError
import pytest
from homeassistant.exceptions import HomeAssistantError
from test_audioserver_ha import audio_setup
from test_spotify_continuity import TRACK, CONTEXT
from test_spotify_library_return_ha import library_journey
from custom_components.loxone.pyloxone_api import audioserver as wire


@pytest.mark.asyncio
@pytest.mark.parametrize('order', ['native-first', 'provider-first', 'provider-204', 'read-failure', 'missing-native'])
async def test_second_return_releases_same_controller_after_late_or_missing_feedback(
    hass, audio_setup, monkeypatch, tmp_path, order,
):
    entity, session, _provider, source, writes, _saved, entry = await library_journey(
        hass, audio_setup, monkeypatch, tmp_path, 'paused',
    )
    await source('Spotify')
    await source('Local Library')
    before = list(writes)
    queue_before = deepcopy(session.queue)
    retained = entity._radio_catalogue.source_session('Spotify')
    native_command = 'audio/7/serviceplay/spotify/native-owner/spotify%3Atrack%3A' + 'A'*22 + '/parentpath/spotify%3Aplaylist%3A' + 'C'*22 + '/0/noshuffle'
    pending = []
    row = {'playerid': 7, 'audiopath': TRACK, 'parent': {'id': CONTEXT},
        'sourceName': 'native-user', 'mode': 'play', 'eventype': 0,
        'time': 0, 'duration': 180, 'pbr': 32}
    forbidden = AsyncMock(side_effect=ClientError('Unrelated HA Spotify must not be read'))

    async def feedback():
        await asyncio.sleep(0)
        audio_setup.queues[-1].put_nowait(json.dumps({'audio_event': [row]}))

    async def request(_self, command, _key, *, is_current, on_send, **_kwargs):
        assert is_current()
        if on_send:
            on_send()
        writes.append(command)
        if '/position/' in command:
            return [{'position': float(command.rsplit('/', 1)[-1])}]
        assert command == native_command
        if order == 'provider-204':
            session.current = None
        elif order == 'read-failure':
            session.async_request = forbidden
        if order == 'missing-native':
            return
        if order == 'native-first':
            await feedback()
        else:
            pending.append(asyncio.create_task(feedback()))

    monkeypatch.setattr(wire.AudioServerCommands, '_async_request', request)
    try:
        if order == 'missing-native':
            with pytest.raises(HomeAssistantError):
                await source('Spotify')
            assert entity._radio_catalogue.source_session('Spotify') is retained
        else:
            await source('Spotify')
            assert entity._audio_metadata.get(7).audio_path == TRACK
        assert bool(entity._audio_commands.source_fences) == (order == 'missing-native')
        assert entity._source_task is None
        assert session.calls == []
        added = writes[len(before):]
        assert added == [native_command] + ([] if order == 'missing-native' else ['audio/7/position/13.264'])
        forbidden.assert_not_awaited()
        assert session.queue == queue_before
        await hass.config_entries.async_unload(entry.entry_id)
        assert not entity._audio_commands.source_fences
    finally:
        await asyncio.gather(*pending, return_exceptions=True)
