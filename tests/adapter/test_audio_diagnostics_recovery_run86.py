"""R85-01: decoded JSON cannot poison committed neighbours or OFF expiry."""
import json

import pytest
from custom_components.loxone import media_player, spotify_continuity, audio_sources
from custom_components.loxone.audio_diagnostics import RollingJournal, _safe_event
from test_audio_diagnostics_storage_ha import row


@pytest.mark.parametrize('stage', [[], {}, None, 42], ids=['list', 'object', 'null', 'numeric'])
def test_malformed_stage_restart_repair_append_off_expiry(tmp_path, stage):
    clock = [100000.0]
    path = tmp_path / 'journal'
    journal = RollingJournal(path, clock=lambda: clock[0])
    journal.maintain([row(clock, 1)])
    segment = next(path.glob('events-*.jsonl'))
    with segment.open('ab') as output:
        for record in [{**row(clock, 2), 'stage': stage}, row(clock, 3)]:
            output.write(json.dumps(record).encode() + b'\n')
    restarted = RollingJournal(path, clock=lambda: clock[0])
    report = restarted.export()
    assert [r['sequence'] for r in report['events']] == [1, 3]
    assert report['invalid_records'] == 1
    assert all(_safe_event(json.loads(line)) for line in segment.read_bytes().splitlines())
    restarted.maintain([row(clock, 4)])
    restarted = RollingJournal(path, clock=lambda: clock[0])
    assert [r['sequence'] for r in restarted.export()['events']] == [1, 3, 4]
    clock[0] += 86401
    restarted.maintain([])
    assert not list(path.glob('events-*.jsonl'))
    assert restarted.export()['events'] == []


@pytest.mark.parametrize('value', [None, [], {}, 1, 'foreign', {'schema': 1, 'stage': []}, {'schema': 1, 'stage': {}}])
def test_safe_event_total_on_decoded_json(value):
    assert _safe_event(value) is False
