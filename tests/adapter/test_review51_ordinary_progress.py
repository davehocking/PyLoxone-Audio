"""Reviewer-only ordinary advancing-Library-clock test at the actual HA service boundary.
Synthetic data only. Identical file is run on full Run50 and exact Run48-runtime copies.
"""
import asyncio
import json
import os
from pathlib import Path

import pytest
from custom_components.loxone import spotify_continuity
from test_spotify_library_return_ha import library_journey, LIBRARY, FOLDER
from test_audioserver_ha import audio_setup  # noqa: F401 - actual fixture


@pytest.mark.asyncio
@pytest.mark.parametrize('clock', ['static-control', 'ordinary-progress'])
async def test_readable_paused_provider_return_allows_ordinary_library_clock(hass, audio_setup, monkeypatch, tmp_path, clock):
    entity, session, _provider, source, writes, saved, entry = await library_journey(
        hass, audio_setup, monkeypatch, tmp_path, 'paused'
    )
    calls_before = len(session.calls)
    native_before = len(writes)
    progressed = []

    async def normal_native_tick(url):
        if clock == 'ordinary-progress' and not progressed and url.endswith('/me/player'):
            started = asyncio.get_running_loop().time()
            await asyncio.sleep(0.25)
            elapsed = asyncio.get_running_loop().time() - started
            row = {'playerid': 7, 'mode': 'play', 'eventype': 0,
                   'audiopath': LIBRARY, 'parent': {'id': FOLDER},
                   'time': 45.0 + elapsed, 'duration': 240, 'pbr': 32}
            progressed.append({'elapsed_seconds': elapsed, 'position_before': 45.0,
                               'position_after': row['time'], 'row': row})
            audio_setup.queues[-1].put_nowait(json.dumps({'audio_event': [row]}))
            await hass.async_block_till_done()

    session.on_read = normal_native_tick
    outcome = {'clock': clock, 'runtime_module': spotify_continuity.__file__,
               'provider_state': 'readable-paused', 'newer_household_commands': 0}
    try:
        await source('Spotify')
        outcome['success'] = True
    except Exception as error:
        outcome['success'] = False
        outcome['exception_type'] = type(error).__name__
        outcome['failure_summary'] = entity.extra_state_attributes.get('audio_last_source_failure')
        raise
    finally:
        outcome['progress_ticks'] = progressed
        outcome['provider_puts'] = [call[1] for call in session.calls[calls_before:] if call[0] == 'PUT']
        outcome['native_commands_added'] = len(writes) - native_before
        folder = Path(os.environ.get('REVIEW51_RESULT_DIR',str(tmp_path/'review51-results')))
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (clock + '.json')).write_text(json.dumps(outcome, indent=2) + '\n')
        await hass.config_entries.async_unload(entry.entry_id)
    assert not outcome['provider_puts']
    assert outcome['native_commands_added'] == 1
    assert writes[native_before]=='audio/7/serviceplay/spotify/native-owner/'
    if clock=='ordinary-progress':assert len(progressed)==1
