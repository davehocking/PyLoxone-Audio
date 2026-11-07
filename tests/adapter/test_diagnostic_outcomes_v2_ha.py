"""HA action outcomes must cover final validation, not just an early reply."""
import asyncio
import json
from types import SimpleNamespace
import pytest
from homeassistant.exceptions import HomeAssistantError
from custom_components.loxone import audio_diagnostics as module
from pyloxone_audio.diagnostic_events import DiagnosticEmitter
from test_audioserver_ha import audio_setup
from test_source_return_simplification_ha import rsa_key,simplified_harness,select,sent_commands
from custom_components.loxone.const import DOMAIN


def instrument(operation):
    factory=getattr(module,'audio_operation',None)
    assert callable(factory),'Final owning-HA diagnostic outcome boundary is missing'
    return factory(operation)


@pytest.mark.parametrize('failure',[None,'late_guard','cancelled','timeout'])
async def test_action_result_follows_reply_and_final_cleanup_without_changing_exception(failure):
    rows=[];d=DiagnosticEmitter(b'synthetic-key',rows.append);d.enabled=True
    marker=asyncio.current_task()
    error={'late_guard':HomeAssistantError('SECRET failure details'),'cancelled':asyncio.CancelledError(),'timeout':TimeoutError()} .get(failure)
    class Entity:
        _audio_diagnostics=d
        _audio_player_id=7
        _audio_metadata=None
        _audio_grouping=None
        _room_volume_percent=37
        _context=SimpleNamespace(id='synthetic-ha-context')
        uuidAction='synthetic-private-room'
        available=True
        state='paused'
        @instrument('media_play')
        async def action(self):
            assert asyncio.current_task()is marker
            d.emit('reply',request_id='native-command',transport='audio_server')
            await asyncio.sleep(0)
            if error is not None:raise error
            return 'unchanged-result'
    if error is None:assert await Entity().action()=='unchanged-result'
    else:
        with pytest.raises(type(error))as caught:await Entity().action()
        assert caught.value is error
    assert [r['stage']for r in rows]==['operation_started','state_snapshot','reply','state_snapshot','operation_finished']
    expected={'late_guard':'error','cancelled':'cancelled','timeout':'timeout'}.get(failure,'returned')
    assert rows[-1]['outcome']==expected
    assert rows[-1]['elapsed_ms']>=0
    assert rows[-1]['monotonic']>=rows[2]['monotonic']
    assert len({r['operation_id']for r in rows})==1
    assert rows[1]['volume']==37
    assert 'SECRET'not in json.dumps(rows)


async def test_disabled_or_broken_observer_does_not_inspect_snapshot_or_change_action():
    rows=[];d=DiagnosticEmitter(b'synthetic-key',rows.append)
    class Entity:
        _audio_diagnostics=d
        @property
        def _audio_metadata(self):raise AssertionError('Disabled diagnostic snapshot work')
        @instrument('media_play')
        async def action(self):return 42
    assert await Entity().action()==42
    assert rows==[]
    d.enabled=True
    # Even malformed observation must remain a logging-only failure.
    assert await Entity().action()==42


@pytest.mark.parametrize('spotify',[False,True])
async def test_complete_actual_ha_source_return_correlates_both_native_commands(hass,audio_setup,monkeypatch,rsa_key,tmp_path,spotify):
    hass.config.config_dir=str(tmp_path)
    entity,controls,sockets,emit=await simplified_harness(hass,audio_setup,monkeypatch,rsa_key,spotify=spotify)
    collector=next(iter(hass.data[DOMAIN].values())).audio_diagnostics
    await collector.async_set_enabled(True)
    await select(hass,entity,spotify=spotify)
    report=await collector.async_export();rows=report['events']
    terminal=[r for r in rows if r['stage']=='operation_finished'and r.get('operation')=='select_source']
    assert len(terminal)==1 and terminal[0]['outcome']=='returned'
    operation=terminal[0]['operation_id']
    snapshots=[r for r in rows if r['stage']=='state_snapshot'and r.get('operation_id')==operation]
    assert [r['phase']for r in snapshots]==['before','after']
    service=[r for r in rows if r['stage']=='ha_service_request'and r.get('operation')=='select_source']
    assert len(service)==1 and service[0].get('ha_context_id')==terminal[0]['ha_context_id']
    assert 'operation_id'not in service[0], 'A shared HA context is not a unique owning invocation'
    requests=[r for r in rows if r['stage']=='request']
    assert len(requests)==2 and all(r.get('operation_id')==operation for r in requests)
    assert len({r['request_id']for r in requests})==2
    assert len(sent_commands(sockets))==2 and all(s.closed for s in sockets)
    assert 'synthetic-active-token'not in json.dumps(report)
