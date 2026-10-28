"""Native switch and existing diagnostics callback through actual HA lifecycle."""

import json
from unittest.mock import AsyncMock

import pytest
from homeassistant.const import Platform
from homeassistant.helpers import entity_registry as er
from custom_components import loxone
from custom_components.loxone.const import DOMAIN
from custom_components.loxone.diagnostics import async_get_config_entry_diagnostics
from test_audioserver_ha import audio_setup, zone_entity_id
from custom_components.loxone.coordinator import LoxoneCoordinator


async def test_owning_service_and_miniserver_audio_feedback_are_distinct(
    hass, audio_setup, monkeypatch, tmp_path
):
    hass.config.config_dir = str(tmp_path)
    callbacks = []
    original = LoxoneCoordinator.async_config_entry_first_refresh

    async def refresh(coordinator):
        await original(coordinator)

        async def run(**kwargs):
            callbacks.append(kwargs["callback"])
            import asyncio

            await asyncio.Future()

        coordinator.api.run = run

    monkeypatch.setattr(LoxoneCoordinator, "async_config_entry_first_refresh", refresh)
    entry = await audio_setup.setup(playback=True)
    collector = hass.data[DOMAIN][entry.entry_id].audio_diagnostics
    await collector.async_set_enabled(True)
    await hass.services.async_call(
        "media_player",
        "volume_set",
        {"entity_id": zone_entity_id(hass, 7), "volume_level": 0.37},
        blocking=True,
    )
    await callbacks[0]({"volume-7": 37, "play-7": 1, "unrelated-door": "SECRET"})
    await hass.async_block_till_done()
    report = await collector.async_export()
    assert any(
        r["stage"] == "ha_service_request"
        and r["operation"] == "volume_set"
        and r["volume"] == 37
        for r in report["events"]
    )
    assert any(
        r["stage"] == "feedback"
        and r["transport"] == "miniserver"
        and r["volume"] == 37
        for r in report["events"]
    )
    assert "SECRET" not in json.dumps(report)
    assert not any(r["stage"] == "send_completed" for r in report["events"]), (
        "A request is not completed transmission"
    )


async def test_one_entry_switch_is_default_off_no_reload_and_export_is_sanitised(
    hass, audio_setup, monkeypatch, tmp_path
):
    hass.config.config_dir = str(tmp_path)
    monkeypatch.setattr(
        loxone, "LOXONE_PLATFORMS", [Platform.MEDIA_PLAYER, Platform.SWITCH]
    )
    entry = await audio_setup.setup(playback=True)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    collector = getattr(coordinator, "audio_diagnostics", None)
    assert collector is not None, "The loaded entry has no supported diagnostics owner"
    registry = er.async_get(hass)
    switch = registry.async_get_entity_id(
        "switch", DOMAIN, entry.entry_id + "_audio_diagnostics"
    )
    assert switch is not None
    assert hass.states.get(switch).state == "off"
    assert hass.states.get(switch).name == "Audio diagnostics"
    from pathlib import Path
    from custom_components.loxone import switch as switch_module

    labels = json.loads(
        (Path(switch_module.__file__).parent / "translations/en.json").read_text()
    )
    assert (
        labels.get("entity", {})
        .get("switch", {})
        .get("audio_diagnostics", {})
        .get("name")
        == "Audio diagnostics"
    )
    assert not collector.enabled
    original = (coordinator.api, coordinator.audio_commands, coordinator.audio_metadata)
    opened = list(audio_setup.opened)
    reload = AsyncMock()
    monkeypatch.setattr(hass.config_entries, "async_reload", reload)
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": switch}, blocking=True
    )
    assert collector.enabled
    await audio_setup.queues[0].put(
        json.dumps(
            {
                "audio_event": [
                    {
                        "playerid": 7,
                        "mode": "play",
                        "eventype": 0,
                        "audiopath": "spotify:track:SECRET",
                        "title": "SECRET-private-song",
                        "sourceName": "SECRET-account",
                        "time": 66.285,
                        "duration": 180,
                        "pbr": 32,
                    }
                ]
            }
        )
    )
    await hass.async_block_till_done()
    report = await async_get_config_entry_diagnostics(hass, entry)
    assert "LoxAPP3.json" not in report
    assert any(
        r["stage"] == "feedback" and r["position"] == 66.285
        for r in report["audio"]["events"]
    )
    assert "SECRET" not in json.dumps(report)
    assert report["audio"]["entry_alias"] == collector.emitter.alias(
        "entry", entry.entry_id
    )
    assert report["audio"]["rooms"][0]["player"] == collector.emitter.alias("player", 7)
    assert report["audio"]["rooms"][0]["room"] == collector.emitter.alias(
        "room", "synthetic-zone-7"
    )
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": switch}, blocking=True
    )
    assert not collector.enabled
    assert (
        coordinator.api,
        coordinator.audio_commands,
        coordinator.audio_metadata,
    ) == original
    assert audio_setup.opened == opened
    reload.assert_not_awaited()
    assert (await async_get_config_entry_diagnostics(hass, entry))["audio"]["events"]
    coordinator.api.send_websocket_command.assert_not_awaited()
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert collector.closed
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    restarted = hass.data[DOMAIN][entry.entry_id].audio_diagnostics
    assert not restarted.enabled
    assert restarted.emitter.alias("player", 7) == collector.emitter.alias("player", 7)


async def test_enabled_restart_two_entry_isolation_and_persisted_loss_counters(
    hass, audio_setup, monkeypatch, tmp_path
):
    hass.config.config_dir = str(tmp_path)
    original_refresh = LoxoneCoordinator.async_config_entry_first_refresh

    async def refresh(coordinator):
        await original_refresh(coordinator)
        if coordinator.config_entry.title == "Second synthetic entry":
            controls = coordinator.miniserver.lox_config.json["controls"]
            coordinator.miniserver.lox_config.json["controls"] = {
                "second-" + key: {
                    **value,
                    "uuidAction": "second-" + value["uuidAction"],
                    "states": {k: "second-" + v for k, v in value["states"].items()},
                }
                for key, value in controls.items()
            }

    monkeypatch.setattr(LoxoneCoordinator, "async_config_entry_first_refresh", refresh)
    first = await audio_setup.setup(playback=True)
    second = await audio_setup.setup(
        host="second-audio.example.invalid",
        title="Second synthetic entry",
        playback=True,
    )
    a = hass.data[DOMAIN][first.entry_id].audio_diagnostics
    b = hass.data[DOMAIN][second.entry_id].audio_diagnostics
    await a.async_set_enabled(True)
    for n in range(600):
        a.emit("feedback", player=7, position=n)
    assert a.queue.qsize() == 256
    assert b.queue.empty() and not b.enabled
    assert a.emitter.alias("player", 7) != b.emitter.alias("player", 7)
    original = a.journal._atomic

    def fail(*args):
        raise OSError("SECRET full-disk text")

    monkeypatch.setattr(a.journal, "_atomic", fail)
    await a.async_flush()
    assert a.storage_failures > 0 and a.dropped_storage == 256
    monkeypatch.setattr(a.journal, "_atomic", original)
    a.emit("feedback", player=7, position=700)
    report = await a.async_export()
    assert "SECRET" not in json.dumps(report)
    losses = (a.dropped_queue, a.dropped_storage, a.storage_failures)
    assert losses[0] >= 344
    assert await hass.config_entries.async_unload(first.entry_id)
    assert await hass.config_entries.async_setup(first.entry_id)
    await hass.async_block_till_done()
    restored = hass.data[DOMAIN][first.entry_id].audio_diagnostics
    assert restored.enabled, "Explicit ON must survive ordinary restart"
    assert (
        restored.dropped_queue,
        restored.dropped_storage,
        restored.storage_failures,
    ) == losses
    assert not b.enabled


async def test_existing_admin_download_route_bounds_real_ha_json_and_excludes_raw_house(
    hass, audio_setup, monkeypatch, tmp_path
):
    from aiohttp.test_utils import make_mocked_request
    from homeassistant.components import diagnostics as ha_diagnostics
    from homeassistant.components import http
    from homeassistant.setup import async_setup_component
    from homeassistant.exceptions import Unauthorized
    from types import SimpleNamespace

    hass.config.config_dir = str(tmp_path)
    assert await async_setup_component(hass, "diagnostics", {})
    entry = await audio_setup.setup(playback=True)
    collector = hass.data[DOMAIN][entry.entry_id].audio_diagnostics
    await collector.async_set_enabled(True)
    for batch in range(35):
        for n in range(128):
            collector.emit("feedback", player=7, position=batch * 128 + n)
        await collector.async_flush()
    await hass.async_block_till_done()
    request = make_mocked_request(
        "GET", "/api/diagnostics/config_entry/" + entry.entry_id, app=hass.http.app
    )
    request["hass_user"] = SimpleNamespace(is_admin=True)
    response = await ha_diagnostics.DownloadDiagnosticsView().get(
        request, "config_entry", entry.entry_id
    )
    assert response.status == 200
    assert response.headers["Content-Disposition"].endswith('.json"')
    payload = json.loads(response.text)
    assert "audio" in payload["data"] and "LoxAPP3.json" not in payload["data"]
    assert len(response.text.encode()) <= 1024 * 1024, (
        "The actual HA pretty-printed download must remain bounded"
    )
    assert payload["data"]["audio"]["export_omitted_records"] > 0
    assert "synthetic-password" not in response.text
    assert "miniserver.example.invalid" not in response.text
    request["hass_user"] = SimpleNamespace(is_admin=False)
    with pytest.raises(Unauthorized):
        await ha_diagnostics.DownloadDiagnosticsView().get(
            request, "config_entry", entry.entry_id
        )
    request["hass_user"] = SimpleNamespace(is_admin=True)
    import asyncio

    report, _, _ = await asyncio.gather(
        collector.async_export(),
        collector.async_set_enabled(False),
        hass.config_entries.async_unload(entry.entry_id),
    )
    assert not collector.enabled and collector.closed
    response = await ha_diagnostics.DownloadDiagnosticsView().get(
        request, "config_entry", entry.entry_id
    )
    assert json.loads(response.text)["data"]["error"] == "Config entry is not loaded"


async def test_cancelled_flush_keeps_executor_ownership_until_disk_finishes(
    hass, audio_setup, monkeypatch, tmp_path
):
    import asyncio
    import threading

    hass.config.config_dir = str(tmp_path)
    entry = await audio_setup.setup(playback=True)
    collector = hass.data[DOMAIN][entry.entry_id].audio_diagnostics
    # Stop only this test's writer so the explicitly coordinated flush owns I/O.
    collector._task.cancel()
    await asyncio.gather(collector._task, return_exceptions=True)
    started = threading.Event()
    release = threading.Event()
    overlapping = threading.Event()
    original = collector.journal.maintain
    calls = 0

    def maintain(rows):
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            if not release.wait(5):
                raise TimeoutError("Synthetic writer deadline")
        elif not release.is_set():
            overlapping.set()
        return original(rows)

    monkeypatch.setattr(collector.journal, "maintain", maintain)
    flush = asyncio.create_task(collector.async_flush())
    export = None
    try:
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.001)
        assert started.is_set()
        flush.cancel()
        export = asyncio.create_task(collector.async_export())
        await asyncio.sleep(0.02)
        assert not overlapping.is_set(), (
            "Cancellation must not release the disk lock while its executor is writing"
        )
    finally:
        release.set()
        results = await asyncio.gather(
            flush, *([] if export is None else [export]), return_exceptions=True
        )
        assert isinstance(results[0], asyncio.CancelledError)


async def test_entry_writer_continues_beyond_24h_and_expires_when_disabled(
    hass, audio_setup, tmp_path
):
    from datetime import UTC, datetime

    hass.config.config_dir = str(tmp_path)
    entry = await audio_setup.setup(playback=True)
    collector = hass.data[DOMAIN][entry.entry_id].audio_diagnostics
    await collector.async_set_enabled(True)
    clock = [100000.0]
    collector.journal.clock = lambda: clock[0]

    def event(sequence):
        return {
            "schema": 1,
            "stage": "feedback",
            "sequence": sequence,
            "monotonic": float(sequence),
            "utc": datetime.fromtimestamp(clock[0], UTC).isoformat(),
            "position": float(sequence),
        }

    collector._enqueue(event(1))
    await collector.async_flush()
    clock[0] += 86401
    collector._enqueue(event(2))
    report = await collector.async_export()
    assert collector.enabled
    assert [r["sequence"] for r in report["events"]] == [2]
    await collector.async_set_enabled(False)
    clock[0] += 86401
    # Wake the actual disabled background housekeeping path, not export's filter.
    collector.wake.set()
    import asyncio

    for _ in range(100):
        if not list(collector.journal.path.glob("*.jsonl")):
            break
        await asyncio.sleep(0.01)
    assert not list(collector.journal.path.glob("*.jsonl"))
    assert not collector.enabled and not collector._task.done()
    assert (await collector.async_export())["events"] == []


async def test_synthetic_collector_load_measurement(
    hass, audio_setup, tmp_path, monkeypatch
):
    import os
    from pathlib import Path
    import time

    hass.config.config_dir = str(tmp_path)
    entry = await audio_setup.setup(playback=True)
    collector = hass.data[DOMAIN][entry.entry_id].audio_diagnostics

    def memory():
        return {
            line.split(":")[0]: line.split(":", 1)[1].strip()
            for line in Path("/proc/self/status").read_text().splitlines()
            if line.startswith(("VmRSS:", "VmHWM:"))
        }

    measurements = {
        "kind": "synthetic HA harness; not household load or per-day forecast",
        "memory_before": memory(),
    }
    n = 10000
    start = time.perf_counter()
    cpu = time.process_time()
    for i in range(n):
        collector.emit("feedback", player=7, position=i)
    measurements["disabled"] = {
        "events_offered": n,
        "elapsed_seconds": time.perf_counter() - start,
        "process_cpu_seconds": time.process_time() - cpu,
        "queue_events": collector.queue.qsize(),
    }
    assert collector.queue.empty() and not collector.journal.path.exists()
    await collector.async_set_enabled(True)
    writes = []
    original = collector.journal._atomic

    def atomic(name, data):
        writes.append(len(data))
        return original(name, data)

    monkeypatch.setattr(collector.journal, "_atomic", atomic)
    start = time.perf_counter()
    cpu = time.process_time()
    for batch in range(80):
        for i in range(128):
            collector.emit("feedback", player=7, position=batch * 128 + i)
        await collector.async_flush()
    elapsed = time.perf_counter() - start
    measurements["enabled"] = {
        "events_offered": 10240,
        "elapsed_seconds": elapsed,
        "process_cpu_seconds": time.process_time() - cpu,
        "events_per_second": 10240 / elapsed,
        "journal_bytes": sum(
            p.stat().st_size for p in collector.journal.path.iterdir()
        ),
        "atomic_write_count": len(writes),
        "atomic_bytes_written": sum(writes),
        "memory_after": memory(),
    }
    start = time.perf_counter()
    cpu = time.process_time()
    report = await collector.async_export()
    measurements["export"] = {
        "elapsed_seconds": time.perf_counter() - start,
        "process_cpu_seconds": time.process_time() - cpu,
        "nested_pretty_bytes": len(
            json.dumps({"data": {"audio": report}}, indent=2).encode()
        ),
        "events": len(report["events"]),
        "omitted": report["export_omitted_records"],
    }
    assert measurements["export"]["nested_pretty_bytes"] <= 1024 * 1024 - 65536
    assert collector.dropped_queue == 0 and collector.dropped_storage == 0
    if output := os.environ.get("AUDIO_RESOURCE_RECEIPT"):
        Path(output).write_text(json.dumps(measurements, indent=2) + "\n")
