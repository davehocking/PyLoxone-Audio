"""Exact Core2026.11 naming/registry export for the compiled native UI fixture."""
import json
import os
from pathlib import Path

from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from test_audio_grouping_ha import audio_setup as audio_setup, grouped_setup as grouped_setup, row


async def test_current_core_name_and_display_registry_match_native_ui(
    hass, grouped_setup, hass_ws_client
):
    g = grouped_setup
    entry, coordinator, ids = await g.setup()
    await g.feed(entry, row("one", (1, 2)), row("outside", (3, 4)))
    await g.callbacks[entry.entry_id]["callback"]({
        **{f"play-{p}": 1 for p in ids},
        **{f"volume-{p}": v for p, v in zip(ids, [10, 40, 60, 90, 20, 30])},
    })
    registry = er.async_get(hass)
    registry.async_update_entity(ids[2], name="Owner room Ω – Long chosen name")
    await hass.async_block_till_done()
    # Core2026.11 composes this device-qualified friendly name; do not strip it.
    assert hass.states.get(ids[2]).attributes["friendly_name"] == "Synthetic speaker 2 Owner room Ω – Long chosen name"
    assert await async_setup_component(hass, "config", {})
    client = await hass_ws_client()
    await client.send_json_auto_id({"type": "config/entity_registry/list_for_display"})
    reply = await client.receive_json()
    assert reply["success"]
    display = reply["result"]
    assert len([r for r in display["entities"] if r["ei"] in ids.values()]) == 6
    assert registry.async_get(ids[2]).name == "Owner room Ω – Long chosen name"
    await client.send_json_auto_id({"type": "config/device_registry/list"})
    device_reply = await client.receive_json()
    assert device_reply["success"]
    output = os.environ.get("GM03_BROWSER_STATES")
    assert output, "Explicit synthetic frontend export path is required"
    Path(output).write_text(json.dumps({
        "snapshots": [{"scenario": "initial", "target": ids[2], "states": {
            i: hass.states.get(i).as_dict() for i in ids.values()
        }}], "display_registry": display, "device_registry": device_reply["result"],
        "provenance": "Registered real HA2026.11.0 setup/state and native display-registry WebSocket response; external I/O invented",
    }, indent=2, default=str) + "\n")
    await client.close()
