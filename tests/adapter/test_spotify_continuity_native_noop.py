"""Review22 real-source-selection no-ops and presentation-only bookmark changes."""

# ruff: noqa: S101, INP001, ANN001, D103, SLF001
from dataclasses import replace
from unittest.mock import AsyncMock

from aiohttp import ClientConnectionError
import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from test_spotify_continuity import NEXT, native
from test_spotify_continuity_conflicts import _saved
from custom_components.loxone import audio_sources


@pytest.mark.asyncio
@pytest.mark.parametrize("availability", ["unloaded", "disabled", "outage", "session-absent", "native-only"])
@pytest.mark.parametrize("active_context", ["advertised", "different"])
async def test_active_native_target_wins_over_different_recent_history_without_bookmark(
    hass, availability, active_context
):
    entity, session, snapshots, commands = await _saved(hass)
    await entity.async_select_source("Spotify")
    assert all(method=='GET' for method,_,_ in session.calls)
    session.calls.clear()
    current_parent = "spotify:playlist:" + ("C" if active_context == "advertised" else "D") * 22
    snapshots[0] = replace(native(), audio_path=NEXT, parent_id=current_parent)
    before = snapshots[0]
    history_id = "D" if active_context == "advertised" else "C"
    other_parent = "spotify:playlist:" + history_id * 22
    commands.async_recent_sources.return_value = {
        "items": [
            {
                "audiopath": "spotify@native-owner:playlist:" + history_id * 22,
                "type": 7,
                "title": "Other prior selection",
            }
        ]
    }

    async def play(_player, _service, _account, _path, *, is_current, on_send) -> None:
        assert is_current()
        on_send()
        snapshots[0] = replace(native(), parent_id=other_parent)

    commands.async_play_catalogue.side_effect = play
    provider = hass.config_entries.async_get_entry("synthetic-entry")
    if availability == "unloaded":
        provider.state = ConfigEntryState.NOT_LOADED
    elif availability == "disabled":
        provider.disabled_by = "user"
    elif availability == "session-absent":
        provider.runtime_data.session = None
    elif availability == "native-only":
        entity._spotify_return = None
    else:
        session.async_request = AsyncMock(side_effect=ClientConnectionError("Synthetic optional outage"))
    await entity.async_select_source("Spotify")
    commands.async_play_catalogue.assert_not_awaited()
    commands.async_recent_sources.assert_not_awaited()
    assert all(method == "GET" for method, _, _ in session.calls)
    assert snapshots[0] is before


@pytest.mark.asyncio
@pytest.mark.parametrize("identity", ["duplicate-user", "duplicate-id", "missing-user"])
async def test_native_source_noop_requires_a_unique_positive_account_label(hass, identity):
    entity, session, snapshots, commands = await _saved(hass)
    snapshots[0] = native()
    session.calls.clear()
    rows = commands.async_service_accounts.return_value
    if identity == "duplicate-user":
        rows.append({**rows[0], "id": "native-b"})
    elif identity == "duplicate-id":
        rows.append(dict(rows[0]))
    else:
        rows[0] = {**rows[0], "user": None}
    assert not await audio_sources.async_native_catalogue_noop(
        commands,
        entity._audio_metadata,
        7,
        entity._radio_catalogue.source_choices["Spotify"],
        is_available=lambda: True,
    )
    commands.async_play_catalogue.assert_not_awaited()
    assert not session.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("presentation", [{"label": "New title"}, {"thumbnail": "https://example.test/new.jpg"}])
async def test_presentation_only_update_retains_playback_bookmark(hass, presentation):
    entity, session, _, commands = await _saved(hass)
    saved = entity._radio_catalogue.source_session('Spotify')
    current = entity._radio_catalogue.source_choices["Spotify"]
    entity._radio_catalogue.source_choices["Spotify"] = replace(current, **presentation)
    assert entity._radio_catalogue.source_session('Spotify') is saved
    await entity.async_select_source("Spotify")
    assert all(method=='GET' for method,_,_ in session.calls)
    commands.async_spotify_handoff.assert_awaited_once()
    commands.async_play_catalogue.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("late", ["generation", "removed", "uncertainty", "native-change"])
async def test_bookmark_free_native_noop_rechecks_its_original_guards_after_inventory_read(hass, late):
    entity, session, snapshots, commands = await _saved(hass)
    await entity.async_select_source("Spotify")
    session.calls.clear()
    hass.config_entries.async_get_entry("synthetic-entry").state = ConfigEntryState.NOT_LOADED

    async def changed() -> list:
        if late == "generation":
            entity._source_generation += 1
        elif late == "removed":
            entity._audio_removed = True
        elif late == "uncertainty":
            # Relevant current native/announcement uncertainty, not retired
            # historical provider veto after a new explicit choice.
            commands.announcement_fences[7]=object()
        else:
            snapshots[0] = replace(native(), parent_id="spotify:playlist:" + "D" * 22)
        return commands.async_service_accounts.return_value

    commands.async_service_accounts.side_effect = changed
    with pytest.raises(HomeAssistantError):
        await entity.async_select_source("Spotify")
    commands.async_play_catalogue.assert_not_awaited()
    assert all(method == "GET" for method, _, _ in session.calls)
