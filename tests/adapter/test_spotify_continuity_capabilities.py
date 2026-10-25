"""Synthetic review14 optional malformed evidence versus positive conflicts."""

# ruff: noqa: S101, INP001, ANN001, ANN003, ANN202, D103, SLF001
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
import logging

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from test_spotify_continuity import DEVICE, NEXT, TRACK, native
from test_spotify_continuity_conflicts import _saved
from test_spotify_continuity_review import entity_boundary
from custom_components.loxone.audio_radio import RadioTarget
from custom_components.loxone.pyloxone_api.audioserver import AudioCommandError


CASES = [
    ("me", None),
    ("me", {}),
    ("me", {"id": None}),
    ("me", {"id": 7}),
    ("playback-device", None),
    ("playback-device", {}),
    ("playback-device", {"id": None}),
    ("playback-device", {"id": 7}),
    ("me/player/devices", {}),
    ("me/player/devices", {"devices": None}),
    ("me/player/devices", {"devices": True}),
    ("me/player/devices", {"devices": [None]}),
    ("me/player/devices", {"devices": [{"id": DEVICE, "is_restricted": False}]}),
    ("me/player/devices", {"devices": [None] * 129}),
]


def _override(session, endpoint, payload, on_response=None) -> None:
    original = session.async_request

    async def response(method, url, **kwargs):
        reply = await original(method, url, **kwargs)
        if method == "GET" and url.endswith("/" + endpoint):
            if on_response is not None:
                await on_response()
            return SimpleNamespace(status=200, json=AsyncMock(return_value=deepcopy(payload)), release=lambda: None)
        return reply

    session.async_request = response


@pytest.mark.asyncio
@pytest.mark.parametrize(("endpoint", "payload"), CASES)
async def test_malformed_optional_identity_resumes_quiet_native_without_put(hass, caplog, endpoint, payload):
    entity, session, _, commands = await _saved(hass)
    if endpoint == "playback-device":
        session.current["device"] = payload
    else:
        _override(session, endpoint, payload)
    await entity.async_select_source("Spotify")
    if endpoint=='me/player/devices':
        commands.async_spotify_handoff.assert_awaited_once()
        commands.async_play_catalogue.assert_not_awaited()
    else:
        commands.async_play_catalogue.assert_awaited_once()
    assert all(method == "GET" for method, _, _ in session.calls)
    assert not [
        r for r in caplog.records if r.levelno >= logging.WARNING and r.name.startswith("custom_components.loxone")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(("endpoint", "payload"), CASES[:8])
async def test_malformed_capture_identity_preserves_discovered_radio(hass, caplog, endpoint, payload):
    entity, session, _, commands, _, _ = entity_boundary(hass)
    session.current["is_playing"] = False
    if endpoint == "playback-device":
        session.current["device"] = payload
    else:
        _override(session, endpoint, payload)
    item = entity._radio_catalogue._item(
        RadioTarget("station", "Radio", "world", audio_path="tunein:station:synthetic")
    )
    await entity.async_play_media(item.media_content_type, item.media_content_id)
    commands.async_play_radio_station.assert_awaited_once()
    assert entity._spotify_return.bookmark is None
    assert all(method == "GET" for method, _, _ in session.calls)
    assert not [
        r for r in caplog.records if r.levelno >= logging.WARNING and r.name.startswith("custom_components.loxone")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("identity", ["profile", "device", "inventory", "mixed-inventory", "oversized-inventory"])
async def test_explicit_foreign_identity_is_not_optional_unavailability(hass, identity):
    entity, session, _, commands = await _saved(hass)
    if identity == "profile":
        _override(session, "me", {"id": "another-provider-owner"})
    elif identity == "device":
        session.current["device"]["id"] = "another-provider-device"
    else:
        rows = [{"id": "another-provider-device", "is_active": True, "is_restricted": False}]
        if identity == "mixed-inventory":
            rows.append(None)
        elif identity == "oversized-inventory":
            rows = [None] * 129 + rows
        _override(session, "me/player/devices", {"devices": rows})
    if 'inventory' in identity:
        # Inventory is a retained transfer-helper boundary, never a new
        # prerequisite for the native session. Keep its foreign-owner control.
        with pytest.raises(AudioCommandError):
            await entity._spotify_return.async_resume(lambda:True)
    else:
        with pytest.raises(HomeAssistantError):
            await entity.async_select_source("Spotify")
    commands.async_play_catalogue.assert_not_awaited()
    assert all(method == "GET" for method, _, _ in session.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["stop", "source"])
async def test_malformed_optional_identity_cannot_bypass_supersession(hass, change):
    entity, session, snapshots, commands = await _saved(hass)
    commands.async_execute = AsyncMock()

    async def supersede() -> None:
        if change == "stop":
            # Independent external Stop feedback during the pending read.
            snapshots[0]=replace(snapshots[0],native_mode='stop')
        else:
            snapshots[0] = native("tunein:station:newer-owner-choice")

    _override(session, "me", {}, supersede)
    with pytest.raises(HomeAssistantError):
        await entity.async_select_source("Spotify")
    commands.async_play_catalogue.assert_not_awaited()
    assert all(method == "GET" for method, _, _ in session.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("capability", ["profile", "playback-device", "inventory", "native-account", "unloaded"])
async def test_optional_absence_never_hides_observed_superseded_native_bookmark(hass, capability):
    entity, session, snapshots, commands = await _saved(hass)
    snapshots[0] = replace(native(mode="pause"), audio_path=NEXT)
    if capability == "profile":
        _override(session, "me", {})
    elif capability == "playback-device":
        session.current["device"] = {}
    elif capability == "inventory":
        _override(session, "me/player/devices", {"devices": None})
    elif capability == "native-account":
        commands.async_service_accounts.side_effect = AudioCommandError("Synthetic optional read failure")
    else:
        hass.config_entries.async_get_entry("synthetic-entry").state = ConfigEntryState.NOT_LOADED
    if capability in ("profile", "playback-device", "unloaded", "inventory"):
        # Optional loss cannot revive old A over the valid native NEXT session.
        await entity.async_select_source('Spotify')
        commands.async_spotify_handoff.assert_awaited_once()
        assert snapshots[0].audio_path==NEXT
    else:
        with pytest.raises(HomeAssistantError):
            await entity.async_select_source("Spotify")
    commands.async_play_catalogue.assert_not_awaited()
    assert all(method == "GET" for method, _, _ in session.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("positive", [True, False])
async def test_oversized_queue_retains_observable_conflict_but_only_capability_loss_is_quiet(hass, positive):
    entity, session, _, commands = await _saved(hass)
    session.queue["queue"] = [None] * 1001
    session.queue["currently_playing"] = None
    if positive:
        session.queue["queue"][0] = {"uri": TRACK}
        with pytest.raises(AudioCommandError):
            await entity._spotify_return.async_resume(lambda:True)
        commands.async_play_catalogue.assert_not_awaited()
    else:
        await entity.async_select_source("Spotify")
        commands.async_spotify_handoff.assert_awaited_once()
        commands.async_play_catalogue.assert_not_awaited()
    assert all(method == "GET" for method, _, _ in session.calls)
