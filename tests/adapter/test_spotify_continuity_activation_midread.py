"""Observed bad native frames must not be rehabilitated by a later good frame."""

# ruff: noqa: S101, INP001, ANN001, ANN202, D103
import asyncio
from dataclasses import replace
import pytest
from test_spotify_continuity import module
from test_spotify_continuity_activation import detached_boundary


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["playback", "queue"])
@pytest.mark.parametrize("mutation", ["playing", "source"])
async def test_observed_midread_bad_native_frame_permanently_aborts(hass, tmp_path, phase, mutation):
    controller, session, snapshots, _, _ = await detached_boundary(hass, tmp_path)
    armed = False

    def restore(snapshot):
        snapshots[0] = snapshot

    async def read(url):
        nonlocal armed
        if not session.transfer_count:
            return
        playback = url.endswith("/me/player")
        if not armed and playback == (phase == "playback"):
            armed = True
            expected = snapshots[0]
            snapshots[0] = (
                replace(expected, native_mode="play") if mutation == "playing" else replace(expected, source="Line-In")
            )
            if phase == "queue":
                asyncio.get_running_loop().call_soon(restore, expected)
                session.on_read = None
        elif armed and phase == "playback" and url.endswith("/queue"):
            snapshots[0] = replace(snapshots[0], source="Spotify", native_mode="stop")
            session.on_read = None

    session.on_read = read
    with pytest.raises(module().AudioCommandError):
        await controller.async_resume(lambda: True)
    assert session.transfer_count == 1
    assert controller.uncertain
    assert not any(c[0] == "PUT" and c[1].endswith("/play") for c in session.calls)
