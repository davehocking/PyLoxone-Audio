"""Source-independent feedback sampling and causal queue protection."""
import asyncio
from datetime import UTC,datetime
from types import SimpleNamespace
import json
import pytest
from custom_components.loxone.audio_diagnostics import EntryAudioDiagnostics
from custom_components.loxone.const import DOMAIN
from test_audioserver_ha import audio_setup


def collector(hass):
    owner=EntryAudioDiagnostics(hass,SimpleNamespace(entry_id='synthetic-entry'),{})
    owner.emitter.enabled=True
    return owner


def row(owner,sequence,stage='feedback',**fields):
    return {'schema':1,'sequence':sequence,'utc':datetime.now(UTC).isoformat(),'monotonic':1000+sequence*.1,'stage':stage,'player':owner.emitter.alias('player',7),'transport':'audio_server','position':sequence*.1,**fields}


async def test_progress_and_bookmark_noise_is_sampled_but_signal_changes_and_jumps_survive(hass):
    owner=collector(hass)
    for i in range(1,1001):owner._enqueue(row(owner,i))
    assert owner.queue.qsize()<=6,'Routine feedback still crowds out useful incident history'
    assert owner.sampled_routine_records>900
    changes=[{'content':owner.emitter.alias('content','new-track')},{'volume':38},{'playback_restrictions':0,'capability_present':True,'capability_valid':True},{'position':1}]
    for i,fields in enumerate(changes,1001):owner._enqueue(row(owner,i,**fields))
    result=[]
    while not owner.queue.empty():result.append(owner.queue.get_nowait())
    for fields in changes:assert any(all(r.get(k)==v for k,v in fields.items())for r in result)
    assert all(r.get('signal_changed')is True for r in result[-4:])
    for i in range(2001,3001):owner._enqueue(row(owner,i,stage='session_saved'))
    assert owner.queue.qsize()<=6


async def test_any_audio_command_opens_short_bounded_high_detail_window(hass):
    owner=collector(hass)
    owner._enqueue(row(owner,1))
    owner._enqueue(row(owner,2,stage='request'))
    for i in range(3,203):owner._enqueue(row(owner,i))
    detail=owner.queue.qsize()
    assert 30<detail<100,'Missing bounded around-command feedback detail'
    for i in range(1001,1201):owner._enqueue(row(owner,i))
    assert owner.queue.qsize()-detail<=3,'Detail window did not expire'


async def test_full_queue_keeps_commands_ahead_of_routine_rows_and_counts_real_important_loss(hass):
    owner=collector(hass);owner.queue=asyncio.Queue(maxsize=3)
    owner._enqueue(row(owner,1,stage='request'))
    # This is an ordinary heartbeat, not the first changed-state feedback.
    owner._enqueue(row(owner,2,stage='session_saved'));owner.queue.get_nowait();owner.queue.get_nowait()
    owner._enqueue(row(owner,6,stage='request'))
    owner._enqueue(row(owner,10,stage='session_saved'))
    owner._enqueue(row(owner,11,stage='reply'))
    owner._enqueue(row(owner,12,stage='operation_finished',outcome='returned'))
    rows=[]
    while not owner.queue.empty():rows.append(owner.queue.get_nowait())
    assert [r['stage']for r in rows]==['request','reply','operation_finished']
    assert owner.dropped_queue==1 and owner.dropped_important_queue==0
    for r in rows:owner.queue.put_nowait(r)
    owner._enqueue(row(owner,13,stage='error',reason='rejected'))
    assert owner.dropped_important_queue==1


async def test_actual_receiver_retains_raw_capability_presence_zero_and_invalid_distinctly(hass,audio_setup,tmp_path):
    hass.config.config_dir=str(tmp_path)
    entry=await audio_setup.setup(playback=True)
    owner=hass.data[DOMAIN][entry.entry_id].audio_diagnostics
    await owner.async_set_enabled(True)
    for value in ['missing',0,32,'invalid']:
        frame={'playerid':7,'mode':'play','eventype':0,'audiopath':'spotify:track:synthetic','title':'SECRET-title','time':1,'duration':180}
        if value!='missing':frame['pbr']=value
        await audio_setup.queues[0].put(json.dumps({'audio_event':[frame]}))
        await hass.async_block_till_done()
    report=await owner.async_export()
    rows=[r for r in report['events']if r['stage']=='feedback'and r.get('transport')=='audio_server']
    assert any(r.get('capability_present')is False and r.get('capability_valid')is False and'playback_restrictions'not in r for r in rows)
    assert any(r.get('playback_restrictions')==0 and r.get('capability_valid')is True for r in rows)
    assert any(r.get('playback_restrictions')==32 for r in rows)
    assert any(r.get('capability_present')is True and r.get('capability_valid')is False for r in rows)
    assert 'SECRET'not in json.dumps(report)
