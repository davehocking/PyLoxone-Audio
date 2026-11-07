"""Fail-closed optional native binding on malformed synthetic structure."""

import pytest
from custom_components.loxone.audio_grouping import grouping_binding
from test_audio_grouping_ha import structure, SERVER, action


@pytest.mark.parametrize(
    "case",
    [
        "root",
        "states-none",
        "states-list",
        "controls-none",
        "control-none",
        "control-no-type",
        "zero-state",
        "zero-server",
        "duplicate-state-control",
        "key-action-mismatch",
    ],
)
def test_invalid_structure_disables_only_optional_group_binding(case):
    value = structure()
    if case == "root":
        value = None
    elif case == "states-none":
        value["mediaServer"][SERVER]["states"] = None
    elif case == "states-list":
        value["mediaServer"][SERVER]["states"] = []
    elif case == "controls-none":
        value["controls"] = None
    elif case == "control-none":
        value["controls"][action(1)] = None
    elif case == "control-no-type":
        value["controls"][action(1)].pop("type")
    elif case == "zero-state":
        value["mediaServer"][SERVER]["states"]["grouping"] = (
            "00000000-0000-0000-0000000000000000"
        )
    elif case == "zero-server":
        details = value["mediaServer"].pop(SERVER)
        details["uuidAction"] = "00000000-0000-0000-0000000000000000"
        value["mediaServer"][details["uuidAction"]] = details
    elif case == "duplicate-state-control":
        value["mediaServer"][SERVER]["states"]["grouping"] = action(1)
    else:
        value["controls"][action(1)]["uuidAction"] = action(99)
    try:
        result = grouping_binding(value)
    except (AttributeError, KeyError, TypeError) as exc:
        result = exc
    assert result is None


@pytest.mark.parametrize(
    "language", ["en", "nl", "cs", "es", "it", "pt-PT", "de", "fr", "pt", "pt-BR"]
)
async def test_group_errors_resolve_through_real_ha_translations(
    hass, enable_custom_integrations, language
):
    from homeassistant.helpers.translation import async_get_translations

    resources = await async_get_translations(hass, language, "exceptions", {"loxone"})
    for key in ("unavailable", "failed", "busy"):
        assert resources.get(
            f"component.loxone.exceptions.audioserver_grouping_{key}.message"
        )
