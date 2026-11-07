"""Stage2 synthetic missing-mode journey; actual receiver/entity/status/services."""
import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from homeassistant.components.media_player import MediaPlayerEntityFeature
from homeassistant.exceptions import HomeAssistantError
from test_audioserver_ha import audio_setup
from test_audioserver_playback import SyntheticAudioSocket, rsa_key
from test_audio_modes_ha import FULL, mode_harness, request
from custom_components.loxone.pyloxone_api import audioserver as wire

BITS = MediaPlayerEntityFeature.SHUFFLE_SET | MediaPlayerEntityFeature.REPEAT_SET


def output(name, value):
    root = os.environ.get("STAGE2_EVIDENCE_ROOT")
    if not root:
        raise RuntimeError("Stage2 evidence fixture key is missing")
    if "STAGE2_UNRELATED_SENTINEL" in os.environ:
        raise RuntimeError("Canonical child inherited unrelated sentinel")
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_text(json.dumps(value, indent=2, default=str) + "\n")


def test_stage2_canonical_fixture_preflight():
    output("environment.json", {"fixture_key_present": True, "unrelated_sentinel_absent": True})


@pytest.mark.parametrize("source", ["spotify", "library"])
async def test_track_missing_modes_recovers_from_fresh_status_not_cached_modes(
    hass, audio_setup, monkeypatch, rsa_key, source,
):
    h = await mode_harness(hass, audio_setup, monkeypatch, rsa_key, source=source)
    room = h.entities[7]
    states = []

    def snapshot(label):
        state = hass.states.get(room.entity_id)
        states.append({"label": label, "entity_id": state.entity_id, "state": state.state,
                       "attributes": dict(state.attributes)})

    snapshot("before")
    assert room.supported_features & BITS == BITS
    entered, release = asyncio.Event(), asyncio.Event()
    sockets, reads = [], []
    old_connect = wire.connect
    status_row = None

    class StatusSocket(SyntheticAudioSocket):
        async def send(self, message):
            if message == "audio/7/status":
                self.sent.append(message)
                reads.append(message)
                entered.set()
                await release.wait()
                self.queue.put_nowait(json.dumps({"status_result": [status_row]}))
            else:
                await super().send(message)

    def connect(*args, **kwargs):
        if not release.is_set():
            socket = StatusSocket(rsa_key)
            sockets.append(socket)
            return socket
        return old_connect(*args, **kwargs)

    monkeypatch.setattr(wire, "connect", connect)
    # Deliberately absent fields, not False/0/null or an unsupported mask.
    changed = {k: v for k, v in h.rows[7].items() if k not in {"plshuffle", "plrepeat", "pbr"}}
    changed.update(audiopath=("library:local" if source == "library" else source) + ":track:next", time=1)
    status_row = {**changed, "plshuffle": True, "plrepeat": 3, "pbr": FULL}
    try:
        await h.emit(changed)
        await hass.async_block_till_done()
        snapshot("missing-awaiting-status")
        assert room.shuffle is None and room.repeat is None, "Never retain the old track's modes"
        assert not room.supported_features & BITS
        try:
            await asyncio.wait_for(entered.wait(), 0.5)
        except TimeoutError:
            pass
        output(f"modes-{source}-pending.json", {"states": states, "reads": reads})
        assert entered.is_set(), "Sparse ordinary track transition never requests fresh native modes"
        release.set()
        await hass.async_block_till_done()
        # Background recovery is deliberately not an HA startup-blocking task.
        for _ in range(200):
            if room.shuffle is True and room.repeat == "one":
                break
            await asyncio.sleep(0)
        await hass.async_block_till_done()
        snapshot("fresh-status")
        assert room.shuffle is True and room.repeat == "one"
        assert room.supported_features & BITS == BITS
        assert reads == ["audio/7/status"]
        assert all(s.closed for s in sockets)
        h.rows[7] = status_row
        await request(hass, h, 7, "shuffle", False)
        await request(hass, h, 7, "repeat", "all")
        await hass.async_block_till_done()
        snapshot("owning-services")
        assert h.writes == ["audio/7/shuffle/disable", "audio/7/repeat/1"]
        assert room.shuffle is False and room.repeat == "all"
        assert "spotify" not in hass.config.components
        output(f"modes-{source}.json", {"states": states, "reads": reads, "writes": h.writes,
                                      "hardware_efficacy": "UNVERIFIED"})
    finally:
        release.set()
    h.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.parametrize("change", [
    {"plshuffle": False, "plrepeat": 0, "pbr": FULL},
    {"pbr": 0}, {"pbr": 32}, {"pbr": 2048}, {"pbr": None},
    {"plshuffle": None}, {"plshuffle": "invalid"}, {"plrepeat": 2},
    {"sourceName": "Another account"}, {"parent": {"id": "spotify:album:another"}},
    {"audiopath": "tunein:station:another"}, {"mode": "pause"},
    {"eventype": 3}, {"audiopath": None},
], ids=["false-zero-complete", "mask-zero", "mask-unsupported", "mask-partial", "mask-null",
        "shuffle-null", "shuffle-invalid", "repeat-invalid", "account", "parent", "source",
        "paused", "event", "empty-path"])
async def test_sparse_mode_repair_does_not_override_explicit_or_context_boundaries(
    hass, audio_setup, monkeypatch, rsa_key, change,
):
    h = await mode_harness(hass, audio_setup, monkeypatch, rsa_key)
    changed = {k: v for k, v in h.rows[7].items() if k not in {"plshuffle", "plrepeat", "pbr"}}
    changed.update(audiopath="spotify:track:next", time=1)
    changed.update(change)
    status = AsyncMock(side_effect=wire.AudioCommandError("Unexpected status read"))
    monkeypatch.setattr(h.commands, "async_player_status", status)
    await h.emit(changed)
    await hass.async_block_till_done()
    await asyncio.sleep(0)
    status.assert_not_awaited()
    assert not getattr(h.metadata, "_requested_refresh", set())
    assert not h.writes
    if change.get("pbr") == FULL:
        assert h.entities[7].shuffle is False and h.entities[7].repeat == "off"
        assert h.entities[7].supported_features & BITS == BITS
    else:
        assert not h.entities[7].supported_features & BITS


async def test_repeated_sparse_track_transitions_are_not_delayed_by_successful_read_freshness(
    hass, audio_setup, monkeypatch, rsa_key,
):
    h = await mode_harness(hass, audio_setup, monkeypatch, rsa_key, source="library")
    reads = []
    row = None

    class StatusSocket(SyntheticAudioSocket):
        async def send(self, message):
            if message == "audio/7/status":
                self.sent.append(message)
                reads.append(message)
                self.queue.put_nowait(json.dumps({"status_result": [row]}))
            else:
                await super().send(message)

    monkeypatch.setattr(wire, "connect", lambda *_a, **_kw: StatusSocket(rsa_key))
    for index in range(3):
        changed = {k: v for k, v in h.rows[7].items() if k not in {"plshuffle", "plrepeat", "pbr"}}
        changed.update(audiopath=f"library:local:track:next-{index}", time=1)
        row = {**changed, "plshuffle": bool(index % 2), "plrepeat": index % 2, "pbr": FULL}
        await h.emit(changed)
        for _ in range(1000):
            if h.entities[7].supported_features & BITS == BITS:
                break
            await asyncio.sleep(0.001)
        assert h.entities[7].supported_features & BITS == BITS
        assert h.entities[7].shuffle is row["plshuffle"]
        h.rows[7] = row
    assert reads == ["audio/7/status"] * 3
    assert not h.writes


@pytest.mark.parametrize("boundary", ["account", "source", "parent", "explicit-denial", "auth", "unload"])
async def test_pending_mode_status_cannot_cross_new_feedback_auth_or_unload(
    hass, audio_setup, monkeypatch, rsa_key, boundary,
):
    h = await mode_harness(hass, audio_setup, monkeypatch, rsa_key, source="library")
    entered, release = asyncio.Event(), asyncio.Event()
    sockets = []
    changed = {k: v for k, v in h.rows[7].items() if k not in {"plshuffle", "plrepeat", "pbr"}}
    changed.update(audiopath="library:local:track:next", time=1)
    stale_reply = {**changed, "plshuffle": True, "plrepeat": 3, "pbr": FULL}

    class StatusSocket(SyntheticAudioSocket):
        async def send(self, message):
            if message == "audio/7/status":
                self.sent.append(message)
                entered.set()
                await release.wait()
                self.queue.put_nowait(json.dumps({"status_result": [stale_reply]}))
            else:
                await super().send(message)

    def connect(*_a, **_kw):
        socket = StatusSocket(rsa_key)
        sockets.append(socket)
        return socket

    monkeypatch.setattr(wire, "connect", connect)
    await h.emit(changed)
    await asyncio.wait_for(entered.wait(), 1)
    try:
        if boundary == "unload":
            assert await hass.config_entries.async_unload(h.entry.entry_id)
        elif boundary == "auth":
            h.commands._credentials = lambda: ("synthetic-user", "synthetic-new-token")
        else:
            delta = {"account": {"sourceName": "Another account"},
                     "source": {"audiopath": "tunein:station:new"},
                     "parent": {"parent": {"id": "library:local:album:another"}},
                     "explicit-denial": {"pbr": 0}}[boundary]
            await h.emit({**changed, **delta})
    finally:
        release.set()
    for _ in range(200):
        if not h.metadata._recoveries:
            break
        await asyncio.sleep(0)
    await hass.async_block_till_done()
    assert not h.entities[7].supported_features & BITS
    assert h.entities[7].shuffle is not True
    assert all(socket.closed for socket in sockets)
    assert not h.writes
