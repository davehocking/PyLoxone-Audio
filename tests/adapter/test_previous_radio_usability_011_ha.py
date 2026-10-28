"""R79-01: real HA previous-radio calls with synthetic native room history.

Derived from independent review run79's unplayable-station and folder controls.
No appliance I/O or real household data is used.
"""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from test_audioserver_ha import audio_setup
from test_native_source_return_ha import install_sources, library_row
from custom_components.loxone.pyloxone_api import audioserver as wire


async def install_radio_source(hass, audio_setup, monkeypatch, provider):
    entity, emit, writes = await install_sources(hass, audio_setup, monkeypatch)
    if provider == "loxoneradio":
        original_folder = wire.AudioServerCommands.async_media_folder

        async def folder(client, service, account, path, offset):
            if service == "loxoneradio":
                return [{"start": 0, "totalitems": 1, "items": [{
                    "type": 2, "audiopath": "loxoneradio:station:catalogue",
                    "name": "Synthetic available station",
                }]}]
            return await original_folder(client, service, account, path, offset)

        monkeypatch.setattr(wire.AudioServerCommands, "async_media_folder", folder)
    await entity._async_refresh_native_sources()
    return entity, emit, writes


def confirm_radio(audio_setup, monkeypatch, writes):
    async def native_radio(client, player, provider, path, *, is_current, on_send):
        assert player == 7 and is_current()
        on_send()
        writes.append(path)
        asyncio.get_running_loop().call_soon(
            audio_setup.queues[0].put_nowait,
            json.dumps({"audio_event": [{
                "playerid": 7, "mode": "play", "eventype": 0, "audiopath": path,
            }]}),
        )

    monkeypatch.setattr(wire.AudioServerCommands, "async_play_radio_station", native_radio)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,label", [("tunein", "TuneIn"), ("loxoneradio", "Loxone Radio")])
@pytest.mark.parametrize("case,usable", [
    ("playable", True), ("implicit-playable", True), ("unplayable", False),
    ("folder", False), ("missing-type", False), ("unknown-type", False),
    ("unknown-playability", False),
])
async def test_previous_radio_history_qualifies_station_before_listing_or_service_dispatch(
    hass, audio_setup, monkeypatch, provider, label, case, usable,
):
    entity, emit, writes = await install_radio_source(hass, audio_setup, monkeypatch, provider)
    await emit(library_row(time=0))
    assert entity._radio_catalogue.source_session(label) is None
    path = provider + (":folder:synthetic" if case == "folder" else ":station:synthetic")
    row = {"type": 2, "audiopath": path, "title": "Prior station", "unplayable": False}
    if case == "implicit-playable":
        row.pop("unplayable")
    elif case == "unplayable":
        row["unplayable"] = True
    elif case == "folder":
        row.update(type=1, id="synthetic-folder", name="Browse folder")
    elif case == "missing-type":
        row.pop("type")
    elif case == "unknown-type":
        row["type"] = 7
    elif case == "unknown-playability":
        row["unplayable"] = "unknown"
    monkeypatch.setattr(wire.AudioServerCommands, "async_recent_sources", AsyncMock(return_value={"items": [row]}))
    await entity._async_refresh_native_sources()
    advertised = label in (entity.source_list or [])
    confirm_radio(audio_setup, monkeypatch, writes)
    try:
        await hass.services.async_call("media_player", "select_source", {
            "entity_id": entity.entity_id, "source": label,
        }, blocking=True)
        result = "success"
    except HomeAssistantError:
        result = "refused"
    # Check both observables after exercising the service, even on a RED listing.
    assert (advertised, result, writes) == (
        (True, "success", [path]) if usable else (False, "refused", [])
    )
    if usable:
        assert entity._audio_metadata.get(7).audio_path == path
        assert entity.source == label
        assert not entity._audio_commands.source_fences
    else:
        assert entity._radio_catalogue.source_session(label) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,label", [("tunein", "TuneIn"), ("loxoneradio", "Loxone Radio")])
@pytest.mark.parametrize("history_kind", ["folder", "unplayable"])
async def test_qualified_external_radio_session_survives_unusable_recent_rows(
    hass, audio_setup, monkeypatch, provider, label, history_kind,
):
    entity, emit, writes = await install_radio_source(hass, audio_setup, monkeypatch, provider)
    monkeypatch.setattr(wire.AudioServerCommands, "async_recent_sources", AsyncMock(return_value={"items": []}))
    await entity._async_refresh_native_sources()
    assert not entity.source_list and not entity._radio_catalogue.source_sessions
    selected = provider + ":station:external"
    await emit({"playerid": 7, "mode": "play", "eventype": 0, "audiopath": selected})
    assert entity.source_list == [label] and writes == []
    await emit(library_row(time=0))
    row = {
        "type": 1 if history_kind == "folder" else 2,
        "id": "synthetic-history", "audiopath": provider + ":folder:history",
        "title": "Unusable history", "unplayable": history_kind == "unplayable",
    }
    monkeypatch.setattr(wire.AudioServerCommands, "async_recent_sources", AsyncMock(return_value={"items": [row]}))
    await entity._async_refresh_native_sources()
    assert label in entity.source_list
    confirm_radio(audio_setup, monkeypatch, writes)
    await hass.services.async_call("media_player", "select_source", {
        "entity_id": entity.entity_id, "source": label,
    }, blocking=True)
    assert writes == [selected]
    assert entity._audio_metadata.get(7).audio_path == selected
    assert entity.source == label and not entity._audio_commands.source_fences
