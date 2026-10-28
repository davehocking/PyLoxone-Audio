"""R85-03: real Store save/readback, honest pending OFF, bounded recovery.

Historical test_restart_preference.py remains immutable. Its old-bug status=off,
failures=0 setup is replaced here by pending/failure assertions, followed by
storage recovery and actual unload/setup (not impossible unwritable durability).
"""
import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.core import CoreState
from homeassistant.const import Platform
from homeassistant.helpers import entity_registry as er
from homeassistant.util.file import WriteError
from custom_components import loxone
from custom_components.loxone import media_player, spotify_continuity, audio_sources
from custom_components.loxone.const import DOMAIN
from test_audioserver_ha import audio_setup


async def setup(hass, audio_setup, tmp_path):
    hass.config.config_dir = str(tmp_path)
    entry = await audio_setup.setup(playback=True)
    collector = hass.data[DOMAIN][entry.entry_id].audio_diagnostics
    await collector.async_set_enabled(True)
    return entry, collector


async def wait_for(predicate):
    for _ in range(300):
        if predicate():
            return
        await asyncio.sleep(0.01)
    assert predicate()


async def test_failed_off_recovery_retry_actual_restart(hass, audio_setup, tmp_path, monkeypatch, hass_storage):
    monkeypatch.setattr(loxone, 'LOXONE_PLATFORMS', [Platform.MEDIA_PLAYER, Platform.SWITCH])
    entry, c = await setup(hass, audio_setup, tmp_path)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    owners = (coordinator.api, coordinator.audio_commands, coordinator.audio_metadata)
    opened = list(audio_setup.opened)
    reload = AsyncMock()
    monkeypatch.setattr(hass.config_entries, 'async_reload', reload)
    key, alias = c.store.key, c.emitter.alias('player', 7)
    original = c.store._async_write_data
    failure = AsyncMock(side_effect=WriteError('Synthetic ENOSPC'))
    monkeypatch.setattr(c.store, '_async_write_data', failure)
    await c.async_set_enabled(False)
    assert not c.enabled
    assert c.status == 'storage_unavailable'
    assert c.pending_preference is False and c.preference_restart_risk
    assert c.storage_failures == 1
    assert hass_storage[key]['data']['enabled'] is True
    report = await c.async_export()
    assert report['status'] == 'storage_unavailable'
    assert report['pending_preference'] is False and report['preference_restart_risk']
    assert report['storage_failures'] == 1
    switch = er.async_get(hass).async_get_entity_id('switch', DOMAIN, entry.entry_id+'_audio_diagnostics')
    state = hass.states.get(switch)
    assert state.state == 'off'
    assert state.attributes['pending_preference'] is False
    assert state.attributes['preference_restart_risk'] is True
    # Repeated wakeups/exports cannot retry before the monotonic deadline.
    for _ in range(3):
        c.wake.set()
        await c.async_export()
    await asyncio.sleep(0.3)
    assert failure.await_count == 1
    c._preference_retry_at = c.hass.loop.time() - 1
    c.wake.set()
    await wait_for(lambda: failure.await_count == 2)
    await wait_for(lambda: c.storage_failures == 2)
    assert c._preference_retry_at > c.hass.loop.time()
    monkeypatch.setattr(c.store, '_async_write_data', original)
    c._preference_retry_at = c.hass.loop.time() - 1
    c.wake.set()
    await wait_for(lambda: c.pending_preference is None)
    assert c.status == 'off' and not c.preference_restart_risk
    assert c.storage_failures == 2
    assert hass_storage[key]['data']['enabled'] is False
    assert hass.states.get(switch).attributes['pending_preference'] is None
    assert (coordinator.api, coordinator.audio_commands, coordinator.audio_metadata) == owners
    assert audio_setup.opened == opened
    coordinator.api.send_websocket_command.assert_not_awaited()
    reload.assert_not_awaited()
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    restarted = hass.data[DOMAIN][entry.entry_id].audio_diagnostics
    assert not restarted.enabled and restarted.pending_preference is None
    assert restarted.emitter.alias('player', 7) == alias


async def test_off_is_immediate_before_awaited_write(hass, audio_setup, tmp_path, monkeypatch):
    _, c = await setup(hass, audio_setup, tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    original = c.store._async_write_data
    async def delayed(data):
        entered.set()
        await release.wait()
        await original(data)
    monkeypatch.setattr(c.store, '_async_write_data', delayed)
    operation = asyncio.create_task(c.async_set_enabled(False))
    try:
        await entered.wait()
        assert not c.enabled
        assert c.pending_preference is False and c.preference_restart_risk
        size = c.queue.qsize()
        c.emit('feedback', player=7, position=123)
        assert c.queue.qsize() == size
    finally:
        release.set()
        await operation
    assert c.pending_preference is None


@pytest.mark.parametrize('fault', ['key', 'bool', 'read-error'])
async def test_exact_readback_not_save_return(hass, audio_setup, tmp_path, monkeypatch, hass_storage, fault):
    _, c = await setup(hass, audio_setup, tmp_path)
    original = c.store._async_write_data
    async def wrong(data):
        await original(data)
        saved = hass_storage[c.store.key]['data']
        if fault == 'key':
            saved['key'] = '0'*64
        elif fault == 'bool':
            saved['enabled'] = 0
    monkeypatch.setattr(c.store, '_async_write_data', wrong)
    if fault == 'read-error':
        monkeypatch.setattr(c.store, 'async_load', AsyncMock(side_effect=OSError('Synthetic read error')))
    await c.async_set_enabled(False)
    assert not c.enabled and c.pending_preference is False
    assert c.status == 'storage_unavailable' and c.storage_failures == 1
    await c.async_flush()
    assert (await c.async_export())['status'] == 'storage_unavailable'


async def test_stopping_deferred_store_data_is_not_confirmation(hass, audio_setup, tmp_path, monkeypatch, hass_storage):
    _, c = await setup(hass, audio_setup, tmp_path)
    saved_state = hass.state
    try:
        hass.state = CoreState.stopping
        await c.async_set_enabled(False)
        assert not c.enabled and c.pending_preference is False
        assert c.status == 'storage_unavailable' and c.storage_failures == 1
        assert hass_storage[c.store.key]['data']['enabled'] is True
        # Actual Store returns its deferred in-memory request; NOT disk evidence.
        assert (await c.store.async_load())['enabled'] is False
    finally:
        hass.state = saved_state
    c._preference_retry_at = c.hass.loop.time() - 1
    c.wake.set()
    await wait_for(lambda: c.pending_preference is None)
    assert hass_storage[c.store.key]['data']['enabled'] is False


async def test_newer_off_while_on_retry_waits_never_reenables(hass, audio_setup, tmp_path, monkeypatch, hass_storage):
    _, c = await setup(hass, audio_setup, tmp_path)
    await c.async_set_enabled(False)
    original = c.store._async_write_data
    monkeypatch.setattr(c.store, '_async_write_data', AsyncMock(side_effect=WriteError('Synthetic ENOSPC')))
    await c.async_set_enabled(True)
    entered, release = asyncio.Event(), asyncio.Event()
    writes = []
    async def delayed(data):
        writes.append(data['data']['enabled'])
        if len(writes) == 1:
            entered.set()
            await release.wait()
        await original(data)
    monkeypatch.setattr(c.store, '_async_write_data', delayed)
    c._preference_retry_at = c.hass.loop.time() - 1
    c.wake.set()
    await entered.wait()
    off = asyncio.create_task(c.async_set_enabled(False))
    try:
        await asyncio.sleep(0)
        assert not c.enabled and c.pending_preference is False
    finally:
        release.set()
        await off
    assert writes == [True, False]
    assert not c.enabled and c.pending_preference is None
    assert hass_storage[c.store.key]['data']['enabled'] is False


async def test_cancel_retains_write_ownership_and_close_retires_retry(hass, audio_setup, tmp_path, monkeypatch):
    _, c = await setup(hass, audio_setup, tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    original = c.store._async_write_data
    async def delayed(data):
        entered.set()
        await release.wait()
        await original(data)
    monkeypatch.setattr(c.store, '_async_write_data', delayed)
    operation = asyncio.create_task(c.async_set_enabled(False))
    close = None
    try:
        await entered.wait()
        operation.cancel()
        await asyncio.sleep(0)
        assert not operation.done(), 'In-flight Store ownership must not be abandoned'
        assert not c.enabled and c.pending_preference is False
        close = asyncio.create_task(c.async_close())
        await asyncio.sleep(0)
        assert not close.done()
    finally:
        release.set()
        results = await asyncio.gather(operation, *([] if close is None else [close]), return_exceptions=True)
    assert isinstance(results[0], asyncio.CancelledError)
    assert c.closed and c._task.done() and not c.enabled
    assert c.pending_preference is False and c.storage_failures >= 1
    writes = AsyncMock()
    monkeypatch.setattr(c.store, '_async_write_data', writes)
    await c.async_set_enabled(True)
    c.wake.set()
    await asyncio.sleep(0)
    writes.assert_not_awaited()


@pytest.mark.parametrize('saved', [None, {'enabled': True, 'key': []}, {'enabled': True, 'key': 'bad'}])
async def test_absent_corrupt_preference_stays_off(hass, audio_setup, tmp_path, monkeypatch, saved):
    from homeassistant.helpers.storage import Store
    original = Store.async_load
    async def load(store):
        if store.key.startswith('loxone_audio_diagnostics.'):
            return saved
        return await original(store)
    monkeypatch.setattr(Store, 'async_load', load)
    hass.config.config_dir = str(tmp_path)
    entry = await audio_setup.setup(playback=True)
    c = hass.data[DOMAIN][entry.entry_id].audio_diagnostics
    assert not c.enabled
