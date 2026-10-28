"""Synthetic single-track shape, derived from read-only native schema (no user IDs)."""
# Assertions, private guards and synthetic counts are intentional.
# ruff: noqa: S101, SLF001, PLR2004, INP001

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest
from homeassistant.util import dt as dt_util
from custom_components.loxone.pyloxone_api.audioserver import AudioCommandError
from test_spotify_continuity import NEXT, TRACK, native, setup_boundary
from test_spotify_continuity_review import entity_boundary

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant




@pytest.mark.asyncio
async def test_contextless_native_active_source_selection_is_noop(hass: HomeAssistant) -> None:
    """Selecting the same active self-parent track must not start it again."""
    entity, session, snapshots, commands, _provider, _target = entity_boundary(hass)
    snapshots[0] = replace(snapshots[0], parent_id=TRACK)
    session.current["context"] = None

    await entity.async_select_source("Spotify")

    assert all(method == "GET" for method, _url, _kwargs in session.calls)
    commands.async_play_catalogue.assert_not_awaited()
