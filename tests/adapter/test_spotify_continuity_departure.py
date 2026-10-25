"""Synthetic review19 departure lifetime, response age and explicit null context."""

# ruff: noqa: S101, INP001, ANN001, D103, SLF001
import asyncio
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from test_spotify_continuity import NEXT, native
from test_spotify_continuity_review import entity_boundary
from custom_components.loxone import media_player, spotify_continuity as continuity
from custom_components.loxone.audio_radio import RadioTarget
from custom_components.loxone.pyloxone_api.audioserver import AudioCommandError

FINAL_READ = 2


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["rejected", "cancelled"])
async def test_failed_native_departure_retires_capture_before_optional_loss(hass, failure):
    entity, session, snapshots, commands, provider, old = entity_boundary(hass)
    item = entity._radio_catalogue._item(
        RadioTarget("station", "Radio", "world", audio_path="tunein:station:synthetic")
    )
    error = (
        AudioCommandError("Synthetic native preparation rejection")
        if failure == "rejected"
        else asyncio.CancelledError()
    )
    with (
        patch.object(media_player.audio_sources, "async_select_radio_station", AsyncMock(side_effect=error)),
        pytest.raises(HomeAssistantError if failure == "rejected" else asyncio.CancelledError),
    ):
        await entity.async_play_media(item.media_content_type, item.media_content_id)
    snapshots[0] = replace(native(), audio_path=NEXT)
    provider.state = ConfigEntryState.NOT_LOADED
    current = entity._radio_catalogue._item(old)
    entity._radio_catalogue.async_source_selection = AsyncMock(return_value=current.media_content_id)
    await entity.async_select_source("Spotify")
    assert entity._spotify_return.bookmark is None
    assert snapshots[0].audio_path==NEXT
    commands.async_play_catalogue.assert_not_awaited()
    commands.async_play_radio_station.assert_not_awaited()
    assert all(method == "GET" for method, _, _ in session.calls)


@pytest.mark.asyncio
async def test_old_final_response_measurement_cannot_be_retained_as_new_capture(hass):
    entity, session, snapshots, commands, _, _ = entity_boundary(hass)
    clock = [dt_util.utcnow()]
    mono = [0.0]
    reads = 0

    async def delayed(url) -> None:
        nonlocal reads
        if url.endswith("/me/player"):
            reads += 1
            if reads == FINAL_READ:
                clock[0] += timedelta(seconds=4)
                mono[0] += 4
                session.current["progress_ms"] += 4000
                snapshots[0] = replace(native(), position=session.current["progress_ms"] / 1000)

    session.on_read = delayed
    bounded = SimpleNamespace(
        timeout=asyncio.timeout,
        sleep=asyncio.sleep,
        get_running_loop=lambda: SimpleNamespace(time=lambda: mono[0]),
    )
    item = entity._radio_catalogue._item(
        RadioTarget("station", "Radio", "world", audio_path="tunein:station:synthetic")
    )
    with (
        patch.object(continuity, "asyncio", bounded),
        patch.object(continuity.dt_util, "utcnow", lambda: clock[0] + timedelta()),
    ):
        await entity._spotify_return.async_capture(lambda:True)
        measured=entity._spotify_return.bookmark
        assert measured.captured==0.0  # Earliest measurement, NOT response time 4.
        assert measured.progress_ms==13264<session.current['progress_ms']
        await entity.async_play_media(item.media_content_type, item.media_content_id)
    commands.async_play_radio_station.assert_awaited_once()
    assert entity._spotify_return.bookmark is measured  # Dormant helper, not new success.
    assert reads==FINAL_READ
    assert all(method == "GET" for method, _, _ in session.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("context", ["initial-omitted", "final-omitted", "explicit-null"])
async def test_contextless_bookmark_requires_explicit_null_not_missing_context(hass, context):
    entity, session, snapshots, commands, _, old = entity_boundary(hass)
    snapshots[0] = replace(native(), parent_id=None)
    session.current["context"] = None
    await entity._spotify_return.async_capture(lambda: True)
    entity._spotify_choice = ("Spotify", old)
    snapshots[0] = native("tunein:station:synthetic")
    session.current["is_playing"] = False
    original = session.async_request

    async def request(method, url, **kwargs):  # noqa: ANN003, ANN202
        result = await original(method, url, **kwargs)
        if method == "PUT":
            session.current["context"] = None
            snapshots[0] = replace(native(), parent_id=None)
        return result

    session.async_request = request
    if context == "initial-omitted":
        session.current.pop("context")
    elif context == "final-omitted":

        async def omit() -> None:
            session.current.pop("context")

        async def during_read(_url):
            if 'context' in session.current:await omit()
        session.on_read=during_read
    await entity.async_select_source("Spotify")
    puts = [method for method, _, _ in session.calls if method == "PUT"]
    assert puts == []
    commands.async_spotify_handoff.assert_awaited_once()
    commands.async_play_catalogue.assert_not_awaited()
    assert snapshots[0].parent_id is None
