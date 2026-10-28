"""Optional source-history recovery through deliberate native browsing."""

# Synthetic player IDs and explicit fixture re-exports are intentional.
# ruff: noqa: S101, INP001, ANN001, D103, SLF001, PLR2004

import asyncio
from unittest.mock import AsyncMock

import pytest
from homeassistant.components.media_player import MediaPlayerEntityFeature

from test_audioserver_ha import audio_setup as audio_setup, zone_entity_id  # noqa: PLC0414 - explicit pytest fixture re-export
from custom_components.loxone.const import DOMAIN
from custom_components.loxone.pyloxone_api import audioserver as wire


@pytest.mark.asyncio
async def test_browse_recovers_history_after_optional_startup_timeout(
    hass, audio_setup, monkeypatch
):
    attempts = {7: 0, 8: 0}

    async def recent(player) -> dict:
        attempts[player] += 1
        if player == 7 and attempts[player] == 1:
            raise TimeoutError
        return {"items": [{
            "audiopath": "tunein:station:synthetic", "title": "Synthetic radio", "type": 2
        }], "ts": 1}

    monkeypatch.setattr(wire.AudioServerCommands, "async_recent_sources", AsyncMock(side_effect=recent))
    await audio_setup.setup(playback=True)
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    assert entity.source_list is None
    assert "TuneIn" in entity._radio_catalogue.source_descriptors
    assert entity.supported_features & MediaPlayerEntityFeature.SELECT_SOURCE
    assert not entity._radio_catalogue.source_choices
    assert entity.supported_features & MediaPlayerEntityFeature.BROWSE_MEDIA
    assert (await entity.async_browse_media()).children
    assert entity.source_list == ["TuneIn"]
    assert "TuneIn" in entity._radio_catalogue.source_choices
    assert entity.supported_features & MediaPlayerEntityFeature.SELECT_SOURCE
    assert attempts == {7: 2, 8: 1}
    # Successful empty or populated discovery must not become permanent polling.
    assert (await entity.async_browse_media()).children
    assert attempts == {7: 2, 8: 1}
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_persistent_history_failure_keeps_browse_and_retries_only_on_request(
    hass, audio_setup, monkeypatch
):
    history = AsyncMock(side_effect=TimeoutError("Synthetic persistent discovery failure"))
    monkeypatch.setattr(wire.AudioServerCommands, "async_recent_sources", history)
    await audio_setup.setup(playback=True)
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    initial_reads = history.await_count
    assert (await entity.async_browse_media()).children
    assert history.await_count == initial_reads + 1
    await hass.async_block_till_done()
    assert history.await_count == initial_reads + 1
    assert entity.source_list is None
    assert "TuneIn" in entity._radio_catalogue.source_descriptors
    assert not entity._radio_catalogue.source_choices
    assert entity.supported_features & MediaPlayerEntityFeature.PLAY_MEDIA
    assert (await entity.async_browse_media()).children
    assert history.await_count == initial_reads + 2
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_genuinely_empty_history_does_not_trigger_repeated_discovery(
    hass, audio_setup, monkeypatch
):
    history = AsyncMock(return_value={"items": [], "ts": 1})
    monkeypatch.setattr(wire.AudioServerCommands, "async_recent_sources", history)
    await audio_setup.setup(playback=True)
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    initial_reads = history.await_count
    for _ in range(3):
        assert (await entity.async_browse_media()).children
    assert history.await_count == initial_reads
    assert entity.source_list is None
    assert "TuneIn" in entity._radio_catalogue.source_descriptors
    assert not entity._radio_catalogue.source_choices
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_unload_cancels_pending_history_recovery_and_closes_listeners(
    hass, audio_setup, monkeypatch
):
    started = asyncio.Event()
    attempts = {7: 0, 8: 0}

    async def recent(player) -> dict:
        attempts[player] += 1
        if player == 7:
            if attempts[player] == 1:
                raise TimeoutError
            started.set()
            await asyncio.Future()
        return {"items": [], "ts": 1}

    monkeypatch.setattr(wire.AudioServerCommands, "async_recent_sources", AsyncMock(side_effect=recent))
    entry = await audio_setup.setup(playback=True)
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    metadata = hass.data[DOMAIN][entry.entry_id].audio_metadata
    task = asyncio.create_task(entity.async_browse_media())
    await asyncio.wait_for(started.wait(), 1)
    assert await hass.config_entries.async_unload(entry.entry_id)
    with pytest.raises(asyncio.CancelledError):
        await task
    assert metadata._listeners == {}
    assert entity._audio_removed
    assert not entity._discovery_tasks
    assert len(audio_setup.closed) == len(audio_setup.opened) == 1
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()
