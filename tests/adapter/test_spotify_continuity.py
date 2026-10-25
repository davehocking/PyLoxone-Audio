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
    controller = m.SpotifySourceReturn(
        hass, m.SpotifyBinding.parse(CONFIG), "synthetic-room", 7, commands, lambda: snapshot[0]
    )
    return controller, session, snapshot, commands, entry


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["capture", "resume"])
async def test_native_selection_change_during_provider_reads_rejects_without_write(hass, phase):
    from dataclasses import replace

    controller, session, snapshot, _, _ = setup_boundary(hass)
    if phase == "resume":
        await controller.async_capture(lambda: True)
        snapshot[0] = native("tunein:station:synthetic")
        session.current["is_playing"] = False

    async def changed(url):
        if url.endswith("/me/player"):
            snapshot[0] = replace(snapshot[0], source_name="another-native-owner")

    session.on_read = changed
    operation = controller.async_capture if phase == "capture" else controller.async_resume
    with pytest.raises(module().AudioCommandError):
        await operation(lambda: True)
    assert all(method == "GET" for method, _, _ in session.calls)
    if phase == "capture":
        assert controller.bookmark is None


@pytest.mark.asyncio
async def test_room_return_preserves_custom_duplicate_preview_and_offset_without_context_start(hass):
    controller, session, snapshot, commands, _ = setup_boundary(hass)
    await controller.async_capture(lambda: True)
    saved = controller.bookmark
    snapshot[0] = native("tunein:station:synthetic")
    session.current["is_playing"] = False
    await controller.async_resume(lambda: True)
    writes = [c for c in session.calls if c[0] != "GET"]
    assert len(writes) == 1
    method, url, kwargs = writes[0]
    assert (method, url) == ("PUT", "https://api.spotify.com/v1/me/player/play")
    assert set(kwargs) == {"params", "allow_redirects", "middlewares"}
    assert kwargs["params"] == {"device_id": DEVICE}
    assert kwargs["allow_redirects"] is False
    assert len(kwargs["middlewares"]) == 1
    assert callable(kwargs["middlewares"][0])
    assert tuple(item["uri"] for item in session.queue["queue"]) == saved.queue == (NEXT, TRACK, NEXT)
    assert saved.progress_ms == 13264
    assert controller.bookmark is None
    assert not commands.source_fences
    assert snapshot[0].audio_path == TRACK


@pytest.mark.asyncio
async def test_changed_available_queue_preview_rejected_before_resume_write(hass):
    controller, session, snapshot, _, _ = setup_boundary(hass)
    await controller.async_capture(lambda: True)
    snapshot[0] = native("tunein:station:synthetic")
    session.current["is_playing"] = False
    session.queue["queue"].reverse()
    session.queue["queue"].append({"uri": TRACK})
    with pytest.raises((ValueError, module().AudioCommandError)):
        await controller.async_resume(lambda: True)
    assert all(method == "GET" for method, _, _ in session.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[], "invalid", 7, True])
async def test_malformed_provider_playback_has_controlled_validation_error(hass, payload):
    controller, session, _, _, _ = setup_boundary(hass)
    session.current = payload
    with pytest.raises((ValueError, module().AudioCommandError)):
        await controller.async_resume(lambda: True)
    assert all(method == "GET" for method, _, _ in session.calls)


@pytest.mark.asyncio
async def test_disabled_optional_entry_is_not_used_even_if_unload_is_pending(hass):
    controller, session, _, _, provider = setup_boundary(hass)
    provider.disabled_by = "user"
    with pytest.raises(module().AudioCommandError):
        await controller.async_resume(lambda: True)
    assert not session.calls


@pytest.mark.asyncio
async def test_already_active_exact_account_source_is_noop_not_rewind(hass):
    controller, session, _, _, _ = setup_boundary(hass)
    await controller.async_resume(lambda: True)
    assert all(method == "GET" for method, _, _ in session.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("fence", ["source_fences", "announcement_fences"])
async def test_existing_player_fence_blocks_provider_action(hass, fence):
    controller, session, _, commands, _ = setup_boundary(hass)
    getattr(commands, fence)[7] = object()
    with pytest.raises(module().AudioCommandError):
        await controller.async_resume(lambda: True)
    assert not session.calls


@pytest.mark.asyncio
async def test_removal_during_final_queue_read_cannot_report_success(hass):
    controller, session, snapshot, _, _ = setup_boundary(hass)
    await controller.async_capture(lambda: True)
    snapshot[0] = native("tunein:station:synthetic")
    session.current["is_playing"] = False

    async def remove(url):
        if url.endswith("/queue") and controller.uncertain:
            controller.close()

    session.on_read = remove
    with pytest.raises(module().AudioCommandError):
        await controller.async_resume(lambda: True)
    assert controller.uncertain


@pytest.mark.asyncio
async def test_pre_send_spotify_frame_cannot_confirm_resume(hass):
    controller, session, snapshot, _, _ = setup_boundary(hass)
    await controller.async_capture(lambda: True)
    old_playing = snapshot[0]
    snapshot[0] = replace(old_playing, native_mode="pause", playback_mode="pause")
    session.current["is_playing"] = False
    session.update_native = False

    async def restore_old_frame():
        snapshot[0] = old_playing

    session.on_put = restore_old_frame
    # A retained old playing frame is NOT new post-send evidence, even if
    # it appears after dispatch. Already-playing native sources now no-op
    # without dispatch, so begin with an actually paused native session.
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.05):
            await controller.async_resume(lambda: True)
    assert controller.uncertain
    with pytest.raises(module().AudioCommandError):
        await controller.async_resume(lambda: True)
    assert sum(method == "PUT" for method, _, _ in session.calls) == 1


@pytest.mark.asyncio
async def test_uncertain_send_survives_entity_removal_and_recreation(hass):
    controller, session, snapshot, commands, _ = setup_boundary(hass)
    await controller.async_capture(lambda: True)
    snapshot[0] = native("tunein:station:synthetic")
    session.current["is_playing"] = False
    session.update_native = False
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.05):
            await controller.async_resume(lambda: True)
    assert controller.uncertain
    fence = commands.source_fences[7]
    controller.close()
    assert commands.source_fences.get(7) is fence
    replacement = module().SpotifySourceReturn(
        hass, controller.binding, controller.room, 7, commands, lambda: snapshot[0]
    )
    assert replacement.uncertain
    # A whole command-client unload may release its fence, not replay authority.
    fence()
    with pytest.raises(module().AudioCommandError):
        await replacement.async_resume(lambda: True)
    assert sum(method == "PUT" for method, _, _ in session.calls) == 1


@pytest.mark.asyncio
async def test_foreign_session_arriving_during_device_discovery_prevents_write(hass):
    controller, session, snapshot, _, _ = setup_boundary(hass)
    await controller.async_capture(lambda: True)
    snapshot[0] = native("tunein:station:synthetic")
    session.current["is_playing"] = False

    async def foreign(url):
        if url.endswith("/devices"):
            session.current = playback()
            session.current["device"]["id"] = "foreign-device"

    session.on_read = foreign
    with pytest.raises(module().AudioCommandError):
        await controller.async_resume(lambda: True)
    assert all(method == "GET" for method, _, _ in session.calls)


@pytest.mark.asyncio
async def test_active_noop_must_match_native_account_not_just_same_track(hass):
    from dataclasses import replace

    controller, session, snapshot, _, _ = setup_boundary(hass)
    snapshot[0] = replace(snapshot[0], source_name="unrelated-native-user")
    with pytest.raises(module().AudioCommandError):
        await controller.async_resume(lambda: True)
    assert all(method == "GET" for method, _, _ in session.calls)


@pytest.mark.asyncio
async def test_new_native_source_during_final_queue_read_cannot_confirm_old_frame(hass):
    controller, session, snapshot, _, _ = setup_boundary(hass)
    await controller.async_capture(lambda: True)
    snapshot[0] = native("tunein:station:synthetic")
    session.current["is_playing"] = False

    async def changed(url):
        if url.endswith("/queue") and controller.uncertain:
            snapshot[0] = native("tunein:station:someone-else")

    session.on_read = changed
    with pytest.raises(module().AudioCommandError):
        await controller.async_resume(lambda: True)
    assert controller.uncertain


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    ["stale", "missing", "wrong-device", "wrong-account", "unloaded", "changed-track", "other-room", "announcement"],
)
async def test_saved_session_rejects_missing_stale_or_foreign_ownership_without_write(hass, case):
    from dataclasses import replace

    controller, session, snapshot, commands, entry = setup_boundary(hass)
    await controller.async_capture(lambda: True)
    snapshot[0] = native("tunein:station:synthetic")
    if case == "stale":
        controller.bookmark = replace(controller.bookmark, captured=controller.bookmark.captured - 91)
    elif case == "missing":
        snapshot[0] = None
    elif case == "wrong-device":
        session.current["device"]["id"] = "another-device"
    elif case == "wrong-account":
        entry.unique_id = "another-account"
    elif case == "unloaded":
        entry.state = ConfigEntryState.NOT_LOADED
    elif case == "changed-track":
        session.current["item"]["uri"] = NEXT
    elif case == "other-room":
        controller._account["owner"] = object()
    else:
        commands.announcement_fences[7] = object()
    with pytest.raises(module().AudioCommandError):
        await controller.async_resume(lambda: True)
    assert all(method == "GET" for method, _, _ in session.calls)
