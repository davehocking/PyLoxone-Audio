"""Initial bounded transfer rewind differs from an observed later paused seek."""

# ruff: noqa: S101, INP001, ANN001, ANN003, ANN202, D103, PLR2004, PT018
from dataclasses import replace


import pytest
from test_spotify_continuity import module
from test_spotify_continuity_activation import detached_boundary


@pytest.mark.asyncio
@pytest.mark.parametrize(("evidence", "phase"), [
    ("provider", "settlement"), ("provider", "final-playback"),
    ("native", "settlement"), ("native", "final-playback"),
    ("native", "final-queue"), ("native", "send-middleware"),
])
async def test_paused_observation_change_cannot_rebase_settled_activation(hass, tmp_path, evidence, phase):
    controller, session, snapshots, _, _ = await detached_boundary(hass, tmp_path)
    reads = queues = 0
    injected = False
    healthy_native = None
    healthy_provider = None
    actual_plays = []
    original_request = session.async_request

    def inject():
        nonlocal injected, healthy_native, healthy_provider
        injected = True
        healthy_native = snapshots[0]
        healthy_provider = session.current["progress_ms"]
        if evidence == "provider":
            session.current["progress_ms"] += 1000
        else:
            snapshots[0] = replace(snapshots[0], position=snapshots[0].position + 1)

    async def request(method, url, **kwargs):
        nonlocal reads, queues
        if session.transfer_count:
            if method == "GET" and url.endswith("/me/player"):
                reads += 1
            if method == "GET" and url.endswith("/queue"):
                queues += 1
            if not injected and ((phase == "settlement" and url.endswith("/me/player") and reads == 2)
                or (phase == "final-playback" and url.endswith("/me/player") and reads == 3)
                or (phase == "final-queue" and url.endswith("/queue") and queues == 3)
                or (phase == "send-middleware" and method == "PUT" and url.endswith("/play"))):
                inject()
            elif injected and method == "GET":
                # Later healthy evidence cannot rehabilitate an observed conflict.
                snapshots[0] = healthy_native
                session.current["progress_ms"] = healthy_provider
        return await original_request(method, url, **kwargs)

    session.async_request = request
    original_put = session.on_put

    async def play():
        actual_plays.append(True)
        await original_put()

    session.on_put = play
    with pytest.raises(module().AudioCommandError):
        await controller.async_resume(lambda: True)
    assert injected and session.transfer_count == 1 and actual_plays == []
    assert controller.uncertain
    snapshots[0] = healthy_native
    session.current["progress_ms"] = healthy_provider
    with pytest.raises(module().AudioCommandError):
        await controller.async_resume(lambda: True)
    assert session.transfer_count == 1 and actual_plays == []


@pytest.mark.asyncio
@pytest.mark.parametrize("rewind_ms", [1000, 2236])
async def test_initial_bounded_rewind_is_accepted_without_rebasing_later_changes(hass, tmp_path, rewind_ms):
    controller, session, snapshots, _, _ = await detached_boundary(hass, tmp_path)

    async def after_transfer():
        session.current["progress_ms"] -= rewind_ms
        snapshots[0] = replace(snapshots[0], position=session.current["progress_ms"] / 1000)

    session.after_transfer = after_transfer
    await controller.async_resume(lambda: True)
    assert session.transfer_count == 1 and not controller.uncertain and controller.bookmark is None
