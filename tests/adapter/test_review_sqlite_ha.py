"""Reviewer-owned file-backed SQLite and adversarial native clock probes."""
from datetime import datetime, timedelta
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3

import pytest
from homeassistant.util import dt as dt_util
from pytest_homeassistant.components.recorder.common import async_wait_recording_done
from test_audioserver_ha import audio_setup
from test_audioserver_playback import rsa_key
from test_audio_modes_ha import mode_harness
from test_stage2_modes_ha import output
import test_stage2_recorder_ha as original
from pyloxone_audio import native, clock as native_clock
from custom_components.loxone.const import EVENT

pytestmark=pytest.mark.usefixtures('recorder_db_url')

@pytest.fixture
def recorder_db_url(hass_fixture_setup, request):
    assert not hass_fixture_setup
    root=Path(os.environ['STAGE2_EVIDENCE_ROOT'])
    root.mkdir(parents=True,exist_ok=True)
    name=request.node.name.replace('[','-').replace(']','')
    return 'sqlite:///'+str(root/(name+'.db'))

async def committed_backup(hass,db_url,label):
    await async_wait_recording_done(hass)
    original_path=Path(db_url.removeprefix('sqlite:///'))
    backup=original_path.with_name(original_path.stem+'-committed.db')
    def read():
        with closing(sqlite3.connect('file:'+str(original_path)+'?mode=ro',uri=True)) as source:
            with closing(sqlite3.connect(backup)) as dest:
                source.backup(dest)
        with closing(sqlite3.connect('file:'+str(backup)+'?mode=ro',uri=True)) as db:
            assert db.execute('pragma integrity_check').fetchone()==('ok',)
            rows=[{'state_id':r[0],'entity_id':r[1],'state':r[2],'attributes':json.loads(r[3]),'last_updated_ts':r[4]}
                  for r in db.execute('select s.state_id,m.entity_id,s.state,a.shared_attrs,s.last_updated_ts from states s '
                     'join states_meta m on s.metadata_id=m.metadata_id '
                     'join state_attributes a on s.attributes_id=a.attributes_id order by s.state_id')]
            return {'source_database':str(original_path),'committed_backup':str(backup),'rows':rows,
                    'integrity_check':'ok','sqlite_version':sqlite3.sqlite_version}
    evidence=await hass.async_add_executor_job(read)
    output(label+'.json',evidence)
    return evidence

async def test_review_committed_original_timeline(
    hass,recorder_mock,recorder_db_url,audio_setup,monkeypatch,rsa_key,
):
    # Exact original acceptance body/assertions. Only persistent database URL
    # differs, and the external read/backup happens even on genuine baseline RED.
    try:
        await original.test_linear_native_clock_does_not_persist_redundant_rows_per_zone(
            hass,recorder_mock,audio_setup,monkeypatch,rsa_key)
    finally:
        await committed_backup(hass,recorder_db_url,'original-timeline-committed')

CASES={
    'rounding-jitter':[(4,34.2),(8,37.7),(12,42.1),(16,45.5)],
    'cumulative-drift':[(4,34.2),(8,38.4),(12,42.6),(16,46.8)],
    'external-forward-seek':[(4,75),(8,79)],
    'external-rewind':[(4,10),(8,14)],
    'nonmonotonic-wallclock':[(4,34),(2,32),(7,37)],
    'wallclock-before-anchor':[(4,34),(-1,31),(3,35)],
}

@pytest.mark.parametrize('case',list(CASES))
async def test_review_native_clock_deviation_is_bounded_and_real_seeks_persist(
    hass,recorder_mock,recorder_db_url,audio_setup,monkeypatch,rsa_key,case,
):
    start=dt_util.utcnow();wall=[start]
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):
            return wall[0].astimezone(tz) if tz is not None else wall[0].replace(tzinfo=None)
    monkeypatch.setattr(native,'datetime',Clock)
    monkeypatch.setattr(native_clock,'datetime',Clock)
    monkeypatch.setattr(dt_util,'utcnow',lambda:wall[0])
    h=await mode_harness(hass,audio_setup,monkeypatch,rsa_key,source='library')
    room=h.entities[7]
    h.rows[7]={**h.rows[7],'time':30}
    await h.emit(h.rows[7]);await async_wait_recording_done(hass)
    before=await original.rows_since(recorder_mock)
    marker=max(r['state_id'] for r in before)
    observed=[]
    for elapsed,position in CASES[case]:
        wall[0]=start+timedelta(seconds=elapsed)
        h.rows[7]={**h.rows[7],'time':position}
        await h.emit(h.rows[7]);await hass.async_block_till_done()
        state=hass.states.get(room.entity_id)
        anchor=state.attributes['media_position']
        stamp=state.attributes['media_position_updated_at']
        displayed=min(state.attributes['media_duration'],anchor+max(0,(wall[0]-stamp).total_seconds()))
        observed.append({'elapsed':elapsed,'native':position,'displayed':displayed,'anchor':anchor,'stamp':str(stamp),'ha_last_updated_ts':state.last_updated_timestamp})
        assert abs(displayed-position)<=0.500001
        assert h.metadata._client.get(7).position==position,'Raw native samples must survive coalescing'
        assert h.metadata._client.get(7).received_at==wall[0]
    evidence=await committed_backup(hass,recorder_db_url,'clock-'+case+'-committed')
    rows=[r for r in evidence['rows'] if r['state_id']>marker and r['entity_id']==room.entity_id]
    if case in {'external-forward-seek','external-rewind'}:
        # Core intentionally excludes progress attrs from Recorder; preserve
        # exact HA progress plus the committed event row, not invented columns.
        assert rows and any(r['last_updated_ts']==observed[0]['ha_last_updated_ts'] for r in rows)
        assert observed[0]['anchor']==CASES[case][0][1]
    output('clock-'+case+'.json',{'inputs':CASES[case],'observed':observed,'new_committed_rows':rows,
                                'synthetic':True,'queue_or_runtime_throttle_modified':False})

@pytest.mark.parametrize('mode',['pause','stop'])
async def test_review_subsecond_pause_correction_remains_exact_in_sqlite(
    hass,recorder_mock,recorder_db_url,audio_setup,monkeypatch,rsa_key,mode,
):
    start=dt_util.utcnow();wall=[start]
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return wall[0].astimezone(tz) if tz is not None else wall[0].replace(tzinfo=None)
    monkeypatch.setattr(native,'datetime',Clock)
    monkeypatch.setattr(native_clock,'datetime',Clock)
    monkeypatch.setattr(dt_util,'utcnow',lambda:wall[0])
    h=await mode_harness(hass,audio_setup,monkeypatch,rsa_key,source='library');room=h.entities[7]
    wall[0]=start+timedelta(seconds=4)
    hass.bus.async_fire(EVENT,{'play-7':1 if mode=='pause' else 0})
    await hass.async_block_till_done()
    row={**h.rows[7],'mode':mode,'time':30.25}
    await h.emit(row);await hass.async_block_till_done()
    assert room.media_position==30.25
    state=hass.states.get(room.entity_id)
    evidence=await committed_backup(hass,recorder_db_url,'subsecond-'+mode+'-committed')
    rows=[r for r in evidence['rows'] if r['entity_id']==room.entity_id]
    assert rows[-1]['last_updated_ts']==state.last_updated_timestamp
    assert rows[-1]['state']==state.state
    assert 'media_position' not in rows[-1]['attributes']
