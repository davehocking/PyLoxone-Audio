"""Durable journal IO and absence controls; synthetic identities, no network."""

# ruff: noqa: S101, INP001, ANN001, ANN002, ANN202, D103, SLF001, PLR2004, ASYNC240
import asyncio
from pathlib import Path
import pytest
from test_spotify_continuity import module
from test_spotify_continuity_activation import detached_boundary


@pytest.mark.asyncio
async def test_absent_journal_restores_once_and_remains_native_only_quiet(hass, tmp_path, monkeypatch, caplog):
    m = module()
    hass.config.config_dir = str(tmp_path)
    reads = []
    original = m._read_dispatch_fences

    def tracked(directory):
        reads.append(directory)
        return original(directory)

    monkeypatch.setattr(m, "_read_dispatch_fences", tracked)
    await asyncio.gather(m.async_restore_dispatch_fences(hass), m.async_restore_dispatch_fences(hass))
    assert len(reads) == 1
    assert not m.spotify_room_uncertain(hass, "synthetic-room", 7)
    assert not (tmp_path / ".storage" / "pyloxone_spotify_return_dispatch").exists()
    assert not [r for r in caplog.records if r.name.startswith("custom_components.loxone") and r.levelno >= 30]


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["{", "[]", "null", "{}"])
async def test_unreadable_uncertainty_journal_is_not_optional_absence(hass, tmp_path, content):
    m = module()
    hass.config.config_dir = str(tmp_path)
    directory = Path(hass.config.path(".storage", "pyloxone_spotify_return_dispatch"))
    directory.mkdir(parents=True)
    (directory / ("fence-" + "a" * 64 + ".lock")).write_text(content)
    await m.async_restore_dispatch_fences(hass)
    assert m.spotify_room_uncertain(hass, "synthetic-room", 7)
