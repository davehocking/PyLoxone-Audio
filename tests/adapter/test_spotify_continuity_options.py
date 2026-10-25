"""Offline options validation for explicit, optional room bindings."""

# ruff: noqa: S101, INP001, D103, PLC0415, ANN001

from copy import deepcopy

import pytest
from homeassistant.helpers.schema_config_entry_flow import SchemaFlowError
from test_spotify_continuity import CONFIG


@pytest.mark.asyncio
async def test_options_accept_explicit_binding_and_expose_editable_mapping():
    from custom_components.loxone import config_flow as flow

    value = {
        "audioserver_host": "audio.example.invalid",
        "audioserver_playback": True,
        "audioserver_spotify_return": {"synthetic-zone-7": deepcopy(CONFIG)},
    }
    assert await flow.validate_loxone_setup(None, value) == value
    assert "audioserver_spotify_return" in {key.schema for key in flow.DATA_SCHEMA_OPTIONS.schema}


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["malformed", "duplicate-device", "no-playback", "extra-token", "path"])
async def test_options_reject_ambiguous_or_unsafe_room_binding(change):
    from custom_components.loxone import config_flow as flow

    value = {
        "audioserver_host": "audio.example.invalid",
        "audioserver_playback": True,
        "audioserver_spotify_return": {"synthetic-zone-7": deepcopy(CONFIG)},
    }
    if change == "malformed":
        value["audioserver_spotify_return"] = []
    elif change == "duplicate-device":
        value["audioserver_spotify_return"]["synthetic-zone-8"] = deepcopy(CONFIG)
    elif change == "no-playback":
        value["audioserver_playback"] = False
    elif change == "extra-token":
        value["audioserver_spotify_return"]["synthetic-zone-7"]["token"] = "synthetic-only"  # noqa: S105 - rejected synthetic extra field
    else:
        value["audioserver_spotify_return"] = {"../room": deepcopy(CONFIG)}
    with pytest.raises(SchemaFlowError):
        await flow.validate_loxone_setup(None, value)
