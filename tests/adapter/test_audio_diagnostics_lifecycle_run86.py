"""R85 correction lifecycle: unchanged bookmarks and honest cleanup failures."""
import asyncio
from unittest.mock import AsyncMock

import pytest
from homeassistant.util.file import WriteError
from custom_components.loxone import media_player, spotify_continuity, audio_sources
from custom_components.loxone import audio_diagnostics as module
from custom_components.loxone.const import DOMAIN
from test_audioserver_ha import audio_setup
from test_native_source_return_ha import install_sources, library_row
from test_audio_diagnostics_preference_run86 import setup, wait_for


async def test_preference_failure_recovery_keeps_existing_bookmark(hass, audio_setup, tmp_path, monkeypatch):
    hass.config.config_dir = str(tmp_path)
    entity, emit, writes = await install_sources(hass, audio_setup, monkeypatch)
    await emit(library_row())
    bookmark = entity._radio_catalogue.source_session('Local Library')
    assert bookmark.position == 45
    c = next(iter(hass.data[DOMAIN].values())).audio_diagnostics
    original = c.store._async_write_data
    await c.async_set_enabled(True)
    monkeypatch.setattr(c.store, '_async_write_data', AsyncMock(side_effect=WriteError('Synthetic ENOSPC')))
    await c.async_set_enabled(False)
    monkeypatch.setattr(c.store, '_async_write_data', original)
    c._preference_retry_at = c.hass.loop.time()-1
    c.wake.set()
    await wait_for(lambda: c.pending_preference is None)
    assert entity._radio_catalogue.source_session('Local Library') == bookmark
    assert writes == []
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


async def test_cleanup_unlink_failure_is_visible_not_success(hass, audio_setup, tmp_path, monkeypatch):
    _, c = await setup(hass, audio_setup, tmp_path)
    await c.async_set_enabled(False)
    pending = c.journal.path/'state.json.tmp'
    pending.write_bytes(b'{}')
    original = module.os.unlink
    def fail(path, *args, **kwargs):
        if str(path) == str(pending):
            raise PermissionError('Synthetic unlink denied')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(module.os, 'unlink', fail)
    await c.async_flush()
    assert pending.exists()
    assert c.status == 'storage_unavailable' and c.storage_failures > 0
    monkeypatch.setattr(module.os, 'unlink', original)
    await c.async_flush()
    assert not pending.exists() and c.status == 'off'


async def test_close_while_retry_in_flight_retires_owner(hass, audio_setup, tmp_path, monkeypatch):
    _, c = await setup(hass, audio_setup, tmp_path)
    original = c.store._async_write_data
    monkeypatch.setattr(c.store, '_async_write_data', AsyncMock(side_effect=WriteError('Synthetic ENOSPC')))
    await c.async_set_enabled(False)
    entered, release = asyncio.Event(), asyncio.Event()
    async def delayed(data):
        entered.set()
        await release.wait()
        await original(data)
    monkeypatch.setattr(c.store, '_async_write_data', delayed)
    c._preference_retry_at = c.hass.loop.time()-1
    c.wake.set()
    await asyncio.wait_for(entered.wait(), 3)
    close = asyncio.create_task(c.async_close())
    try:
        await asyncio.sleep(0)
        assert not close.done() and not c.enabled
    finally:
        release.set()
        await asyncio.wait_for(close, 3)
    assert c.closed and c._task.done() and c.pending_preference is False
    assert c.status == 'storage_unavailable'
