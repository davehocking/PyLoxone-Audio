"""Synthetic review15 optional loss, active progress and bounded preparation."""

# ruff: noqa: S101, INP001, ANN001, D103, SLF001
import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from test_spotify_continuity import CONTEXT, native
from test_spotify_continuity_conflicts import _saved
from test_spotify_continuity_review import entity_boundary
from custom_components.loxone import spotify_continuity as continuity
from custom_components.loxone.audio_radio import RadioTarget

PROGRESSED_SECONDS = 25.0


@pytest.mark.asyncio
async def test_successful_return_then_progress_and_provider_unload_is_repeated_native_noop(hass):
    entity, session, snapshots, commands = await _saved(hass)
    await entity.async_select_source("Spotify")
    assert all(method=='GET' for method,_,_ in session.calls)
    snapshots[0] = replace(native(), position=PROGRESSED_SECONDS)
    session.current["progress_ms"] = 25000
    provider = hass.config_entries.async_get_entry("synthetic-entry")
    provider.state = ConfigEntryState.NOT_LOADED
    target = entity._radio_catalogue.source_choices["Spotify"]
    item = entity._radio_catalogue._item(target)
    entity._radio_catalogue.async_source_selection = AsyncMock(return_value=item.media_content_id)
    for _ in range(2):
        await entity.async_select_source("Spotify")
    assert all(method=='GET' for method,_,_ in session.calls)
    commands.async_spotify_handoff.assert_awaited_once()
    commands.async_play_catalogue.assert_not_awaited()
    assert snapshots[0].position == PROGRESSED_SECONDS
    assert snapshots[0].parent_id == CONTEXT
    assert entity._radio_catalogue.source_session('Spotify').position==PROGRESSED_SECONDS


@pytest.mark.asyncio
@pytest.mark.parametrize("positive_conflict", [False, True])
async def test_absent_native_position_is_optional_but_positive_content_conflict_stays_hard(hass, positive_conflict):
    entity, session, snapshots, commands, _, _ = entity_boundary(hass)
    snapshots[0] = replace(native(), position=None)
    if positive_conflict:
        session.current["item"]["uri"] = "spotify:track:" + "B" * 22
    item = entity._radio_catalogue._item(
        RadioTarget("station", "Radio", "world", audio_path="tunein:station:synthetic")
    )
    await entity.async_play_media(item.media_content_type, item.media_content_id)
    commands.async_play_radio_station.assert_awaited_once()
    assert all(method == "GET" for method, _, _ in session.calls)
    assert entity._spotify_return.bookmark is None


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["capture", "resume"])
async def test_optional_account_lock_acquisition_is_inside_preparation_timeout(hass, phase):
    if phase == "resume":
        entity, session, _, commands = await _saved(hass)
        operation = entity.async_select_source("Spotify")
    else:
        entity, session, _, commands, _, _ = entity_boundary(hass)
        item = entity._radio_catalogue._item(
            RadioTarget("station", "Radio", "world", audio_path="tunein:station:synthetic")
        )
        operation = entity.async_play_media(item.media_content_type, item.media_content_id)
    bounded = SimpleNamespace(timeout=lambda _: asyncio.timeout(0.01), get_running_loop=asyncio.get_running_loop)
    async with entity._spotify_return._account["lock"]:
        with patch.object(continuity, "asyncio", bounded):
            await asyncio.wait_for(operation, 0.2)
    if phase == "capture":
        commands.async_play_radio_station.assert_awaited_once()
    else:
        commands.async_play_catalogue.assert_awaited_once()
    assert all(method == "GET" for method, _, _ in session.calls)
    assert not commands.source_fences
