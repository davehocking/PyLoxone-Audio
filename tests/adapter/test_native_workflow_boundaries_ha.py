"""Native HA workflow boundaries in disposable synthetic exact-Core tests only."""
import json
from datetime import timedelta
from unittest.mock import AsyncMock

from homeassistant.components import system_log
from homeassistant.const import KEY_DATA_LOGGING
from homeassistant.core import Context
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant.components.recorder.common import async_wait_recording_done
from test_audioserver_ha import audio_setup, zone_entity_id


async def test_native_raw_logs_are_admin_only(
    hass, audio_setup, hass_ws_client, hass_admin_user, tmp_path
):
    hass.config.config_dir = str(tmp_path)
    await audio_setup.setup(playback=True)
    hass.data[KEY_DATA_LOGGING] = None
    assert await async_setup_component(hass, "system_log", {})
    reader = AsyncMock(return_value=["PRIVATE_NATIVE_LINE"])
    system_log.async_register_log_reader(hass, reader)
    client = await hass_ws_client()
    hass_admin_user.is_owner = False
    hass_admin_user.groups = []
    assert not hass_admin_user.is_admin
    await client.send_json_auto_id({"type": "system_log/subscribe_raw", "integration": "loxone"})
    response = await client.receive_json()
    assert not response["success"] and response["error"]["code"] == "unauthorized"
    reader.assert_not_awaited()
    await client.close()


async def test_native_raw_logs_are_not_the_sanitised_audio_export(
    hass, audio_setup, hass_ws_client, tmp_path
):
    hass.config.config_dir = str(tmp_path)
    entry = await audio_setup.setup(playback=True)
    collector = hass.data["loxone"][entry.entry_id].audio_diagnostics
    hass.data[KEY_DATA_LOGGING] = None
    assert await async_setup_component(hass, "system_log", {})
    line = "2026-11-05 12:00:00.000 WARNING (MainThread) [custom_components.loxone] SYNTHETIC_PASSWORD_MUST_NOT_SHARE"
    system_log.async_register_log_reader(hass, AsyncMock(return_value=[line]))
    client = await hass_ws_client()
    await client.send_json_auto_id({"type": "system_log/subscribe_raw", "integration": "loxone"})
    ack = await client.receive_json()
    assert ack["success"]
    assert (await client.receive_json())["event"] == [line]
    report = await collector.async_export()
    assert "SYNTHETIC_PASSWORD_MUST_NOT_SHARE" not in json.dumps(report)
    assert not collector.enabled
    await client.send_json_auto_id({"type": "unsubscribe_events", "subscription": ack["id"]})
    assert (await client.receive_json())["success"]
    await client.close()


async def test_native_action_history_has_raw_context_audio_export_only_alias(
    recorder_mock, hass, audio_setup, hass_ws_client, hass_admin_user, tmp_path
):
    hass.config.config_dir = str(tmp_path)
    assert await async_setup_component(hass, "logbook", {})
    entry = await audio_setup.setup(playback=True)
    collector = hass.data["loxone"][entry.entry_id].audio_diagnostics
    await collector.async_set_enabled(True)
    context = Context(user_id=hass_admin_user.id)
    entity_id = zone_entity_id(hass, 7)
    await hass.services.async_call(
        "media_player", "volume_set", {"entity_id": entity_id, "volume_level": 0.37},
        blocking=True, context=context,
    )
    await hass.async_block_till_done()
    await async_wait_recording_done(hass)
    client = await hass_ws_client()
    await client.send_json_auto_id({
        "type": "logbook/get_action_calls",
        "start_time": (dt_util.utcnow() - timedelta(minutes=1)).isoformat(),
    })
    response = await client.receive_json()
    assert response["success"]
    calls = [row for row in response["result"] if row["domain"] == "media_player" and row["service"] == "volume_set"]
    assert len(calls) == 1
    assert calls[0]["context_id"] == context.id
    assert calls[0]["context_user_id"] == hass_admin_user.id
    assert calls[0]["service_data"]["entity_id"] == entity_id
    report = await collector.async_export()
    rows = [row for row in report["events"] if row["stage"] == "ha_service_request"]
    assert len(rows) == 1
    assert rows[0]["request_id"] != context.id
    assert rows[0]["volume"] == 37
    assert context.id not in json.dumps(report) and hass_admin_user.id not in json.dumps(report)
    assert not any(row["stage"] == "send_completed" for row in report["events"])
    await client.close()


async def test_optional_native_console_is_not_enabled_by_audio_and_warns_and_logs(
    hass, audio_setup, hass_ws_client, caplog, tmp_path
):
    hass.config.config_dir = str(tmp_path)
    entry = await audio_setup.setup(playback=True)
    collector = hass.data["loxone"][entry.entry_id].audio_diagnostics
    assert "debug_console" not in hass.config.components
    client = await hass_ws_client()
    await client.send_json_auto_id({"type": "debug_console/info"})
    assert not (await client.receive_json())["success"]
    # Enable only inside this disposable network-isolated fixture; NEVER a target helper.
    assert await async_setup_component(hass, "debug_console", {"debug_console": {}})
    code = "'loxone' in hass.config.components"
    await client.send_json_auto_id({"type": "debug_console/execute", "session_id": "fixture", "code": code})
    refusal = await client.receive_json()
    assert not refusal["success"] and refusal["error"]["code"] == "warning_not_accepted"
    await client.send_json_auto_id({"type": "debug_console/warning/accept"})
    assert (await client.receive_json())["success"]
    await client.send_json_auto_id({"type": "debug_console/execute", "session_id": "fixture", "code": code})
    result = await client.receive_json()
    assert result["success"] and "error" not in result["result"]
    assert "True" in str(result["result"]["result"])
    assert code in caplog.text
    assert not collector.enabled and collector.queue.empty()
    assert code not in json.dumps(await collector.async_export())
    await client.close()


async def test_console_stop_cancels_only_its_synthetic_await(
    hass, audio_setup, hass_ws_client, tmp_path
):
    import asyncio

    hass.config.config_dir = str(tmp_path)
    await audio_setup.setup(playback=True)
    assert await async_setup_component(hass, "debug_console", {"debug_console": {}})
    started, release = asyncio.Event(), asyncio.Event()

    async def wait_in_fixture():
        started.set()
        await release.wait()

    hass.data["fixture_wait"] = wait_in_fixture
    client = await hass_ws_client()
    try:
        await client.send_json_auto_id({"type": "debug_console/warning/accept"})
        assert (await client.receive_json())["success"]
        await client.send_json_auto_id({
            "type": "debug_console/execute", "session_id": "fixture-stop",
            "code": "await hass.data['fixture_wait']()",
        })
        await asyncio.wait_for(started.wait(), 5)
        await client.send_json_auto_id({"type": "debug_console/stop", "session_id": "fixture-stop"})
        responses = [await client.receive_json(), await client.receive_json()]
        assert sum(row["success"] for row in responses) == 1
        refused = next(row for row in responses if not row["success"])
        assert refused["error"]["code"] == "execution_stopped"
    finally:
        release.set()
        await client.close()


async def test_console_refuses_nonadministrator_even_after_component_setup(
    hass, audio_setup, hass_ws_client, hass_admin_user, tmp_path
):
    hass.config.config_dir = str(tmp_path)
    await audio_setup.setup(playback=True)
    assert await async_setup_component(hass, "debug_console", {"debug_console": {}})
    client = await hass_ws_client()
    hass_admin_user.is_owner = False
    hass_admin_user.groups = []
    assert not hass_admin_user.is_admin
    for payload in (
        {"type": "debug_console/info"},
        {"type": "debug_console/warning/accept"},
        {"type": "debug_console/execute", "session_id": "fixture-denied", "code": "'loxone' in hass.config.components"},
    ):
        await client.send_json_auto_id(payload)
        response = await client.receive_json()
        assert not response["success"] and response["error"]["code"] == "unauthorized"
    await client.close()
