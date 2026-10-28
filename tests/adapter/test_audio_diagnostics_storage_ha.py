"""Synthetic local files/clock only; never use household/configuration data."""

from datetime import UTC, datetime
import importlib.util
import json
from pathlib import Path
import pytest
from custom_components.loxone import media_player  # Owning-host import guard context.


def journal(path, clock, **limits):
    spec = importlib.util.find_spec("custom_components.loxone.audio_diagnostics")
    assert spec is not None, "The entry-owned bounded diagnostics journal is missing"
    from custom_components.loxone.audio_diagnostics import RollingJournal

    return RollingJournal(path, clock=lambda: clock[0], **limits)


def row(clock, sequence=1):
    return {
        "schema": 1,
        "stage": "feedback",
        "sequence": sequence,
        "utc": datetime.fromtimestamp(clock[0], UTC).isoformat(),
        "monotonic": float(sequence),
        "player": "player-" + "a" * 20,
        "position": 66.285,
    }


def test_rolling_age_is_not_run_timeout_and_off_evidence_expires(tmp_path):
    clock = [100000.0]
    j = journal(tmp_path / "journal", clock)
    j.maintain([row(clock)])
    assert len(j.export()["events"]) == 1
    # Exactly24h expires; keep accepting new evidence beyond that horizon.
    clock[0] += 86400
    j.maintain([row(clock, 2)])
    report = j.export()
    assert [r["sequence"] for r in report["events"]] == [2]
    assert report["retention_seconds"] == 86400
    clock[0] += 86401
    j.maintain([])
    assert j.export()["events"] == []
    assert not list((tmp_path / "journal").glob("*.jsonl"))


def test_disk_segments_and_export_rotate_oldest_with_honest_coverage(tmp_path):
    clock = [100000.0]
    j = journal(
        tmp_path / "journal",
        clock,
        disk_bytes=1600,
        segment_bytes=400,
        export_bytes=900,
    )
    j.maintain([row(clock, n) for n in range(40)])
    report = j.export()
    assert sum(p.stat().st_size for p in j.path.glob("*.jsonl")) <= 1600
    assert all(p.stat().st_size <= 400 for p in j.path.glob("*.jsonl"))
    assert len(json.dumps(report).encode()) <= 900
    assert report["rotated_records"] > 0
    assert report["export_omitted_records"] > 0
    assert report["events"][-1]["sequence"] == 39
    assert report["coverage_oldest_utc"] is not None
    assert report["complete_24h"] is False
    again = journal(j.path, clock, disk_bytes=1600, segment_bytes=400, export_bytes=900)
    assert again.export()["rotated_records"] == report["rotated_records"]


def test_recovery_rejects_raw_fields_partial_tails_and_future_records(tmp_path):
    clock = [100000.0]
    j = journal(tmp_path / "journal", clock)
    j.maintain([row(clock)])
    p = next(j.path.glob("*.jsonl"))
    with p.open("ab") as out:
        out.write(json.dumps({**row(clock, 2), "raw": "SECRET"}).encode() + b"\n")
        out.write(b'{"token":"SECRET"')
    report = journal(j.path, clock).export()
    assert len(report["events"]) == 1
    assert "SECRET" not in json.dumps(report)
    assert report["invalid_records"] >= 2
    # Sanitisation is before persistence as well as export.
    j.maintain([{**row(clock, 3), "raw": "SECRET"}])
    assert all(b"SECRET" not in p.read_bytes() for p in j.path.glob("*.jsonl"))
    assert j.path.stat().st_mode & 0o777 == 0o700
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in j.path.iterdir())


def test_no_default_off_directory_and_no_symlink_following(tmp_path):
    clock = [100000.0]
    j = journal(tmp_path / "journal", clock)
    assert j.export()["events"] == []
    assert not j.path.exists()
    outside = tmp_path / "sentinel"
    outside.write_text("SECRET")
    j.path.mkdir()
    (j.path / "events-000000.jsonl").symlink_to(outside)
    import pytest

    with pytest.raises(OSError):
        j.maintain([row(clock)])
    assert outside.read_text() == "SECRET"


def test_cap_rotation_does_not_rewrite_all_surviving_segments(tmp_path, monkeypatch):
    clock = [100000.0]
    j = journal(tmp_path / "journal", clock, disk_bytes=3200, segment_bytes=800)
    j.maintain([row(clock, n) for n in range(20)])
    before = {p.name: p.read_bytes() for p in j.path.glob("*.jsonl")}
    writes = []
    original = j._atomic

    def write(name, data):
        writes.append(name)
        return original(name, data)

    monkeypatch.setattr(j, "_atomic", write)
    j.maintain([row(clock, 9)])
    rewritten = [
        name for name in writes if name in before and name.startswith("events-")
    ]
    assert len(rewritten) <= 1, (
        "A new event must not rewrite every retained segment at the cap"
    )
    assert j.export()["events"][-1]["sequence"] == 9


def test_export_encoding_is_linear_in_retained_events(tmp_path, monkeypatch):
    from custom_components.loxone import audio_diagnostics as module

    clock = [100000.0]
    j = journal(tmp_path / "journal", clock, export_bytes=1000)
    j.maintain([row(clock, n) for n in range(200)])
    original = module.json.dumps
    encoded_events = []

    def dumps(value, *args, **kwargs):
        if isinstance(value, dict) and "events" in value:
            encoded_events.append(len(value["events"]))
        return original(value, *args, **kwargs)

    monkeypatch.setattr(module.json, "dumps", dumps)
    report = j.export()
    assert sum(encoded_events) <= 400, (
        "Repeatedly serialising the entire shrinking report is quadratic"
    )
    assert len(original(report).encode()) <= 1000


def test_formatted_export_reserves_final_coverage_metadata(monkeypatch):
    from custom_components.loxone import audio_diagnostics as module

    rows = [row([100000.0], n) for n in range(2)]
    report = {"events": rows, "export_omitted_records": 0}
    # Exactly fills the former pre-coverage budget. Final coverage is payload too.
    budget = len(json.dumps({"data": {"audio": report}}, indent=2).encode())
    monkeypatch.setattr(module, "EXPORT_BYTES", 65536 + budget)
    result = module.EntryAudioDiagnostics._bound_export(report)
    assert len(json.dumps({"data": {"audio": result}}, indent=2).encode()) <= budget
    assert result["export_omitted_records"] == 1
    assert result["export_oldest_utc"] == rows[1]["utc"]


@pytest.mark.parametrize(
    "state", ["[]", "null", '{"dropped_queue":"SECRET"}', '{"dropped_queue":-1}']
)
def test_restart_recovers_malformed_counter_metadata(tmp_path, state):
    clock = [100000.0]
    j = journal(tmp_path / "journal", clock)
    j.maintain([row(clock)])
    (j.path / "state.json").write_text(state)
    report = journal(j.path, clock).export()
    assert len(report["events"]) == 1
    assert report["dropped_queue"] == 0
    assert "SECRET" not in json.dumps(report)


def test_partial_atomic_write_keeps_only_committed_records(tmp_path, monkeypatch):
    from custom_components.loxone import audio_diagnostics as module

    clock = [100000.0]
    j = journal(tmp_path / "journal", clock)
    j.maintain([row(clock)])
    original = module.os.replace

    def fail_replace(*args):
        raise OSError("Synthetic disk full")

    monkeypatch.setattr(module.os, "replace", fail_replace)
    with pytest.raises(OSError):
        j.maintain([row(clock, 2)])
    assert not list(j.path.glob("*.tmp"))
    monkeypatch.setattr(module.os, "replace", original)
    assert [r["sequence"] for r in j.export()["events"]] == [1]
    j.maintain([row(clock, 3)])
    assert [r["sequence"] for r in journal(j.path, clock).export()["events"]] == [1, 3]
