"""Causality belongs to native position feedback, not a refreshed cached envelope."""

# ruff: noqa: S101, INP001, ANN001, ANN202, D103, SLF001, PLR2004
from dataclasses import replace
from datetime import timedelta

import pytest
from test_spotify_continuity import module
from test_spotify_continuity_activation import detached_boundary


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["settlement", "final-profile", "send-middleware"])
@pytest.mark.parametrize("clock", ["missing", "pre-transfer", "future", "stale-envelope"])
async def test_activation_requires_causal_position_feedback_through_play(hass, tmp_path, phase, clock):
    controller, session, snapshots, _, _ = await detached_boundary(hass, tmp_path)
    old = snapshots[0].received_at - timedelta(seconds=1)
    injected = False
    plays = []

    def inject():
        nonlocal injected
        injected = True
        now = snapshots[0].received_at
        changes = {
            "missing": {"position_updated_at": None},
            "pre-transfer": {"position_updated_at": old},
            "future": {"position_updated_at": now + timedelta(seconds=10)},
            "stale-envelope": {"received_at": old},
        }
        snapshots[0] = replace(snapshots[0], **changes[clock])

    async def observe(url):
        if session.transfer_count and phase == "final-profile" and url.endswith("/me"):
            inject()

    session.on_read = observe
    if phase == "settlement":
        async def after_transfer():
            inject()
        session.after_transfer = after_transfer
    original_request = session.async_request

    async def request(method, url, **kwargs):
        if phase == "send-middleware" and method == "PUT" and url.endswith("/play"):
            inject()
        return await original_request(method, url, **kwargs)

    session.async_request = request
    original_put = session.on_put

    async def play():
        plays.append(True)
        await original_put()

    session.on_put = play
    with pytest.raises(module().AudioCommandError):
        await controller.async_resume(lambda: True)
    assert injected and session.transfer_count == 1 and plays == [] and controller.uncertain
