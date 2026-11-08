"""HA2026.11 native log discovery; synthetic lines, no device connection."""
import logging
from unittest.mock import AsyncMock

from homeassistant.components import system_log
from homeassistant.components.system_log.stream import DATA_RAW_LOG_STREAM
from homeassistant.const import KEY_DATA_LOGGING
from homeassistant.setup import async_setup_component
from test_audioserver_ha import audio_setup


async def test_native_integration_log_includes_library_without_enabling_debug(
    hass, audio_setup, hass_ws_client, tmp_path
):
    hass.config.config_dir = str(tmp_path)
    entry = await audio_setup.setup(playback=True)
    collector = hass.data["loxone"][entry.entry_id].audio_diagnostics
    assert not collector.enabled
    loggers = [logging.getLogger(n) for n in (
        "custom_components.loxone", "custom_components.loxone.pyloxone_api.connection",
        "pyloxone_audio", "websockets.client",
    )]
    levels_before = [(log.level, log.getEffectiveLevel()) for log in loggers]
    hass.data[KEY_DATA_LOGGING] = None
    assert await async_setup_component(hass, system_log.DOMAIN, {})
    lines = [
        "2026-11-05 12:00:00.000 WARNING (MainThread) [custom_components.loxone.audio_diagnostics] Audio diagnostics storage unavailable; playback is unaffected. Check free disk space and permissions",
        "2026-11-05 12:00:01.000 WARNING (MainThread) [pyloxone_audio.sources] Optional audio position restore failed; confirmed source playback is retained",
        "2026-11-05 12:00:02.000 WARNING (MainThread) [pyloxone_audio_other] UNRELATED_SECRET",
        "2026-11-05 12:00:03.000 WARNING (MainThread) [websockets.client] UNRELATED_AUTH_SECRET",
    ]
    system_log.async_register_log_reader(hass, AsyncMock(return_value=lines))
    client = await hass_ws_client()
    await client.send_json_auto_id({
        "type": "system_log/subscribe_raw", "integration": "loxone",
    })
    acknowledgement = await client.receive_json()
    assert acknowledgement["success"]
    sub_id = acknowledgement["id"]
    event = (await client.receive_json())["event"]
    assert event == lines[:2], "Native Loxone log view must include its library warning"
    assert "SECRET" not in "\n".join(event)
    assert [(log.level, log.getEffectiveLevel()) for log in loggers] == levels_before
    assert not collector.enabled and collector.queue.empty()
    await client.send_json_auto_id({"type": "unsubscribe_events", "subscription": sub_id})
    assert (await client.receive_json())["success"]
    assert not hass.data[DATA_RAW_LOG_STREAM]._subscribers
    await client.close()
