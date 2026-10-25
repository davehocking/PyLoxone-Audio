"""Real HA source actions with synthetic I/O; no household playback evidence.

The valid recent fixture preserves a fresh read-only Snug reply's row shapes,
not the unrecorded failing request. Every invalid/outage case is fault injection.
"""
# ruff: noqa: S101, SLF001, INP001, F811, F401, PLR2004
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from urllib.parse import unquote

import pytest
from homeassistant.exceptions import HomeAssistantError

from test_audioserver_ha import audio_setup
from test_native_source_return_ha import install_sources, library_row
from custom_components.loxone.pyloxone_api import audioserver as wire

LOGGER = "custom_components.loxone.audio_diagnostics"
STATION = "loxoneradio:stream:synthetic-0"


async def radio_room(hass: Any, audio_setup: Any, monkeypatch: Any) -> Any:
    entity, emit, writes = await install_sources(hass, audio_setup, monkeypatch, spotify=True)
    folder = wire.AudioServerCommands.async_media_folder

    async def with_radio(client: Any, service: str, account: str, path: str, offset: int) -> Any:
        if service == "loxoneradio":
            return [{"start": 0, "totalitems": 1, "items": [
                {"type": 2, "name": "Synthetic station", "audiopath": STATION},
            ]}]
        return await folder(client, service, account, path, offset)

    monkeypatch.setattr(wire.AudioServerCommands, "async_media_folder", with_radio)
    recent = json.loads((Path(__file__).parent / "fixtures/synthetic_recent_shape.json").read_text())
    monkeypatch.setattr(wire.AudioServerCommands, "async_recent_sources", AsyncMock(return_value=recent))
    await entity._radio_catalogue.async_refresh_sources()
    await emit(library_row())
    return entity, emit, writes


@pytest.mark.parametrize("preflight", [False, True])
@pytest.mark.parametrize(("recent", "reason"), [
    ({"items": []}, "source_content_missing"),
    ({"items": None}, "source_history_invalid"),
    ({"items": [{"audiopath": "library:local:track:synthetic", "title": "Synthetic"}]}, "source_history_item_invalid"),
    ({"items": [{"audiopath": "library:local:track:synthetic", "title": "\n", "type": 2}]}, "source_catalogue_text_invalid"),
])
async def test_source_history_refusal_retains_original_fixed_reason_and_provider_without_logging(
    hass: Any, audio_setup: Any, monkeypatch: Any, caplog: Any,
    preflight: bool, recent: Any, reason: str,
) -> None:
    entity, _emit, writes = await radio_room(hass, audio_setup, monkeypatch)
    if preflight:
        entity._radio_catalogue.source_choices.pop("Loxone Radio")
    read = AsyncMock(return_value=deepcopy(recent))
    monkeypatch.setattr(wire.AudioServerCommands, "async_recent_sources", read)
    caplog.set_level(logging.CRITICAL, logger=LOGGER)
    with pytest.raises(HomeAssistantError) as error:
        await hass.services.async_call("media_player", "select_source", {
            "entity_id": entity.entity_id, "source": "Loxone Radio",
        }, blocking=True)
    await hass.async_block_till_done()
    assert str(error.value) == "Choose content explicitly in Browse before selecting this source"
    assert "audio_last_source_failure" not in hass.states.get(entity.entity_id).attributes
    assert read.await_count == 1
    assert writes == []
    assert entity._source_task is None
    assert not entity._audio_commands.source_fences
    assert not entity._audio_commands.source_observations
    assert not [r for r in caplog.records if r.name == LOGGER]
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


async def test_unknown_history_error_stays_redacted_and_publication_cannot_replace_action_error(
    hass: Any, audio_setup: Any, monkeypatch: Any, caplog: Any,
) -> None:
    entity, _emit, writes = await radio_room(hass, audio_setup, monkeypatch)
    private = "https://secret.invalid/?token=DO_NOT_LOG"
    read = AsyncMock(side_effect=ValueError(private))
    monkeypatch.setattr(wire.AudioServerCommands, "async_recent_sources", read)
    caplog.set_level(logging.CRITICAL, logger=LOGGER)
    def no_publish(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("Synthetic publication failure")
    monkeypatch.setattr(entity, "async_schedule_update_ha_state", no_publish)
    with pytest.raises(HomeAssistantError) as error:
        await entity.async_select_source("Loxone Radio")
    assert str(error.value) == "Choose content explicitly in Browse before selecting this source"
    assert "audio_last_source_failure" not in entity.extra_state_attributes
    assert "DO_NOT_LOG" not in caplog.text
    assert writes == [] and read.await_count == 1
    assert entity._source_task is None


@pytest.mark.parametrize("history_failure", ["empty", "invalid", "timeout"])
async def test_same_controller_radio_last_good_survives_history_loss_and_successive_sources(
    hass: Any, audio_setup: Any, monkeypatch: Any, history_failure: str,
) -> None:
    entity, emit, writes = await radio_room(hass, audio_setup, monkeypatch)
    await emit(library_row(audiopath="spotify:track:original", parent={"id": "spotify:playlist:original"}, sourceName="Synthetic owner"))
    # Confirm the station before leaving; song title is deliberately different.
    row = {"playerid": 7, "mode": "play", "audiopath": STATION, "title": "Synthetic song, not station identity"}
    await emit(row)
    assert entity._radio_catalogue.source_session("Loxone Radio").audio_path == STATION
    old_request = wire.AudioServerCommands._async_request
    async def request(client: Any, command: str, key: Any, **kwargs: Any) -> Any:
        if "/serviceplay/radio/nouser/" not in command:
            return await old_request(client, command, key, **kwargs)
        assert kwargs["is_current"]()
        kwargs["on_send"]()
        writes.append(command)
        audio_setup.queues[0].put_nowait(json.dumps({"audio_event": [row]}))
        return None
    monkeypatch.setattr(wire.AudioServerCommands, "_async_request", request)
    if history_failure == "timeout":
        history = AsyncMock(side_effect=TimeoutError("Synthetic optional history unavailable"))
    else:
        history = AsyncMock(return_value={"items": [] if history_failure == "empty" else None})
    monkeypatch.setattr(wire.AudioServerCommands, "async_recent_sources", history)
    # Same entity/controller, no manufactured restart between choices.
    for source in ("Spotify", "Local Library", "Loxone Radio", "Spotify", "Loxone Radio"):
        await hass.services.async_call("media_player", "select_source", {
            "entity_id": entity.entity_id, "source": source,
        }, blocking=True)
    radio_writes = [command for command in writes if "/serviceplay/radio/nouser/" in command]
    assert len(radio_writes) == 2
    assert all(unquote(command).endswith(STATION) for command in radio_writes)
    assert not any("Synthetic song" in command for command in writes)
    assert entity._radio_catalogue.source_session("Loxone Radio").audio_path == STATION
    assert entity._source_task is None and not entity._audio_commands.source_fences
    assert not entity._audio_commands.source_observations
    assert all(call.args == (7,) for call in history.await_args_list)
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


async def test_newer_library_cancels_radio_history_read_without_sending_or_publishing_old_failure(
    hass: Any, audio_setup: Any, monkeypatch: Any,
) -> None:
    entity, _emit, writes = await radio_room(hass, audio_setup, monkeypatch)
    entered = asyncio.Event()
    async def blocked(_client: Any, player: int) -> Any:
        assert player == 7
        entered.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(wire.AudioServerCommands, "async_recent_sources", blocked)
    old = asyncio.create_task(hass.services.async_call("media_player", "select_source", {
        "entity_id": entity.entity_id, "source": "Loxone Radio",
    }, blocking=True))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        # Retained Library session still needs its one optional history read;
        # the newer request must not inherit the old read or its failure.
        monkeypatch.setattr(wire.AudioServerCommands, "async_recent_sources", AsyncMock(return_value={"items": []}))
        await hass.services.async_call("media_player", "select_source", {
            "entity_id": entity.entity_id, "source": "Local Library",
        }, blocking=True)
        result = await asyncio.gather(old, return_exceptions=True)
        assert isinstance(result[0], asyncio.CancelledError)
        assert not any("/serviceplay/radio/nouser/" in command for command in writes)
        assert getattr(entity, "_audio_last_source_failure", None) is None
        assert entity._source_task is None
        assert not entity._audio_commands.source_fences
    finally:
        old.cancel()
        await asyncio.gather(old, return_exceptions=True)
