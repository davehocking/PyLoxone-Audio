"""Cancellation after positive restoration must settle its durable commit consistently."""

# ruff: noqa: S101, INP001, ANN001, ANN002, ANN202, D103, PLR2004, SLF001
import asyncio
import threading
import pytest
from test_spotify_continuity import module
from test_spotify_continuity_activation import detached_boundary


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_twice", [False, True])
async def test_confirmed_commit_finishes_before_cancellation_releases_ownership(
    hass, tmp_path, monkeypatch, cancel_twice
):
    m = module()
    controller, session, _, _, _ = await detached_boundary(hass, tmp_path)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = m._clear_dispatch_fence

    def slow_commit(*args):
        entered.set()
        assert release.wait(5)
        try:
            return original(*args)
        finally:
            finished.set()

    monkeypatch.setattr(m, "_clear_dispatch_fence", slow_commit)
    task = asyncio.create_task(controller.async_resume(lambda: True))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        task.cancel()
        await asyncio.sleep(0)
        if cancel_twice:
            controller.invalidate()
            task.cancel()
            await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await asyncio.to_thread(finished.wait, 3)
    finally:
        release.set()
    assert controller.bookmark is None
    assert not controller.uncertain
    assert len([c for c in session.calls if c[0] == "PUT"]) == 2
    for key in tuple(hass.data):
        if isinstance(key, str) and key.startswith("pyloxone_spotify_return"):
            hass.data.pop(key)
    await m.async_restore_dispatch_fences(hass)
    assert not m.spotify_room_uncertain(hass, "synthetic-room", 7)


@pytest.mark.asyncio
async def test_cancelled_failed_commit_keeps_runtime_and_restart_uncertainty(hass, tmp_path, monkeypatch):
    m = module()
    controller, session, _, _, _ = await detached_boundary(hass, tmp_path)
    entered, release = threading.Event(), threading.Event()

    def failed_commit(*_args):
        entered.set()
        assert release.wait(5)
        message = "Synthetic durable commit failure"
        raise OSError(message)

    monkeypatch.setattr(m, "_clear_dispatch_fence", failed_commit)
    task = asyncio.create_task(controller.async_resume(lambda: True))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        task.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
    assert controller.uncertain
    assert len([c for c in session.calls if c[0] == "PUT"]) == 2
    for key in tuple(hass.data):
        if isinstance(key, str) and key.startswith("pyloxone_spotify_return"):
            hass.data.pop(key)
    await m.async_restore_dispatch_fences(hass)
    assert m.spotify_room_uncertain(hass, "synthetic-room", 7)
