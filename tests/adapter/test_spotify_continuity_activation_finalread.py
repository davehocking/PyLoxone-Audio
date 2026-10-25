"""Pre-Play validation must retain the activation guard after loop settlement."""

# ruff: noqa: S101, INP001, ANN001, ANN202, D103
from dataclasses import replace
import pytest
from test_spotify_continuity import module
from test_spotify_continuity_activation import detached_boundary


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["playing", "source"])
async def test_final_activation_reads_cannot_hide_observed_bad_native_frame(hass, tmp_path, mutation):
    controller, session, snapshots, _, _ = await detached_boundary(hass, tmp_path)
    reads = 0
    final_read = 3

    async def observe(url):
        nonlocal reads
        if not session.transfer_count:
            return
        if url.endswith("/me/player"):
            reads += 1
            if reads == final_read:
                snapshots[0] = (
                    replace(snapshots[0], native_mode="play")
                    if mutation == "playing"
                    else replace(snapshots[0], source="Line-In")
                )
        elif reads == final_read and url.endswith("/queue"):
            snapshots[0] = replace(snapshots[0], source="Spotify", native_mode="stop")
            session.on_read = None

    session.on_read = observe
    with pytest.raises(module().AudioCommandError):
        await controller.async_resume(lambda: True)
    assert session.transfer_count == 1
    assert controller.uncertain
    assert not any(c[0] == "PUT" and c[1].endswith("/play") for c in session.calls)
