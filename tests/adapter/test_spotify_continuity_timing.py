"""Synthetic review17 elapsed capture clocks and native dispatch latency."""

# ruff: noqa: S101, INP001, ANN001, D103, SLF001
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from test_spotify_continuity import native
from test_spotify_continuity_review import entity_boundary, seed_last_good
from custom_components.loxone.pyloxone_api.audioserver import AudioCommandError
from custom_components.loxone import spotify_continuity as continuity
from custom_components.loxone.audio_radio import RadioTarget


@pytest.mark.asyncio
@pytest.mark.parametrize("delay", ["profile", "queue", "both", "first-response"])
async def test_healthy_advancing_playback_during_capture_never_breaks_native_radio(hass, delay):
    entity, session, snapshots, commands, _, _ = entity_boundary(hass)
    clock = [dt_util.utcnow()]
    snapshots[0] = replace(native(), received_at=clock[0], position_updated_at=clock[0])
    first_player = True

    async def advance(url) -> None:
        nonlocal first_player
        should_advance = (
            (url.endswith("/me") and delay in ("profile", "both"))
            or (url.endswith("/queue") and delay in ("queue", "both"))
            or (url.endswith("/me/player") and first_player and delay == "first-response")
        )
        if url.endswith("/me/player"):
            first_player = False
        if should_advance:
            clock[0] += timedelta(seconds=4)
            session.current["progress_ms"] += 4000
            snapshots[0] = replace(
                native(),
                position=session.current["progress_ms"] / 1000,
                received_at=clock[0],
                position_updated_at=clock[0],
            )

    session.on_read = advance
    item = entity._radio_catalogue._item(
        RadioTarget("station", "Radio", "world", audio_path="tunein:station:synthetic")
    )
    # New wire samples need distinct timestamp objects, even at the same time.
    with patch.object(continuity.dt_util, "utcnow", lambda: clock[0] + timedelta()):
        # Direct retained-helper timing coverage, not a departure prerequisite.
        await entity._spotify_return.async_capture(lambda:True)
        await entity.async_play_media(item.media_content_type, item.media_content_id)
    commands.async_play_radio_station.assert_awaited_once()
    assert all(method == "GET" for method, _, _ in session.calls)
    assert entity._spotify_return.bookmark.progress_ms == session.current["progress_ms"]
    assert not commands.source_fences


@pytest.mark.asyncio
async def test_native_dispatch_latency_discards_stale_clock_before_any_future_provider_resume(hass):
    entity, session, snapshots, commands, _, _ = entity_boundary(hass)
    seed_last_good(entity,snapshots[0])
    saved=entity._radio_catalogue.source_session('Spotify')
    original = commands.async_play_radio_station.side_effect

    async def delayed(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        session.current["progress_ms"] += 4000
        await original(*args, **kwargs)

    commands.async_play_radio_station.side_effect = delayed
    item = entity._radio_catalogue._item(
        RadioTarget("station", "Radio", "world", audio_path="tunein:station:synthetic")
    )
    await entity.async_play_media(item.media_content_type, item.media_content_id)
    assert entity._spotify_return.bookmark is None
    assert entity._radio_catalogue.source_session('Spotify') is saved
    assert saved.position==13.264  # Provider/time alone is not new native proof.
    commands.async_play_radio_station.assert_awaited_once()
    await entity.async_select_source('Spotify')
    commands.async_spotify_handoff.assert_awaited_once()
    commands.async_play_catalogue.assert_not_awaited()
    assert snapshots[0].position==17.264
    assert all(method == "GET" for method, _, _ in session.calls)


@pytest.mark.asyncio
async def test_missing_playing_clock_anchor_quietly_disables_bookmark_not_radio(hass):
    entity, session, snapshots, commands, _, _ = entity_boundary(hass)
    snapshots[0] = replace(native(), position_updated_at=None)
    item = entity._radio_catalogue._item(
        RadioTarget("station", "Radio", "world", audio_path="tunein:station:synthetic")
    )
    await entity.async_play_media(item.media_content_type, item.media_content_id)
    assert entity._spotify_return.bookmark is None
    commands.async_play_radio_station.assert_awaited_once()
    assert all(method == "GET" for method, _, _ in session.calls)


@pytest.mark.asyncio
async def test_elapsed_time_does_not_hide_positive_forward_seek(hass):
    entity, session, snapshots, commands, _, _ = entity_boundary(hass)
    clock = [dt_util.utcnow()]
    snapshots[0] = replace(native(), position_updated_at=clock[0], received_at=clock[0])

    async def change(url) -> None:
        if url.endswith("/me"):
            clock[0] += timedelta(seconds=4)
            snapshots[0] = replace(native(), position_updated_at=clock[0], received_at=clock[0])
            session.current["progress_ms"] = 40000

    session.on_read = change
    item = entity._radio_catalogue._item(
        RadioTarget("station", "Radio", "world", audio_path="tunein:station:synthetic")
    )
    with patch.object(continuity.dt_util, "utcnow", lambda: clock[0] + timedelta()), pytest.raises(AudioCommandError):
        await entity._spotify_return.async_capture(lambda:True)
    commands.async_play_radio_station.assert_not_awaited()
    assert all(method == "GET" for method, _, _ in session.calls)
