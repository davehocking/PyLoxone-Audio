"""Literal compiled-native/custom requests through registered HA and native feedback."""
import json
import os
from pathlib import Path
import pytest
from unittest.mock import call as api_call
from custom_components.loxone.const import SENDDOMAIN
from test_audio_grouping_ha import grouped_setup, audio_setup, structure, row, action


def _stepper_calls():
    trace = os.environ.get('GM03_BROWSER_REQUESTS')
    if not trace:
        raise RuntimeError('Required invented stepper trace missing')
    calls = json.loads(Path(trace).read_text())
    if not isinstance(calls, list) or not calls:
        raise RuntimeError('Invented stepper trace must be nonempty list')
    return calls


@pytest.mark.parametrize('index', range(len(_stepper_calls())))
async def test_literal_debounced_custom_stepper_requests(hass, grouped_setup, index):
    trace = os.environ.get('GM03_BROWSER_REQUESTS')
    if not trace:
        raise RuntimeError('Required invented volume-v3 literal requests missing')
    calls = json.loads(Path(trace).read_text())
    assert calls == _stepper_calls()
    call = calls[index]
    expected_service = call['service']
    assert expected_service in {'audio_room_volume', 'audio_group_volume'}
    assert call['service'] == expected_service
    assert call['domain'] == 'loxone'
    assert set(call['data']) == {'volume_percent'}
    assert type(call['data']['volume_percent']) is int
    assert 0 <= call['data']['volume_percent'] <= 100
    g = grouped_setup
    g.source.clear(); g.source.update(structure(13))
    entry, co, _ = await g.setup()
    ids = {e._audio_player_id:i for i,e in g.entities.items()}
    numbers = {i:p for p,i in ids.items()}
    states = call['states']
    assert len([i for i in states if i in numbers]) == 13
    target = (call.get('target') or {}).get('entity_id') or call['data']['entity_id']
    assert target in numbers
    groups = {}
    for entity_id in ids.values():
        descriptor = states[entity_id]['attributes']['loxone_group_control']
        assert descriptor['version'] == 3
        if descriptor.get('group_id') is not None:
            groups[descriptor['group_id']] = tuple(numbers[i] for i in descriptor['members'])
    await g.feed(entry, *(row(name, players) for name,players in groups.items()))
    old = {p:round(states[i]['attributes']['loxone_room_volume_level']*100) for p,i in ids.items()}
    await g.callbacks[entry.entry_id]['callback']({**{f'play-{p}':1 for p in ids}, **{f'volume-{p}':v for p,v in old.items()}})
    await hass.async_block_till_done()
    original_groups = co.audio_grouping.native.snapshot.groups
    members = tuple(numbers[i] for i in states[target]['attributes']['group_members']) if expected_service == 'audio_group_volume' else (numbers[target],)
    wanted = call['data']['volume_percent']
    mean = (2*sum(old[p] for p in members)+len(members))//(2*len(members))
    expected = {p:max(0,min(100,v+wanted-mean)) if p in members else v for p,v in old.items()}
    writes = []
    async def feedback(event):
        writes.append(dict(event.data))
        player = next(p for p in ids if action(p) == event.data['uuid'])
        await g.callbacks[entry.entry_id]['callback']({f'volume-{player}':int(event.data['value'].split('/')[1])})
    remove = hass.bus.async_listen(SENDDOMAIN,feedback)
    try:
        await hass.services.async_call(call['domain'],call['service'],call['data'],target=call.get('target'),blocking=True)
        await hass.async_block_till_done()
        assert writes == [{'uuid':action(p),'value':f'volume/{expected[p]}'} for p in members if expected[p] != old[p]]
        assert {p:g.entities[i]._room_volume_percent for p,i in ids.items()} == expected
        assert {p:hass.states.get(i).attributes['volume_level'] for p,i in ids.items()} == {p:v/100 for p,v in expected.items()}
        assert co.audio_grouping.native.snapshot.groups == original_groups
        assert not co.audio_grouping.native._scope and not co.audio_grouping.native._requests
        assert not co.audio_grouping.native._lock.locked()
        assert co.api.send_websocket_command.call_args_list == [api_call(w['uuid'],w['value']) for w in writes]
    finally:
        remove()
