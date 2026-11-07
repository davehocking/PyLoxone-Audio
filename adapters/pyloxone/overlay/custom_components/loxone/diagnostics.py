"""Diagnostics support for Pyloxone."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    # The structure file of *this* entry: with several Miniservers the
    # first loaded one used to be returned for every entry.
    coordinator = hass.data.get(DOMAIN, {}).get(config_entry.entry_id)
    miniserver = getattr(coordinator, "miniserver", None)
    if miniserver is None:
        return {"error": "Config entry is not loaded"}
    diagnostics = getattr(coordinator, "audio_diagnostics", None)
    if diagnostics is None or diagnostics.closed:
        return {"error": "Audio diagnostics unavailable"}
    from importlib.metadata import version
    from homeassistant.const import __version__ as ha_version
    integration = await async_get_integration(hass, config_entry.domain)
    return {"audio": await diagnostics.async_export(),
            "environment": {"home_assistant": ha_version, "pyloxone": str(integration.version),
                            "pyloxone_audio": version("PyLoxone-Audio")},
            "evidence_limits": ["No commands from before opt-in", "Socket send is not device execution",
                                "Numeric position replies are echoes, not physical movement",
                                "No audio, titles, private announcement text or raw house configuration",
                                "A native reply is not final HA service acceptance",
                                "HA Action history records calls and context, not internal audio transmission or sound",
                                "Native HA logs and Action history are separate raw data, not included or sanitised here",
                                "Debug console is optional administrator-only Python execution; input is logged"]}

