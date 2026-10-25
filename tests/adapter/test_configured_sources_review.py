"""Independent review regressions; synthetic exact entity/refresh boundaries."""
# ruff: noqa: S101, INP001, ANN001, ANN202, D103, SLF001, PLC0415, PT011
import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError
from test_audio_catalogue import catalogue_commands
from test_configured_sources import configured_commands
from test_spotify_continuity import native
from test_spotify_continuity_review import entity_boundary

from custom_components.loxone.audio_catalogue import AudioCatalogue


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["Line-In", "Spotify"])
@pytest.mark.parametrize("history_outage", [False, True])
async def test_singleton_label_cannot_rebind_to_replacement_identity(hass, source, history_outage):
    entity, _, snapshots, commands, _, _ = entity_boundary(hass, binding=None)
    for name, value in vars(configured_commands()).items():
        setattr(commands, name, value)
    commands.async_recent_sources.return_value = {"items": [
        {"type": 7, "audiopath": "spotify@owner:playlist:one", "title": "Original"}]}
    await entity._async_refresh_native_sources()
    snapshots[0] = native("tunein:station:before", mode="stop")
    if source == "Line-In":
        row = commands.async_source_inputs.return_value[0]
        row["id"] = "ABCDEF123456#1000002"
        row["cmd"] = "linein/" + row["id"]
    else:
        commands.async_service_accounts.return_value[0]["id"] = "replacement"
        commands.async_recent_sources.return_value = {"items": [
            {"type": 7, "audiopath": "spotify@replacement:playlist:two", "title": "Replacement"}]}
    if history_outage:
        commands.async_recent_sources.side_effect = TimeoutError("Synthetic history outage")
    try:
        await entity.async_select_source(source)
    except HomeAssistantError:
        pass
    commands.async_play_catalogue.assert_not_awaited()
    commands.async_play_radio_station.assert_not_awaited()


@pytest.mark.asyncio
async def test_older_inventory_completion_cannot_replace_newer_inventory():
    commands = configured_commands()
    first = deepcopy(commands.async_source_inputs.return_value)
    second = deepcopy(first)
    second[0].update(id="ABCDEF123456#1000002", cmd="linein/ABCDEF123456#1000002")
    commands.async_source_inputs.side_effect = [first, second]
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0
    payload = commands.async_media_folder.side_effect

    async def folder(*_args):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await release.wait()
        return payload(*_args)

    commands.async_media_folder.side_effect = folder
    catalogue = AudioCatalogue(commands, 7)
    old = asyncio.create_task(catalogue.async_refresh_sources())
    await entered.wait()
    try:
        await catalogue.async_refresh_sources()
        newer = dict(catalogue.source_descriptors)
    finally:
        release.set()
        await asyncio.gather(old, return_exceptions=True)
    assert catalogue.source_descriptors == newer
    assert catalogue.source_descriptors["Line-In"].input_id == "ABCDEF123456#1000002"
    assert catalogue._source_inputs[0].folder == "ABCDEF123456#1000002"


@pytest.mark.asyncio
async def test_older_history_completion_cannot_replace_newer_choices():
    commands = configured_commands()
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def recent(_player):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await release.wait()
            return {"items": [{"audiopath": "tunein:station:older", "title": "Older"}]}
        return {"items": [{"audiopath": "tunein:station:newer", "title": "Newer"}]}

    commands.async_recent_sources.side_effect = recent
    catalogue = AudioCatalogue(commands, 7)
    old = asyncio.create_task(catalogue.async_refresh_sources())
    await entered.wait()
    try:
        await catalogue.async_refresh_sources()
    finally:
        release.set()
        await asyncio.gather(old, return_exceptions=True)
    assert catalogue.source_choices["TuneIn"].audio_path == "tunein:station:newer"


@pytest.mark.asyncio
async def test_history_started_before_new_native_event_cannot_replace_it():
    commands = configured_commands()
    entered, release = asyncio.Event(), asyncio.Event()

    async def recent(_player):
        entered.set()
        await release.wait()
        return {"items": [{"audiopath": "tunein:station:older", "title": "Older"}]}

    commands.async_recent_sources.side_effect = recent
    catalogue = AudioCatalogue(commands, 7)
    task = asyncio.create_task(catalogue.async_refresh_sources())
    await entered.wait()
    try:
        assert catalogue.remember_source(native("tunein:station:newer-event")) == "TuneIn"
    finally:
        release.set()
        await task
    assert catalogue.source_choices["TuneIn"].audio_path == "tunein:station:newer-event"


@pytest.mark.asyncio
async def test_empty_unconfigured_radio_root_is_not_availability_evidence():
    commands = catalogue_commands()
    commands.async_service_accounts.return_value = []
    commands.async_source_inputs.return_value = []
    commands.async_search_capabilities.return_value = {}
    commands.async_radio_services.return_value = []
    commands.async_recent_sources = AsyncMock(return_value={"items": []})
    catalogue = AudioCatalogue(commands, 7)
    await catalogue.async_refresh_sources()
    assert not catalogue.source_descriptors


@pytest.mark.asyncio
async def test_selection_cannot_fallback_after_its_published_inventory_is_superseded(hass):
    entity, _, snapshots, commands, _, _ = entity_boundary(hass, binding=None)
    for name, value in vars(configured_commands()).items():
        setattr(commands, name, value)
    await entity._async_refresh_native_sources()
    snapshots[0] = native("tunein:station:before", mode="stop")
    history_entered, history_release = asyncio.Event(), asyncio.Event()
    inventory_entered, inventory_release = asyncio.Event(), asyncio.Event()

    async def recent(_player):
        history_entered.set()
        await history_release.wait()
        return {"items": []}

    async def replacement_accounts():
        inventory_entered.set()
        await inventory_release.wait()
        return []

    async def play(_player, _service, _account, path, *, is_current, on_send):
        assert is_current()
        on_send()
        snapshots[0] = native("linein:" + path)

    commands.async_recent_sources.side_effect = recent
    commands.async_play_catalogue.side_effect = play
    selection = asyncio.create_task(entity.async_select_source("Line-In"))
    await history_entered.wait()
    commands.async_service_accounts.side_effect = replacement_accounts
    replacement = asyncio.create_task(entity._radio_catalogue.async_refresh_sources())
    await inventory_entered.wait()
    try:
        history_release.set()
        await asyncio.gather(selection, return_exceptions=True)
    finally:
        commands.async_source_inputs.return_value = []
        inventory_release.set()
        await asyncio.gather(replacement, return_exceptions=True)
    commands.async_play_catalogue.assert_not_awaited()
