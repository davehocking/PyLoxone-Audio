"""Real source-action outcomes and fixed warnings without development traces."""
# ruff: noqa: S101, INP001, ANN001, D103, SLF001
import logging
import json
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError
from test_spotify_continuity_conflicts import _saved
from test_spotify_continuity_review import entity_boundary
from test_spotify_continuity import native
from custom_components.loxone.audio_radio import RadioTarget
from custom_components.loxone.pyloxone_api.audioserver import AudioCommandError
from custom_components.loxone.pyloxone_api import audioserver as wire


@pytest.mark.asyncio
async def test_actual_source_entity_reports_positive_foreign_ownership_before_any_send(hass, caplog):
    entity, session, _, commands = await _saved(hass)
    session.current['device']['id'] = 'foreign-device'
    caplog.set_level(logging.DEBUG, logger='custom_components.loxone.media_player')
    handoffs_before = commands.async_spotify_handoff.await_count
    with pytest.raises(HomeAssistantError):
        await entity.async_select_source('Spotify')
    messages = [r.getMessage() for r in caplog.records if r.name == 'custom_components.loxone.media_player']
    assert not hasattr(entity, '_audio_last_source_failure')
    assert any('Audio source selection failed' in m for m in messages)
    assert all(method == 'GET' for method, _, _ in session.calls)
    commands.async_play_catalogue.assert_not_awaited()
    assert commands.async_spotify_handoff.await_count == handoffs_before
    assert 'foreign-device' not in '\n'.join(messages)


@pytest.mark.asyncio
async def test_ambiguous_native_send_and_subsequent_refusal_are_distinguishable_without_replay(hass, caplog):
    entity, _, snapshots, commands, _, _ = entity_boundary(hass, binding=None)
    snapshots[0] = native('tunein:station:before', mode='stop')
    target = entity._radio_catalogue._item(RadioTarget('station', 'Synthetic', 'world', audio_path='tunein:station:next'))
    calls = []

    async def uncertain(_player, _service, _path, *, is_current, on_send):
        assert is_current()
        on_send()
        calls.append(True)
        raise AudioCommandError('https://secret.invalid/?token=DO_NOT_LOG')

    commands.async_play_radio_station.side_effect = uncertain
    caplog.set_level(logging.DEBUG, logger='custom_components.loxone.audio_diagnostics')
    for _ in range(2):
        with pytest.raises(HomeAssistantError):
            await entity.async_play_media(target.media_content_type, target.media_content_id)
    messages = [r.getMessage() for r in caplog.records if r.name.endswith('audio_diagnostics')]
    assert len(calls) == 2 and 7 in commands.source_fences
    assert not messages
    assert not any('reason=native_fence' in m for m in messages)
    assert 'DO_NOT_LOG' not in '\n'.join(messages)
    assert 'secret.invalid' not in '\n'.join(messages)


@pytest.mark.asyncio
async def test_debug_disabled_does_not_emit_source_trace(hass, caplog):
    entity, session, _, _ = await _saved(hass)
    caplog.set_level(logging.INFO, logger='custom_components.loxone.audio_diagnostics')
    await entity.async_select_source('Spotify')
    assert not [r for r in caplog.records if r.name.endswith('audio_diagnostics')]
    assert sum(method == 'PUT' for method, _, _ in session.calls) == 0
    entity._audio_commands.async_spotify_handoff.assert_awaited_once()


@pytest.mark.asyncio
async def test_real_native_send_echo_and_exact_feedback_are_separate_stages(hass, caplog, monkeypatch):
    entity, _, snapshots, commands, _, _ = entity_boundary(hass, binding=None)
    snapshots[0] = native('tunein:station:before', mode='stop')
    owner = wire.AudioServerCommands('audio.example.invalid', lambda: ('synthetic', 'synthetic-token'))
    commands.source_observations = owner.source_observations
    commands.async_play_radio_station = owner.async_play_radio_station
    socket = AsyncMock()
    socket.__aenter__.return_value = socket
    sent = []

    async def send(command):
        sent.append(command)
        snapshots[0] = native('tunein:station:after')

    async def receive():
        return json.dumps({'command': sent[-1]})

    socket.send.side_effect = send
    socket.recv.side_effect = receive
    monkeypatch.setattr(wire, 'connect', lambda *args, **kwargs: socket)
    monkeypatch.setattr(owner, '_authenticate', AsyncMock())
    target = entity._radio_catalogue._item(RadioTarget('station', 'Synthetic', 'world', audio_path='tunein:station:after'))
    caplog.set_level(logging.DEBUG, logger='custom_components.loxone.audio_diagnostics')
    await entity.async_play_media(target.media_content_type, target.media_content_id)
    messages = [r.getMessage() for r in caplog.records if r.name.endswith('audio_diagnostics')]
    assert len(sent) == 1 and not commands.source_fences
    assert not messages
    assert 'synthetic-token' not in '\n'.join(messages)
    await owner.async_close()
