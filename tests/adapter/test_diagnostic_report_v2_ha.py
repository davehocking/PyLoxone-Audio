"""All-source diagnostic incident evidence must survive routine progress noise."""
from datetime import UTC, datetime
import json
import pytest
from custom_components.loxone import media_player
from custom_components.loxone import audio_diagnostics as module


def event(sequence, stage="feedback", source="library", request=False):
    row={"schema":1,"stage":stage,"sequence":sequence,"utc":datetime.fromtimestamp(100000+sequence,UTC).isoformat(),"monotonic":float(sequence),"source":source,"player":"player-"+"a"*20}
    if request:row["request_id"]="request_id-"+"b"*20
    else:row["position"]=float(sequence)
    return row


@pytest.mark.parametrize("source",["tunein","loxoneradio","spotify","library","linein","airplay"])
def test_export_retains_old_command_timeline_before_recent_feedback(tmp_path,monkeypatch,source):
    journal=module.RollingJournal(tmp_path/'journal',clock=lambda:100500.,disk_bytes=100000,segment_bytes=8000,export_bytes=6000)
    stages=["request","authenticated","send_completed","reply"]
    journal.maintain([event(i,stage,source,True)for i,stage in enumerate(stages)]+[event(i,source=source)for i in range(4,124)])
    report=journal.export()
    assert [r['stage']for r in report['events']if 'request_id'in r]==stages,"Recent progress must not push the entire incident out of the download"
    assert report['export_omitted_records']>0
    assert report['export_omitted_important_records']==0
    assert report['events'][-1]['sequence']==123
    monkeypatch.setattr(module,'EXPORT_BYTES',65536+4500)
    bounded=module.EntryAudioDiagnostics._bound_export(report)
    assert [r['stage']for r in bounded['events']if 'request_id'in r]==stages
    assert len(json.dumps({'data':{'audio':bounded}},indent=2).encode())<=4500
    assert bounded['export_omitted_important_records']==0


def test_priority_export_reports_important_omissions_when_even_commands_exceed_cap(tmp_path):
    journal=module.RollingJournal(tmp_path/'journal',clock=lambda:100500.,disk_bytes=100000,segment_bytes=8000,export_bytes=1800)
    journal.maintain([event(i,'request','spotify',True)for i in range(30)])
    report=journal.export()
    assert report['export_omitted_important_records']==report['export_omitted_records']>0
    assert len(json.dumps(report).encode())<=1800
    assert report['events'][-1]['sequence']==29
