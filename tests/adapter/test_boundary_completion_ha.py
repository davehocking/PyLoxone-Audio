"""Boundary continuation via real HA owners; only synthetic external I/O."""
import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest
from homeassistant.exceptions import HomeAssistantError
from pyloxone_audio import SourceEnvironment

from test_audioserver_ha import audio_setup
from test_native_source_return_ha import install_sources, library_row
from test_seek_contributor import player
from test_source_simple_session_ha import session_room
from test_source_return_simplification_ha import simplified_harness, select, rsa_key

from custom_components.loxone import audio_sources
from custom_components.loxone.pyloxone_api import audioserver
from custom_components.loxone.spotify_continuity import SpotifyReturnUnavailable


@pytest.mark.asyncio
async def test_optional_restore_diagnostics_are_not_source_confirmation(hass, audio_setup, monkeypatch, rsa_key):
    entity, controls, sockets, emit = await simplified_harness(hass, audio_setup, monkeypatch, rsa_key)
    controls['seek_reply'] = 'reject'
    await select(hass, entity)
    assert len(sockets) == 2
    assert entity._audio_metadata.get(7).source == 'Local Library'
    assert not entity._audio_commands.source_fences
    assert not hasattr(entity, '_audio_last_source_failure')


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome', ['prewrite-absence', 'changed-native', 'uncertain-write', 'cancelled'])
async def test_owning_source_route_not_host_bridge_decides_optional_fallback(hass, audio_setup, monkeypatch, outcome):
    entity, emit, writes, session, spotify = await session_room(hass, audio_setup, monkeypatch)
    original_cancellation = asyncio.CancelledError()

    async def bridge(metadata, available):
        assert available()
        if outcome == 'cancelled':
            raise original_cancellation
        if outcome == 'changed-native':
            await emit({**spotify, 'sourceName': 'Different account'})
        if outcome == 'uncertain-write':
            entity._audio_commands.source_fences[7] = lambda: None
        raise SpotifyReturnUnavailable('Synthetic linked session unavailable')

    monkeypatch.setattr(entity._spotify_return, 'async_resume_native', bridge)
    try:
        if outcome == 'prewrite-absence':
            await entity.async_select_source('Spotify')
            assert len(writes) == 1 and '/serviceplay/spotify/' in writes[0]
        elif outcome == 'cancelled':
            with pytest.raises(asyncio.CancelledError) as caught:
                await entity.async_select_source('Spotify')
            assert caught.value is original_cancellation
            assert not writes
        else:
            with pytest.raises(HomeAssistantError):
                await entity.async_select_source('Spotify')
            assert not writes
        assert entity._source_task is None
    finally:
        entity._audio_commands.source_fences.pop(7, None)


@pytest.mark.asyncio
async def test_real_owner_passive_history_uses_ordered_native_samples(hass, audio_setup, monkeypatch):
    entity, emit, writes = await install_sources(hass, audio_setup, monkeypatch)
    await emit(library_row())
    entity._source_generation = 1
    prior = entity._radio_catalogue.source_session('Local Library')
    current = entity._audio_metadata.get(7)
    incoming = replace(current, audio_path='library:local:track:new', position=10,
                       received_at=current.received_at + timedelta(seconds=1))
    receiver = entity._audio_metadata._client._receiver
    receiver._metadata[7] = incoming
    entity._update_audio_metadata()
    assert entity._radio_catalogue.source_session('Local Library') is prior
    receiver._metadata[7] = replace(incoming, position=11, received_at=incoming.received_at + timedelta(seconds=1))
    entity._update_audio_metadata()
    assert entity._radio_catalogue.source_session('Local Library').audio_path == incoming.audio_path
    assert not writes


@pytest.mark.asyncio
async def test_real_owner_manual_seek_rejects_new_snapshot_even_before_ui_listener(hass, audio_setup, monkeypatch):
    entity, row = await player(hass, audio_setup)
    checked = []

    async def transport(_client, player_id, seconds, *, is_current, on_send):
        receiver = entity._audio_metadata._client._receiver
        receiver._metadata[7] = replace(receiver._metadata[7], audio_path='spotify:track:new')
        checked.append(is_current())
        # Synthetic external boundary honours the same public current-state guard.
        if not checked[-1]:
            raise audioserver.AudioCommandError('Audio seek is no longer applicable to the current track')
        pytest.fail('An obsolete manual seek reached dispatch')

    monkeypatch.setattr(audioserver.AudioServerCommands, 'async_seek', transport)
    with pytest.raises(HomeAssistantError):
        await entity.async_media_seek(30)
    assert checked == [False]
    assert entity.media_position == row['time']
    assert entity._source_task is None and not entity._audio_commands.source_fences


def test_ha_clock_configuration_does_not_mutate_portable_default(monkeypatch):
    portable = SourceEnvironment()
    before = portable.clock()
    synthetic = before.replace(year=2040)
    monkeypatch.setattr(audio_sources.dt_util, 'utcnow', lambda: synthetic)
    assert audio_sources.environment.clock() == synthetic
    assert SourceEnvironment().clock().year == before.year
    assert portable.clock().year == before.year
