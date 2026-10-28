"""Additional R85-03 timer and unwritable-restart limitation controls."""
import asyncio
from unittest.mock import AsyncMock

from homeassistant.util.file import WriteError
from custom_components.loxone import media_player, spotify_continuity, audio_sources
from custom_components.loxone.const import DOMAIN
from test_audioserver_ha import audio_setup
from test_audio_diagnostics_preference_run86 import setup


async def test_real_housekeeping_timeout_retries_without_event_or_export(hass, audio_setup, tmp_path, monkeypatch, hass_storage):
    _, c = await setup(hass, audio_setup, tmp_path)
    original = c.store._async_write_data
    monkeypatch.setattr(c.store, '_async_write_data', AsyncMock(side_effect=WriteError('Synthetic ENOSPC')))
    await c.async_set_enabled(False)
    assert c.pending_preference is False and c.storage_failures == 1
    monkeypatch.setattr(c.store, '_async_write_data', original)
    started = c.hass.loop.time()
    # Real writer timeout and real monotonic deadline: no deadline mutation,
    # no event wake, export, request or sleep patch to drive the retry.
    while c.pending_preference is not None and c.hass.loop.time()-started < 65:
        await asyncio.sleep(0.1)
    elapsed = c.hass.loop.time()-started
    assert elapsed >= 59
    assert c.pending_preference is None and not c.enabled
    assert c.status == 'off' and c.storage_failures == 1
    assert hass_storage[c.store.key]['data']['enabled'] is False


async def test_unwritable_off_restart_can_restore_old_on_honestly(hass, audio_setup, tmp_path, monkeypatch, hass_storage):
    entry, c = await setup(hass, audio_setup, tmp_path)
    monkeypatch.setattr(c.store, '_async_write_data', AsyncMock(side_effect=WriteError('Synthetic ENOSPC')))
    await c.async_set_enabled(False)
    assert not c.enabled and c.pending_preference is False
    assert c.preference_restart_risk and c.status == 'storage_unavailable'
    assert hass_storage[c.store.key]['data']['enabled'] is True
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    restarted = hass.data[DOMAIN][entry.entry_id].audio_diagnostics
    assert restarted.enabled, 'Unwritable storage cannot guarantee persistent OFF'
