"""Independent-review regressions: partial frames, idle sampling and async dispatch."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from homeassistant.helpers import entity_registry as er
from custom_components.loxone.audio_diagnostics import audio_operation
from custom_components.loxone.const import DOMAIN
from custom_components.loxone.pyloxone_api.connection import LoxoneConnection
from pyloxone_audio.diagnostic_events import DiagnosticEmitter
from test_diagnostic_noise_v2_ha import collector,row
from test_audioserver_ha import audio_setup,zone_entity_id


async def test_alternating_partial_miniserver_feedback_is_not_a_change_flood(hass):
    owner=collector(hass);owner.players={7:'synthetic-zone'}
    owner.states={'v':(7,'volume'),'p':(7,'playState')}
    for _ in range(1000):owner.miniserver_feedback({'v':37,'p':1})
    assert owner.queue.qsize()==2
    assert owner.sampled_routine_records==1998
    assert owner.dropped_important_queue==0
    owner.miniserver_feedback({'v':38,'p':0})
    assert owner.queue.qsize()==4


async def test_status_send_attempt_cannot_open_the_action_detail_window(hass):
    owner=collector(hass)
    owner._enqueue(row(owner,1))
    owner._enqueue(row(owner,2,stage='request',request_kind='status'))
    owner._enqueue(row(owner,3,stage='send_attempt',request_kind='status'))
    for i in range(4,204):owner._enqueue(row(owner,i))
    assert owner.queue.qsize()<=4,'Background status activated high-detail logging'


async def test_overlapping_owning_invocations_with_same_ha_context_have_distinct_ids():
    rows=[];d=DiagnosticEmitter(b'synthetic-key',rows.append);d.enabled=True
    gate=asyncio.Event()
    class Entity:
        _audio_diagnostics=d
        _audio_player_id=7
        _audio_metadata=None
        _audio_grouping=None
        _room_volume_percent=37
        _context=SimpleNamespace(id='same-automation-context')
        uuidAction='synthetic-zone';available=True;state='paused'
        @audio_operation('media_play')
        async def action(self,request):
            d.emit('request',request_id=request)
            await gate.wait()
            d.emit('reply',request_id=request)
    tasks=[asyncio.create_task(Entity().action(value))for value in ['one','two']]
    try:
        await asyncio.sleep(0)
        starts=[r for r in rows if r['stage']=='operation_started']
        assert len(starts)==2
        assert len({r['operation_id']for r in starts})==2
        assert len({r['ha_context_id']for r in starts})==1
    finally:
        gate.set();await asyncio.wait_for(asyncio.gather(*tasks),2)
    for request in ['one','two']:
        child=[r for r in rows if r.get('request_id')==d.alias('request_id',request)]
        assert len(child)==2 and len({r['operation_id']for r in child})==1


@pytest.mark.parametrize('service,extra',[('volume_set',{'volume_level':.37}),('volume_up',{}),('volume_down',{}),('media_next_track',{}),('media_previous_track',{}),('media_play',{}),('media_pause',{})])
async def test_actual_deferred_miniserver_dispatch_keeps_root_correlation_after_ha_return(hass,audio_setup,tmp_path,service,extra):
    hass.config.config_dir=str(tmp_path)
    entry=await audio_setup.setup(playback=False)
    coordinator=hass.data[DOMAIN][entry.entry_id];owner=coordinator.audio_diagnostics
    await owner.async_set_enabled(True)
    gate=asyncio.Event();sent=[]
    connection=LoxoneConnection.__new__(LoxoneConnection);connection.audio_diagnostics=owner
    async def wire(command):sent.append(command)
    connection.connection=SimpleNamespace(protocol=SimpleNamespace(state=SimpleNamespace(name='OPEN')),send=wire)
    async def send(uuid,value):
        await gate.wait()
        await connection._send_text_command(f'jdev/sps/io/{uuid}/{value}',encrypted=False)
    coordinator.api.send_websocket_command=send
    try:
        await hass.services.async_call('media_player',service,{'entity_id':zone_entity_id(hass,7),**extra},blocking=True)
        roots=[r for r in (await owner.async_export())['events']if r['stage']=='operation_finished']
        assert len(roots)==1 and roots[0]['outcome']=='returned'
        assert sent==[],'The test must release the actual send only after owning HA return'
    finally:
        gate.set();await hass.async_block_till_done()
    transport=[r for r in (await owner.async_export())['events']if r.get('transport')=='miniserver'and r['stage']in{'send_attempt','send_completed'}]
    assert len(transport)==2 and len(sent)==1
    assert all(r.get('operation_id')==roots[0]['operation_id']for r in transport)
    assert all(r['monotonic']>=roots[0]['monotonic']for r in transport)
