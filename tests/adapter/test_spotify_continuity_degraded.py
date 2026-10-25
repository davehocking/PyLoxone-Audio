"""Synthetic review18 freshness loss and active no-ops without resume parsing."""

# ruff: noqa: S101, INP001, ANN001, D103, SLF001
from dataclasses import replace
from datetime import timedelta
import logging

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from test_spotify_continuity import native
from test_spotify_continuity_conflicts import _saved
from test_spotify_continuity_review import entity_boundary
from custom_components.loxone.audio_radio import RadioTarget
from custom_components.loxone.pyloxone_api.audioserver import AudioCommandError


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["capture", "resume"])
async def test_stale_unchanged_snapshot_only_disables_optional_enhancement(hass, caplog, phase):
    if phase == "capture":
        entity, session, snapshots, commands, _, _ = entity_boundary(hass)
        snapshots[0] = native(mode="pause")
        session.current["is_playing"] = False
        item = entity._radio_catalogue._item(
            RadioTarget("station", "Radio", "world", audio_path="tunein:station:synthetic")
        )
        operation = entity.async_play_media(item.media_content_type, item.media_content_id)
    else:
        entity, session, snapshots, commands = await _saved(hass)
        operation = entity.async_select_source("Spotify")
    snapshots[0] = replace(snapshots[0], received_at=dt_util.utcnow() - timedelta(seconds=6))
    await operation
    if phase == "capture":
        commands.async_play_radio_station.assert_awaited_once()
    else:
        commands.async_play_catalogue.assert_awaited_once()
    assert all(method == "GET" for method, _, _ in session.calls)
    assert entity._spotify_return.bookmark is None
    assert not [
        r for r in caplog.records if r.levelno >= logging.WARNING and r.name.startswith("custom_components.loxone")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("format_loss", ["episode", "duration", "progress", "flags"])
@pytest.mark.parametrize("ownership", ["owned", "foreign-device", "native-radio"])
async def test_active_native_noop_uses_identity_not_optional_resume_fields(hass, format_loss, ownership):
    entity, session, snapshots, commands, _, _ = entity_boundary(hass)
    if format_loss == "episode":
        uri = "spotify:episode:" + "E" * 22
        snapshots[0] = replace(native(), audio_path=uri)
        session.current["item"].update(uri=uri, type="episode")
        session.current["currently_playing_type"] = "episode"
    elif format_loss == "duration":
        session.current["item"]["duration_ms"] = None
    elif format_loss == "progress":
        session.current["progress_ms"] = None
    else:
        session.current["shuffle_state"] = None
    if ownership == "foreign-device":
        session.current["device"]["id"] = "foreign-synthetic-device"
    elif ownership == "native-radio":
        snapshots[0] = native("tunein:station:synthetic")
    if ownership == "owned":
        await entity.async_select_source("Spotify")
        assert entity._spotify_return.bookmark is None
        commands.async_spotify_handoff.assert_not_awaited()
    elif ownership=='foreign-device':
        with pytest.raises(HomeAssistantError):
            await entity.async_select_source("Spotify")
        commands.async_spotify_handoff.assert_not_awaited()
    else:
        # A valid provider-owned session may be explicitly returned from radio
        # without requiring optional context/clock/flags or restoring a queue.
        await entity.async_select_source('Spotify')
        commands.async_spotify_handoff.assert_awaited_once()
        assert snapshots[0].source=='Spotify'
    commands.async_play_catalogue.assert_not_awaited()
    commands.async_play_radio_station.assert_not_awaited()
    assert all(method == "GET" for method, _, _ in session.calls)


@pytest.mark.asyncio
async def test_post_send_freshness_loss_stays_uncertain_without_native_replay(hass):
    entity, session, snapshots, commands = await _saved(hass)
    session.update_native = False

    async def stale() -> None:
        snapshots[0] = replace(native(), received_at=dt_util.utcnow() - timedelta(seconds=6))

    session.on_put = stale
    # Direct retained-helper post-PUT coverage, not the current native path.
    with pytest.raises(AudioCommandError):
        await entity._spotify_return.async_resume(lambda:True)
    assert entity._spotify_return.uncertain
    assert sum(method == "PUT" for method, _, _ in session.calls) == 1
    commands.async_play_catalogue.assert_not_awaited()
