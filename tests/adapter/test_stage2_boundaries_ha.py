"""Literal compiled native requests and persisted group/availability boundaries."""
import json
from pathlib import Path

import pytest
from homeassistant.core import callback
from pytest_homeassistant.components.recorder.common import async_wait_recording_done
from test_audioserver_ha import audio_setup
from test_audioserver_playback import rsa_key
from test_audio_modes_ha import mode_harness
from test_audio_grouping_ha import grouped_setup, row
from test_stage2_modes_ha import output
from test_stage2_recorder_ha import rows_since


async def test_literal_compiled_native_mode_buttons_reach_registered_services_and_native_wire(
    hass, audio_setup, monkeypatch, rsa_key,
):
    trace = json.loads((Path(__file__).resolve().parents[1] / 'frontend/stage2-native-calls.json').read_text())
    assert trace['module_sha256'] == '911eed0c78f7bc13e013e51bddd42e14274bf8d892f18109a2c9d0f96c69660a'
    h = await mode_harness(hass, audio_setup, monkeypatch, rsa_key, source='library')
    h.rows[7] = {**h.rows[7], 'plshuffle': True, 'plrepeat': 3}
    await h.emit(h.rows[7])
    for request in trace['calls']:
        assert request['data']['entity_id'] == h.entities[7].entity_id
        await hass.services.async_call(request['domain'], request['service'], request['data'],
                                       target=request['target'], blocking=True)
    await hass.async_block_till_done()
    assert h.writes == ['audio/7/shuffle/disable', 'audio/7/repeat/0']
    assert h.entities[7].shuffle is False and h.entities[7].repeat == 'off'
    assert all(socket.closed for socket in h.sockets)
    output('native-mode-literal-replay.json', {'trace': trace, 'native_writes': h.writes,
        'actual_registered_services': True, 'native_auth_feedback': True,
        'hardware_efficacy': 'UNVERIFIED'})


@pytest.mark.usefixtures('recorder_db_url')
async def test_group_volume_disconnect_hard_auth_and_reconnect_persist_without_throttling(
    hass, recorder_mock, grouped_setup,
):
    g = grouped_setup
    entry, co, ids = await g.setup()
    callback_ = g.callbacks[entry.entry_id]['callback']
    state_ = g.callbacks[entry.entry_id]['on_state']
    tracked = {ids[1], ids[2]}
    await callback_({'play-1': 1, 'play-2': 1, 'volume-1': 20, 'volume-2': 40})
    await hass.async_block_till_done()
    await async_wait_recording_done(hass)
    marker = max(r['state_id'] for r in await rows_since(recorder_mock))
    events, phases = [], []
    label = ['']

    @callback
    def changed(event):
        if event.data['entity_id'] in tracked:
            events.append({'phase': label[0], 'entity_id': event.data['entity_id'],
                           'state': event.data['new_state'].state,
                           'attributes': dict(event.data['new_state'].attributes)})

    remove = hass.bus.async_listen('state_changed', changed)
    try:
        for phase in ['group', 'group-volume', 'disconnect', 'reconnect', 'hard-auth-failed', 'auth-recovered']:
            label[0] = phase
            if phase == 'group':
                await g.feed(entry, row('synthetic-group', (1, 2)))
            elif phase == 'group-volume':
                await callback_({'volume-1': 30, 'volume-2': 70})
            else:
                state_('disconnected' if phase == 'disconnect' else 'failed' if phase == 'hard-auth-failed' else 'connected')
                if phase in {'reconnect', 'auth-recovered'}:
                    await callback_({'play-1': 1, 'play-2': 1, 'volume-1': 30, 'volume-2': 70})
            await hass.async_block_till_done()
            await async_wait_recording_done(hass)
            persisted = [r for r in await rows_since(recorder_mock, marker) if r['entity_id'] in tracked]
            assert {r['entity_id'] for r in persisted} == tracked, phase
            assert {e['entity_id'] for e in events if e['phase'] == phase} == tracked, phase
            states = {i: hass.states.get(i) for i in tracked}
            if phase in {'disconnect', 'hard-auth-failed'}:
                assert all(s.state == 'unavailable' for s in states.values())
            else:
                assert all(s.state != 'unavailable' for s in states.values())
            if phase == 'group':
                assert states[ids[1]].attributes['group_members'] == [ids[1], ids[2]]
            if phase == 'group-volume':
                assert states[ids[1]].attributes['loxone_room_volume_level'] == 0.3
                assert states[ids[2]].attributes['loxone_room_volume_level'] == 0.7
                assert states[ids[1]].attributes['volume_level'] == 0.5
            phases.append({'phase': phase, 'persisted': persisted})
            marker = max(r['state_id'] for r in await rows_since(recorder_mock))
        output('recorder-group-availability.json', {'phases': phases, 'state_changed': events,
            'auth_scope': 'synthetic Miniserver supervisor hard-auth-failed callback; not audible or hardware proof'})
    finally:
        remove()
