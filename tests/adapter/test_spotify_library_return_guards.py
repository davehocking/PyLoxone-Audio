"""Guard matrix for confirmed Library detours; synthetic provider/native only."""
# ruff: noqa: S101, SLF001, INP001, ANN001, ANN003, ANN202, D103, PLR2004
from dataclasses import replace
import asyncio
from datetime import timedelta

import pytest
from homeassistant.util import dt as dt_util
from custom_components.loxone.spotify_continuity import SpotifyReturnUnavailable
from custom_components.loxone.pyloxone_api.audioserver import AudioCommandError
from test_spotify_continuity import NEXT
from test_spotify_continuity_activation import detached_boundary


def library(snapshot, **changes):
    return replace(snapshot, source="Local Library", source_name=None,
                   audio_path="library:local:track:synthetic", parent_id="library:local:folder:synthetic",
                   position=45.0, duration=240.0, native_mode="play", **changes)


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["none", "stale", "player", "path", "event", "mode", "owner", "expired", "uncertain", "closed"])
async def test_unproved_library_departure_does_not_extend_activation_scope(hass, tmp_path, invalid):
    controller, session, snapshots, _commands, _entry = await detached_boundary(hass, tmp_path)
    snapshots[0] = library(snapshots[0])
    if invalid == "none":
        snapshots[0] = None
    elif invalid == "stale":
        snapshots[0] = replace(snapshots[0], received_at=dt_util.utcnow() - timedelta(seconds=6))
    elif invalid == "player":
        snapshots[0] = replace(snapshots[0], player_id=8)
    elif invalid == "path":
        snapshots[0] = replace(snapshots[0], audio_path="library:local:folder:synthetic")
    elif invalid == "event":
        snapshots[0] = replace(snapshots[0], event_active=True, event_idle=False)
    elif invalid == "mode":
        snapshots[0] = replace(snapshots[0], native_mode="pause")
    elif invalid == "owner":
        controller._account["owner"] = object()
    elif invalid == "expired":
        controller.bookmark = replace(controller.bookmark, captured=asyncio.get_running_loop().time() - 91)
    elif invalid == "uncertain":
        controller.uncertain = True
    else:
        controller.close()
    controller.remember_library_departure()
    assert controller._library_departure is None
    assert not [c for c in session.calls if c[0] == "PUT"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["track", "parent", "source", "mode", "bookmark", "invalidate", "capture"])
async def test_library_detour_witness_cannot_authorise_a_different_departure(hass, tmp_path, change):
    controller, session, snapshots, _commands, _entry = await detached_boundary(hass, tmp_path)
    snapshots[0] = library(snapshots[0])
    controller.remember_library_departure()
    saved = controller.bookmark
    assert controller._detached_source_supported(saved, snapshots[0])
    if change in ("track", "parent", "source", "mode"):
        field, value = {"track":("audio_path","library:local:track:other"), "parent":("parent_id","library:local:folder:other"),
                        "source":("source","LineIn"), "mode":("native_mode","pause")}[change]
        snapshots[0] = replace(snapshots[0], **{field:value})
        assert not controller._detached_source_supported(saved, snapshots[0])
    elif change == "bookmark":
        controller.bookmark = replace(saved)
        assert not controller._detached_source_supported(controller.bookmark, snapshots[0])
    elif change == "invalidate":
        controller.invalidate()
        assert controller._library_departure is None
    else:
        with pytest.raises(AudioCommandError):
            await controller.async_capture(lambda: True)
        assert controller._library_departure is None
    assert not [c for c in session.calls if c[0] == "PUT"]


@pytest.mark.asyncio
@pytest.mark.parametrize("conflict", ["track", "context", "queue", "progress", "native-owner", "native-event", "provider-loss", "disconnect", "library-clock"])
async def test_library_activation_never_plays_or_replays_after_conflict(hass, tmp_path, conflict):
    controller, session, snapshots, commands, _entry = await detached_boundary(hass, tmp_path)
    snapshots[0] = library(snapshots[0])
    departure = snapshots[0]
    controller.remember_library_departure()

    async def after():
        if conflict == "track":
            session.current["item"]["uri"] = NEXT
        elif conflict == "context":
            session.current["context"]["uri"] = "spotify:playlist:" + "Z" * 22
        elif conflict == "queue":
            session.queue["queue"] = [{"uri": NEXT}]
        elif conflict == "progress":
            session.current["progress_ms"] = 0
        elif conflict == "native-owner":
            snapshots[0] = replace(snapshots[0], source_name="other-owner")
        elif conflict == "native-event":
            snapshots[0] = replace(snapshots[0], event_active=True, event_idle=False)
        elif conflict == "provider-loss":
            session.current = None
        elif conflict == "library-clock":
            activated = snapshots[0]
            snapshots[0] = replace(departure, position=45.001)

            async def later_frame(_url):
                snapshots[0] = activated

            session.on_read = later_frame
        else:
            raise ConnectionResetError("synthetic transport loss")

    session.after_transfer = after
    with pytest.raises((AudioCommandError, TimeoutError, ConnectionResetError)):
        await controller.async_resume(lambda: True)
    assert session.transfer_count == 1
    assert len([c for c in session.calls if c[0] == "PUT"]) == 1
    assert controller.uncertain and commands.source_fences
    with pytest.raises(AudioCommandError):
        await controller.async_resume(lambda: True)
    assert len([c for c in session.calls if c[0] == "PUT"]) == 1


@pytest.mark.asyncio
async def test_library_label_and_http204_without_confirmed_detour_are_not_ownership(hass, tmp_path):
    controller, session, snapshots, _commands, _entry = await detached_boundary(hass, tmp_path)
    snapshots[0] = library(snapshots[0])
    with pytest.raises(SpotifyReturnUnavailable):
        await controller.async_resume(lambda: True)
    assert controller.bookmark is not None
    assert not [c for c in session.calls if c[0] == "PUT"]
