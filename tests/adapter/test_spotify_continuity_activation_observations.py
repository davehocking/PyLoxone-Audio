"""Every final observation must permanently reject an observed competing seek."""

# ruff: noqa: S101, INP001, ANN001, ANN202, D103, PLR2004, SLF001
from dataclasses import replace
import pytest
from test_spotify_continuity import module
from test_spotify_continuity_activation import detached_boundary


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["profile", "native-user", "playback"])
async def test_final_observations_cannot_rehabilitate_a_contradictory_position(hass, tmp_path, phase):
    controller, session, snapshots, _, _ = await detached_boundary(hass, tmp_path)
    reads = 0
    changed = False
    healthy = None
    original_user = controller._native_user

    async def native_user():
        nonlocal changed, healthy
        value = await original_user()
        if phase == "native-user" and session.transfer_count:
            changed = True
            healthy = snapshots[0]
            snapshots[0] = replace(snapshots[0], position=32.556)
        return value

    controller._native_user = native_user

    async def observation(url):
        nonlocal reads, changed, healthy
        if not session.transfer_count:
            return
        if changed:
            assert healthy is not None
            snapshots[0] = healthy
            session.on_read = None
            return
        if url.endswith("/me/player"):
            reads += 1
        if (phase == "profile" and url.endswith("/me")) or (
            phase == "playback" and url.endswith("/me/player") and reads == 3
        ):
            changed = True
            healthy = snapshots[0]
            snapshots[0] = replace(snapshots[0], position=32.556)

    session.on_read = observation
    with pytest.raises(module().AudioCommandError):
        await controller.async_resume(lambda: True)
    assert session.transfer_count == 1
    assert controller.uncertain
    assert not any(c[0] == "PUT" and c[1].endswith("/play") for c in session.calls)
