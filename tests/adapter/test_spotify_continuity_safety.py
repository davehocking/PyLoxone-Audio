"""Synthetic review11 conflicts, inherited uncertainty and removed-action guards."""

# ruff: noqa: S101, INP001, ANN001, D103, SLF001
import asyncio
import logging
from copy import deepcopy
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from homeassistant.exceptions import HomeAssistantError
from test_spotify_continuity import NEXT, native
from test_spotify_continuity_review import entity_boundary
from custom_components.loxone.pyloxone_api import audioserver as wire
from custom_components.loxone.audio_radio import RadioTarget
from custom_components.loxone.spotify_continuity import spotify_room_uncertain








@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action", ["async_media_stop", "async_set_volume_level", "async_volume_up", "async_volume_down"]
)
async def test_removed_entity_never_sends_stop_or_volume(hass, monkeypatch, action):
    entity, _, _, _, _, _ = entity_boundary(hass)
    await entity.async_will_remove_from_hass()
    fire = MagicMock()
    monkeypatch.setattr(type(hass.bus), "async_fire", fire)
    with pytest.raises(HomeAssistantError):
        await getattr(entity, action)(*([0.05] if action == "async_set_volume_level" else []))
    fire.assert_not_called()
