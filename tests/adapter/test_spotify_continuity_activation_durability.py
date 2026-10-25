"""First-use journal directory ancestry must be durable before provider dispatch."""

# ruff: noqa: S101, INP001, ANN001, ANN202, D103
import os
from pathlib import Path
import pytest
from test_spotify_continuity_activation import detached_boundary


@pytest.mark.asyncio
@pytest.mark.parametrize("storage_exists", [False, True])
async def test_directory_parent_fsync_precedes_first_provider_send(hass, tmp_path, monkeypatch, storage_exists):
    controller, session, _, _, _ = await detached_boundary(hass, tmp_path)
    storage = tmp_path / ".storage"
    if storage_exists:
        storage.mkdir()
    synced = set()
    original = os.fsync

    def sync(descriptor):
        synced.add((Path("/proc/self/fd") / str(descriptor)).readlink())
        return original(descriptor)

    monkeypatch.setattr(os, "fsync", sync)

    async def before_server_accepts():
        assert storage in synced, "Journal directory parent was not fsynced before send"
        if not storage_exists:
            assert tmp_path in synced, "New .storage parent was not fsynced before send"

    session.after_transfer = before_server_accepts
    await controller.async_resume(lambda: True)
    assert session.transfer_count == 1
    assert not controller.uncertain
