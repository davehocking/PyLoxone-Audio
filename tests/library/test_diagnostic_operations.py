"""Portable operation correlation, lifetime and privacy under synthetic input."""
import asyncio
import json
import pytest
from pyloxone_audio import diagnostic_events as module


def operation(identifier):
    factory=getattr(module,'diagnostic_operation',None)
    assert callable(factory),'Cross-command diagnostic operation correlation is missing'
    return factory(identifier)


@pytest.mark.parametrize('source',['tunein','loxoneradio','spotify','library','linein','airplay'])
def test_all_sources_share_operation_but_keep_distinct_native_requests(source):
    rows=[];d=module.DiagnosticEmitter(b'synthetic-not-secret',rows.append);d.enabled=True
    with operation('HA-action-private-context'):
        d.emit('operation_started',source=source,transport='ha_service')
        d.emit('request',source=source,request_id='native-command-1')
        d.emit('reply',source=source,request_id='native-command-1')
        d.emit('request',source=source,request_id='native-command-2')
        d.emit('operation_finished',outcome='returned',elapsed_ms=30.)
    assert len(rows)==5
    assert len({r['operation_id']for r in rows})==1
    assert rows[1]['request_id']!=rows[3]['request_id']
    assert rows[-1]['elapsed_ms']==30.
    assert rows[-1]['outcome']=='returned'
    assert 'private-context'not in json.dumps(rows)
    d.emit('feedback',source=source)
    assert 'operation_id'not in rows[-1]


async def test_late_background_task_cannot_keep_an_expired_operation_context():
    rows=[];d=module.DiagnosticEmitter(b'synthetic-key',rows.append);d.enabled=True
    ready=asyncio.Event()
    async def later():
        await ready.wait();d.emit('feedback',player=1)
    with operation('old-operation'):
        task=asyncio.create_task(later())
    ready.set();await task
    assert 'operation_id'not in rows[0]


def test_new_fields_remain_fixed_schema_and_distinguish_zero_permissions():
    rows=[];d=module.DiagnosticEmitter(b'synthetic-key',rows.append);d.enabled=True
    with operation('private-context'):
        d.emit('state_snapshot',phase='before',playback_restrictions=0,capability_present=True,capability_valid=True,ha_state='paused',outcome='SECRET',elapsed_ms=float('nan'),raw='SECRET',error_message='SECRET')
    assert rows and rows[0]['playback_restrictions']==0
    assert rows[0]['capability_valid'] is True
    assert rows[0]['ha_state']=='paused'
    assert 'SECRET'not in json.dumps(rows)
    assert 'elapsed_ms'not in rows[0]
