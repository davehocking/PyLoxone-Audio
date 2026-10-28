"""Synthetic provider/native boundaries, never household recordings or tokens."""

# ruff: noqa: S101, INP001, ANN001, ANN003, ANN202, D103, SLF001, PLC0415, PLR2004

import asyncio
from copy import deepcopy
from dataclasses import replace
from importlib import import_module, util
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.util import dt as dt_util

from custom_components.loxone.pyloxone_api.audioserver import AudioZoneMetadata

TRACK = "spotify:track:" + "A" * 22
NEXT = "spotify:track:" + "B" * 22
CONTEXT = "spotify:playlist:" + "C" * 22
DEVICE = "d" * 40
CONFIG = {
    "entry_id": "synthetic-entry",
    "user_id": "synthetic-owner",
    "account_id": "native-owner",
    "device_id": DEVICE,
}


def module():
    name = "custom_components.loxone.spotify_continuity"
    assert util.find_spec(name) is not None, "Room-owned Spotify transport return is not implemented"
    return import_module(name)


def native(path=TRACK, mode="play"):
    now = dt_util.utcnow()
    return AudioZoneMetadata(
        player_id=7,
        source="Spotify" if path == TRACK else "TuneIn",
        source_name="native-user",
        audio_path=path,
        parent_id=CONTEXT if path == TRACK else None,
        position=13.264 if path == TRACK else None,
        duration=180 if path == TRACK else None,
        native_mode=mode,
        playback_mode=mode,
        event_idle=True,
        event_active=False,
        received_at=now,
        position_updated_at=now,
    )


def playback():
    return {
        "device": {"id": DEVICE, "is_active": True, "is_restricted": False},
        "item": {"uri": TRACK, "duration_ms": 180000},
        "context": {"uri": CONTEXT},
        "progress_ms": 13264,
        "is_playing": True,
        "shuffle_state": False,
        "repeat_state": "context",
    }


class Session:
    """Only implements HA OAuth2Session's public interface; no token property."""

    def __init__(self, snapshot) -> None:
        """Provide synthetic state, never an authentication token."""
        self.snapshot = snapshot
        self.current = playback()
        # Preview deliberately includes a duplicate and a custom next item.
        self.queue = {"currently_playing": {"uri": TRACK}, "queue": [{"uri": NEXT}, {"uri": TRACK}, {"uri": NEXT}]}
        self.calls = []
        self.ensure = AsyncMock()
        self.on_put = None
        self.on_read = None
        self.update_native = True

    async def async_ensure_token_valid(self):
        """Record the public HA refresh boundary."""
        await self.ensure()

    async def async_request(self, method, url, **kwargs):
        """Implement only the public request/middleware contract."""
        self.calls.append((method, url, deepcopy(kwargs)))
        if method == "PUT":
            assert kwargs.get("params") == {"device_id": DEVICE}
            assert "json" not in kwargs
            assert "data" not in kwargs

            async def send(_request):
                if self.on_put:
                    await self.on_put()
                self.current = playback()
                self.current["progress_ms"] = 14081
                if self.update_native:
                    self.snapshot[0] = native()
                return SimpleNamespace(status=204, release=lambda: None)

            if kwargs.get("middlewares"):
                return await kwargs["middlewares"][0](None, send)
            return await send(None)
        if url.endswith("/me"):
            status, data = 200, {"id": "synthetic-owner"}
        elif url.endswith("/devices"):
            status, data = (
                200,
                {"devices": [{"id": DEVICE, "is_active": self.current is not None, "is_restricted": False}]},
            )
        elif url.endswith("/queue"):
            status, data = 200, deepcopy(self.queue)
        else:
            status, data = (200, deepcopy(self.current)) if self.current else (204, None)
        if method == "GET" and self.on_read:
            await self.on_read(url)
        return SimpleNamespace(status=status, json=AsyncMock(return_value=data), release=lambda: None)


def setup_boundary(hass):
    m = module()
    snapshot = [native()]
    session = Session(snapshot)
    entry = SimpleNamespace(
        entry_id="synthetic-entry",
        unique_id="synthetic-owner",
        domain="spotify",
        state=ConfigEntryState.LOADED,
        runtime_data=SimpleNamespace(session=session),
    )
    original_get = hass.config_entries.async_get_entry
    hass.config_entries.async_get_entry = lambda key: entry if key == entry.entry_id else original_get(key)
    commands = SimpleNamespace(
        async_service_accounts=AsyncMock(
            return_value=[{"cmd": "spotify", "id": "native-owner", "user": "native-user", "configerror": False}]
        ),
        source_fences={},
        announcement_fences={},
    )
    # A synthetic unrelated HA Spotify entry remains installed. Native callers
    # must never acquire its session or send provider requests in 0.1.1.
    return None, session, snapshot, commands, entry
