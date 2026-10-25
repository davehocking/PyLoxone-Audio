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
async def test_native_self_parent_allows_provider_contextless_capture(hass: HomeAssistant) -> None:
    """A native one-track container is not a Spotify playlist context."""
    controller, session, snapshots, _commands, _entry = setup_boundary(hass)
    snapshots[0] = replace(snapshots[0], parent_id=TRACK)
    session.current["context"] = None

    await controller.async_capture(lambda: True)

    assert controller.bookmark is not None
    assert controller.bookmark.track == TRACK
    assert controller.bookmark.context is None
    assert all(method == "GET" for method, _url, _kwargs in session.calls)


@pytest.mark.asyncio
async def test_contextless_native_active_source_selection_is_noop(hass: HomeAssistant) -> None:
    """Selecting the same active self-parent track must not start it again."""
    entity, session, snapshots, commands, _provider, _target = entity_boundary(hass)
    snapshots[0] = replace(snapshots[0], parent_id=TRACK)
    session.current["context"] = None

    await entity.async_select_source("Spotify")

    assert all(method == "GET" for method, _url, _kwargs in session.calls)
    commands.async_play_catalogue.assert_not_awaited()


@pytest.mark.asyncio
async def test_contextless_bookmark_accepts_unchanged_native_paused_identity(hass: HomeAssistant) -> None:
    """A self-parent wrapper must not invalidate the exact captured track."""
    controller, session, snapshots, _commands, _entry = setup_boundary(hass)
    snapshots[0] = replace(snapshots[0], parent_id=TRACK)
    session.current["context"] = None
    await controller.async_capture(lambda: True)
    saved = controller.bookmark
    snapshots[0] = replace(snapshots[0], native_mode="pause")

    controller.reject_native_conflict(snapshots[0])

    assert controller.bookmark is saved
    assert saved.context is None


@pytest.mark.asyncio
async def test_contextless_resume_confirms_self_parent_without_restarting_context(hass: HomeAssistant) -> None:
    """Return preserves exact track/preview/position using bodyless Play only."""
    controller, session, snapshots, _commands, _entry = setup_boundary(hass)
    snapshots[0] = replace(snapshots[0], parent_id=TRACK)
    session.current["context"] = None
    await controller.async_capture(lambda: True)
    saved = controller.bookmark
    snapshots[0] = native("tunein:station:synthetic")
    session.current["is_playing"] = False
    request = session.async_request

    async def contextless_request(method: str, url: str, **kwargs: Any) -> Any:
        response = await request(method, url, **kwargs)
        if method == "PUT":
            session.current["context"] = None
            snapshots[0] = replace(snapshots[0], parent_id=TRACK)
        return response

    session.async_request = contextless_request
    await controller.async_resume(lambda: True)

    writes = [call for call in session.calls if call[0] != "GET"]
    assert len(writes) == 1
    assert writes[0][1].endswith("/me/player/play")
    assert "data" not in writes[0][2]
    assert "json" not in writes[0][2]
    assert tuple(row["uri"] for row in session.queue["queue"]) == saved.queue
    assert session.current["progress_ms"] == 14081
    assert controller.bookmark is None
    assert not controller.uncertain


@pytest.mark.asyncio
async def test_contextless_activation_requires_same_track_stopped_fresh_frame(hass: HomeAssistant) -> None:
    """Exact post-transfer frame recognises only the track's self wrapper."""
    controller, session, snapshots, _commands, _entry = setup_boundary(hass)
    snapshots[0] = replace(snapshots[0], parent_id=TRACK)
    session.current["context"] = None
    await controller.async_capture(lambda: True)
    sent_at = dt_util.utcnow()
    snapshots[0] = replace(native(mode="stop"), parent_id=TRACK)

    assert controller._activation_native(snapshots[0], controller.bookmark, sent_at)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "conflict", ["track", "playlist", "foreign-device", "foreign-profile", "native-owner", "queue"]
)
async def test_single_track_wrapper_never_masks_positive_conflicts(hass: HomeAssistant, conflict: str) -> None:
    """The wrapper exception changes no account, content, queue or room guard."""
    controller, session, snapshots, _commands, entry = setup_boundary(hass)
    snapshots[0] = replace(snapshots[0], parent_id=TRACK)
    session.current["context"] = None
    if conflict == "track":
        session.current["item"]["uri"] = NEXT
    elif conflict == "playlist":
        session.current["context"] = {"uri": "spotify:playlist:" + "C" * 22}
    elif conflict == "foreign-device":
        session.current["device"]["id"] = "another-device"
    elif conflict == "foreign-profile":
        entry.unique_id = "another-account"
    elif conflict == "native-owner":

        async def change(_url: str) -> None:
            snapshots[0] = replace(snapshots[0], source_name="another-native-owner")

        session.on_read = change
    else:
        session.queue["currently_playing"]["uri"] = NEXT

    with pytest.raises((AudioCommandError, ValueError)):
        await controller.async_capture(lambda: True)

    assert controller.bookmark is None
    assert all(method == "GET" for method, _url, _kwargs in session.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["track", "parent", "owner", "seek", "stop-generation", "event"])
async def test_single_track_saved_bookmark_preserves_newer_action_refusals(hass: HomeAssistant, change: str) -> None:
    """A captured null context gives no authority over a newer native action."""
    controller, session, snapshots, _commands, _entry = setup_boundary(hass)
    snapshots[0] = replace(snapshots[0], parent_id=TRACK)
    session.current["context"] = None
    await controller.async_capture(lambda: True)
    snapshots[0] = replace(snapshots[0], native_mode="pause")
    session.current["is_playing"] = False
    if change == "track":
        snapshots[0] = replace(snapshots[0], audio_path=NEXT, parent_id=NEXT)
    elif change == "parent":
        snapshots[0] = replace(snapshots[0], parent_id="spotify:album:" + "D" * 22)
    elif change == "owner":
        snapshots[0] = replace(snapshots[0], source_name="another-native-owner")
    elif change == "seek":
        snapshots[0] = replace(snapshots[0], position=60)
    elif change == "event":
        snapshots[0] = replace(snapshots[0], event_active=True, event_idle=False)
    else:

        async def stopped(_url: str) -> None:
            controller.invalidate()

        session.on_read = stopped

    with pytest.raises((AudioCommandError, ValueError)):
        await controller.async_resume(lambda: True)

    assert all(method == "GET" for method, _url, _kwargs in session.calls)
