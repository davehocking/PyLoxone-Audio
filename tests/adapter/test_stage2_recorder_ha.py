"""Exact synthetic timeline -> HA state events -> real SQLite Recorder rows."""
import asyncio

from datetime import datetime, timedelta
import json


import pytest
from homeassistant.core import callback
from homeassistant.util import dt as dt_util
from homeassistant.components.media_player.significant_change import async_check_significant_change
from homeassistant.components.recorder.db_schema import States, StatesMeta, StateAttributes
from pytest_homeassistant.components.recorder.common import async_wait_recording_done
from sqlalchemy import select
from test_audioserver_ha import audio_setup
from test_audioserver_playback import rsa_key
from test_audio_modes_ha import mode_harness
from test_stage2_modes_ha import output
from custom_components.loxone.const import EVENT
from pyloxone_audio import native


async def rows_since(recorder, marker=0):
    def read():
        with recorder.get_session() as session:
            rows = session.execute(select(States.state_id, States.state, States.last_updated_ts,
                StatesMeta.entity_id, StateAttributes.shared_attrs)
                .join(StatesMeta, States.metadata_id == StatesMeta.metadata_id)
                .join(StateAttributes, States.attributes_id == StateAttributes.attributes_id)
                .where(States.state_id > marker).order_by(States.state_id)).all()
            return [{"state_id": r[0], "state": r[1], "last_updated_ts": r[2], "entity_id": r[3],
                     "attributes": json.loads(r[4])} for r in rows]
    return await recorder.async_add_executor_job(read)


@pytest.mark.usefixtures("recorder_db_url")
async def test_linear_native_clock_does_not_persist_redundant_rows_per_zone(
    hass, recorder_mock, audio_setup, monkeypatch, rsa_key,
):
    # Fixed elapsed sample schedule, not a measurement of the owner's room.
    start = dt_util.utcnow()
    clock = [start]

    class SampleClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0].astimezone(tz) if tz is not None else clock[0].replace(tzinfo=None)

    monkeypatch.setattr(native, "datetime", SampleClock)
    monkeypatch.setattr(dt_util, "utcnow", lambda: clock[0])
    h = await mode_harness(hass, audio_setup, monkeypatch, rsa_key, source="library")
    rooms = {p: h.entities[p] for p in (7, 8, 9, 10)}
    modes = {7: "play", 8: "play", 9: "pause", 10: "stop"}
    for p in range(1, 13):
        hass.bus.async_fire(EVENT, {f"play-{p}": 2 if p in (7, 8) else 1 if p == 9 else 0})
    for p in rooms:
        h.rows[p] = {**h.rows[p], "time": 30, "mode": modes[p]}
        await h.emit(h.rows[p])
    await async_wait_recording_done(hass)
    initial = await rows_since(recorder_mock)
    marker = max(r["state_id"] for r in initial)
    entity_ids = {room.entity_id for room in rooms.values()}
    input_timeline = [{"elapsed": elapsed, "rows": [
        {**h.rows[p], "time": 30 + elapsed if modes[p] == "play" else 30}
        for p in rooms]} for elapsed in range(4, 61, 4)]
    output("recorder-input.json", {"duration_seconds": 60, "frames": input_timeline})
    events, processed, progress = [], [], []
    phase = [0]

    @callback
    def relevant(data):
        return data.get("entity_id") in entity_ids

    @callback
    def observe(event):
        new = event.data.get("new_state")
        old = event.data.get("old_state")
        events.append({"elapsed": phase[0], "type": event.event_type, "entity_id": event.data["entity_id"],
                       "state": new.state if new else None, "attributes": dict(new.attributes) if new else None,
                       "significant": (async_check_significant_change(hass, old.state, dict(old.attributes),
                          new.state, dict(new.attributes)) if old and new else True)})

    removes = [hass.bus.async_listen("state_changed", observe, event_filter=relevant),
               hass.bus.async_listen("state_reported", observe, event_filter=relevant)]
    process = recorder_mock._process_state_changed_event_into_session

    def record_process(event):
        if event.data.get("entity_id") in entity_ids:
            processed.append({"entity_id": event.data["entity_id"],
                              "timestamp": event.data["new_state"].last_updated_timestamp})
        return process(event)

    monkeypatch.setattr(recorder_mock, "_process_state_changed_event_into_session", record_process)
    try:
        for frame in input_timeline:
            elapsed = frame["elapsed"]
            phase[0] = elapsed
            clock[0] = start + timedelta(seconds=elapsed)
            for row in frame["rows"]:
                await h.emit(row)
            await hass.async_block_till_done()
            for p, room in rooms.items():
                state = hass.states.get(room.entity_id)
                pos = state.attributes["media_position"]
                if modes[p] == "play":
                    pos += (clock[0] - state.attributes["media_position_updated_at"]).total_seconds()
                progress.append({"elapsed": elapsed, "player": p, "displayed": pos,
                                 "native": 30 + elapsed if modes[p] == "play" else 30})
        await async_wait_recording_done(hass)
        persisted = [r for r in await rows_since(recorder_mock, marker) if r["entity_id"] in entity_ids]
        counts = {room.entity_id: {
            "state_reported": sum(e["type"] == "state_reported" and e["entity_id"] == room.entity_id for e in events),
            "state_changed": sum(e["type"] == "state_changed" and e["entity_id"] == room.entity_id for e in events),
            "significant_state_changed": sum(e["type"] == "state_changed" and e["entity_id"] == room.entity_id and e["significant"] for e in events),
            "recorder_queue_processed": sum(e["entity_id"] == room.entity_id for e in processed),
            "persisted_rows": sum(r["entity_id"] == room.entity_id for r in persisted),
            "native_mode": modes[p],
        } for p, room in rooms.items()}
        output("recorder-linear.json", {"duration_seconds": 60, "sample_interval_seconds": 4,
            "synthetic_only": True, "counts": counts, "events": events, "queue_processed": processed,
            "persisted": persisted, "progress": progress})
        linear_event_count = len(events)
        transition_marker = max([marker, *(r["state_id"] for r in persisted)])
        transition_inputs = []
        for label, fields, ms in [
            ("track", {"audiopath": "library:local:track:next", "title": "Next title", "time": 1}, {}),
            ("external-seek", {"time": 55}, {}),
            ("shuffle-repeat", {"plshuffle": True, "plrepeat": 1}, {}),
            ("pause", {"mode": "pause"}, {"play-7": 1}),
            ("resume", {"mode": "play", "time": 57}, {"play-7": 2}),
            ("volume", {}, {"volume-7": 41}),
            ("source", {"audiopath": "tunein:station:synthetic", "sourceName": "TuneIn",
                        "parent": {"id": "tunein:container:synthetic"}, "title": "Station",
                        "time": None, "duration": None}, {}),
        ]:
            phase[0] += 1
            clock[0] = start + timedelta(seconds=phase[0])
            h.rows[7] = {**h.rows[7], **fields}
            transition_inputs.append({"label": label, "elapsed": phase[0], "row": h.rows[7], "ms": ms})
            if ms:
                hass.bus.async_fire(EVENT, ms)
            await h.emit(h.rows[7])
            await hass.async_block_till_done()
            await async_wait_recording_done(hass)
            state = hass.states.get(rooms[7].entity_id)
            assert any(e["entity_id"] == rooms[7].entity_id and e["elapsed"] == phase[0]
                       and e["type"] == "state_changed" for e in events), label
            if label == "external-seek":
                assert state.attributes["media_position"] == 55
            if label == "shuffle-repeat":
                assert state.attributes["shuffle"] is True and state.attributes["repeat"] == "all"
            if label in {"pause", "resume"}:
                assert state.state == ("paused" if label == "pause" else "playing")
            if label == "volume":
                assert state.attributes["volume_level"] == 0.41
            if label == "source":
                assert state.attributes["source"] == "TuneIn"
        transition_rows = [r for r in await rows_since(recorder_mock, transition_marker)
                           if r["entity_id"] in entity_ids]
        output("recorder-transition-input.json", transition_inputs)
        output("recorder-transitions.json", {"events": events[linear_event_count:], "persisted": transition_rows})
        assert len(transition_rows) >= 7
        assert all(abs(row["displayed"] - row["native"]) <= 0.000001 for row in progress)
        assert all(c["persisted_rows"] == 0 for c in counts.values()), counts
        assert all(c["state_changed"] == 0 for c in counts.values()), counts
        assert all(c["state_reported"] == 15 for c in counts.values()), counts
    finally:
        for remove in removes:
            remove()
