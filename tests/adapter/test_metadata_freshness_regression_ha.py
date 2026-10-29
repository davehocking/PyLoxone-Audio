"""0.1.2 regression: old Audio Server data must not become current on MS play.

Synthetic events only. The original real-HA setup/entity/receiver/event path runs;
only external transports and the sampled wall clock are controlled.
"""
from datetime import datetime, timedelta
import json
from unittest.mock import AsyncMock

import pytest
from homeassistant.util import dt as dt_util

from custom_components.loxone.const import EVENT
from custom_components.loxone.pyloxone_api import audioserver
from pyloxone_audio import native
from test_audioserver_ha import audio_setup as audio_setup, zone_entity_id


@pytest.mark.asyncio
@pytest.mark.parametrize('sample_age', [timedelta(seconds=1), timedelta(hours=7)], ids=['fresh-control', 'overnight-stale'])
async def test_miniserver_play_does_not_certify_an_old_track(hass, audio_setup, monkeypatch, sample_age):
    """A live transport flag cannot certify seven-hour-old cached track timing."""
    current = dt_util.utcnow()
    clock = [current - sample_age]

    class SampleClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0].astimezone(tz) if tz is not None else clock[0].replace(tzinfo=None)

    monkeypatch.setattr(native, 'datetime', SampleClock)
    monkeypatch.setattr(dt_util, 'utcnow', lambda: clock[0])
    # Any future recovery is a read, never a play/seek/source/mode command.
    status = AsyncMock(side_effect=TimeoutError('synthetic current status unavailable'))
    execute = AsyncMock()
    seek = AsyncMock()
    monkeypatch.setattr(audioserver.AudioServerCommands, 'async_player_status', status)
    monkeypatch.setattr(audioserver.AudioServerCommands, 'async_execute', execute)
    monkeypatch.setattr(audioserver.AudioServerCommands, 'async_seek', seek)

    entry = await audio_setup.setup(playback=True)
    entity_id = zone_entity_id(hass, 7)
    # HA intentionally omits media details while OFF. Match the incident's
    # prior native STOP/IDLE state before seeding the old metadata sample.
    hass.bus.async_fire(EVENT, {'play-7': 0})
    await hass.async_block_till_done()
    await audio_setup.queues[0].put(json.dumps({'audio_event': [{
        'playerid': 7, 'title': 'Previous session track', 'artist': 'Synthetic artist',
        'audiopath': 'spotify:track:previous-synthetic', 'sourceName': 'Spotify',
        'mode': 'stop', 'time': 0, 'duration': 219, 'pbr': 32,
    }]}))
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).attributes.get('media_title') == 'Previous session track'
    receiver = hass.data['loxone'][entry.entry_id].audio_metadata._client._receiver
    assert receiver._listening is True, 'The regression requires the original stream to remain nominally open'

    clock[0] = current
    hass.bus.async_fire(EVENT, {'play-7': 2})
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state.state == 'playing', 'Do not falsify authoritative Miniserver playback state'
    if sample_age > timedelta(hours=1):
        assert state.attributes.get('media_title') != 'Previous session track', (
            'Fresh Miniserver PLAYING must not certify overnight-old Audio Server track metadata'
        )
    else:
        assert state.attributes.get('media_title') == 'Previous session track', (
            'Fresh sparse metadata is not a silent-stream failure'
        )
    execute.assert_not_awaited()
    seek.assert_not_awaited()
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()
