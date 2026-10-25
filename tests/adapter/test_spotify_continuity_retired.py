"""Synthetic review16 consumed bookmarks never poison later native-only no-ops."""

# ruff: noqa: S101, INP001, ANN001, D103, SLF001
from dataclasses import replace
from unittest.mock import AsyncMock

from aiohttp import ClientConnectionError
import pytest
from homeassistant.config_entries import ConfigEntryState
from test_spotify_continuity import NEXT, native
from test_spotify_continuity_conflicts import _saved


@pytest.mark.asyncio
@pytest.mark.parametrize("availability", ["unloaded", "disabled", "outage", "session-absent"])
@pytest.mark.parametrize("context", ["same", "new"])
async def test_confirmed_resume_retires_bookmark_and_history_before_optional_loss(hass, availability, context):
    entity, session, snapshots, commands = await _saved(hass)
    await entity.async_select_source("Spotify")
    assert all(method=='GET' for method,_,_ in session.calls)
    current = entity._radio_catalogue.source_choices["Spotify"]
    if context == "new":
        path = "spotify@native-owner:playlist:" + "D" * 22
        current = replace(current, folder=path, audio_path=path)
    parent = "spotify:playlist:" + ("D" if context == "new" else "C") * 22
    snapshots[0] = replace(native(), audio_path=NEXT, parent_id=parent)
    item = entity._radio_catalogue._item(current)
    # Emulate the real native-history discovery boundary without network access.
    entity._radio_catalogue.async_source_selection = AsyncMock(return_value=item.media_content_id)
    provider = hass.config_entries.async_get_entry("synthetic-entry")
    if availability == "unloaded":
        provider.state = ConfigEntryState.NOT_LOADED
    elif availability == "disabled":
        provider.disabled_by = "user"
    elif availability == "session-absent":
        provider.runtime_data.session = None
    else:
        session.async_request = AsyncMock(side_effect=ClientConnectionError("Synthetic optional provider outage"))
    for _ in range(2):
        await entity.async_select_source("Spotify")
    assert all(method=='GET' for method,_,_ in session.calls)
    commands.async_spotify_handoff.assert_awaited_once()
    commands.async_play_catalogue.assert_not_awaited()
    entity._radio_catalogue.async_source_selection.assert_not_awaited()
    assert entity._radio_catalogue.source_session('Spotify').audio_path==NEXT
    assert snapshots[0].audio_path == NEXT
    assert snapshots[0].parent_id == parent
