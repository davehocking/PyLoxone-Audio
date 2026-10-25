"""The positively confirmed unlink commit cannot become unresolved afterwards."""

# ruff: noqa: S101, INP001, ANN001, ANN002, ANN003, ANN202, D103, PLR2004
import os
from pathlib import Path
import pytest
from test_spotify_continuity import module
from test_spotify_continuity_activation import detached_boundary


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["open", "fsync"])
async def test_post_unlink_failure_keeps_positive_commit_consistent_across_restart(hass, tmp_path, monkeypatch, fault):
    m = module()
    controller, session, _, _, _ = await detached_boundary(hass, tmp_path)
    original_open, original_sync = os.open, os.fsync
    injected = []

    def open_directory(path, *args, **kwargs):
        if (
            fault == "open"
            and Path(path) == session.journal
            and session.transfer_count
            and not list(session.journal.glob("fence-*.lock"))
        ):
            injected.append(fault)
            message = "Synthetic directory open failure after confirmed unlink"
            raise OSError(message)
        return original_open(path, *args, **kwargs)

    def fsync(descriptor):
        if (
            fault == "fsync"
            and (Path("/proc/self/fd") / str(descriptor)).readlink() == session.journal
            and session.transfer_count
            and not list(session.journal.glob("fence-*.lock"))
        ):
            injected.append(fault)
            message = "Synthetic directory sync failure after confirmed unlink"
            raise OSError(message)
        return original_sync(descriptor)

    monkeypatch.setattr(os, "open", open_directory)
    monkeypatch.setattr(os, "fsync", fsync)
    await controller.async_resume(lambda: True)
    assert injected == [fault]
    assert controller.bookmark is None
    assert not controller.uncertain
    assert len([c for c in session.calls if c[0] == "PUT"]) == 2
    for key in tuple(hass.data):
        if isinstance(key, str) and key.startswith("pyloxone_spotify_return"):
            hass.data.pop(key)
    await m.async_restore_dispatch_fences(hass)
    assert not m.spotify_room_uncertain(hass, "synthetic-room", 7)
