"""Literal trusted-gesture emissions through actual registered owning HA services.

Invented identities only. The browser has 32 synthetic rooms; this owning fixture
projects the exact six existing identities, preserving both controlled groups and
all request targets/volumes. No household/native endpoint is contacted.
"""
import copy
import hashlib
import json
import os
from pathlib import Path

import pytest
from custom_components.loxone.const import SENDDOMAIN
from test_audio_grouping_ha import action, row
from test_audio_grouping_ha import grouped_setup as grouped_setup, audio_setup as audio_setup
from test_room_transport_ha import catalogue_state

ROOT = Path(__file__).resolve().parents[2]
FRONT = ROOT / 'tests/frontend'
TRACE = FRONT / 'gm03-mobile-requests.json'
PROVENANCE = json.loads((FRONT / 'gm03-mobile-provenance.json').read_text())
if hashlib.sha256(TRACE.read_bytes()).hexdigest() != PROVENANCE['requests_sha256']:
    raise RuntimeError('Literal mobile gesture fixture digest mismatch')
ASSET = ROOT / PROVENANCE['asset']
if hashlib.sha256(ASSET.read_bytes()).hexdigest() != PROVENANCE['module_sha256']:
    raise RuntimeError('Mobile gesture frontend epoch mismatch')
REQUESTS = json.loads(TRACE.read_text())


@pytest.mark.parametrize('index', range(len(REQUESTS)))
async def test_literal_mobile_release_registered_service_to_native_bus(hass, grouped_setup, index):
    request = REQUESTS[index]
    g = grouped_setup
    entry, co, ids = await g.setup()
    await g.feed(entry, row('one', (1, 2)), row('outside', (3, 4)))
    states = request['states']
    levels = {p: round(states[i]['attributes']['loxone_room_volume_level'] * 100) for p, i in ids.items()}
    await g.callbacks[entry.entry_id]['callback']({**{f'play-{p}': 1 for p in ids}, **{f'volume-{p}': v for p, v in levels.items()}})
    await hass.async_block_till_done()
    groups = {i: list(hass.states.get(i).attributes['group_members']) for i in ids.values()}
    assert all(groups[i] == states[i]['attributes']['group_members'] for i in ids.values())
    preserved = {i: copy.deepcopy(catalogue_state(e)) for i, e in g.entities.items()}
    raw = {i: hass.states.get(i).attributes['loxone_room_volume_level'] for i in ids.values()}
    target = request['target']['entity_id']
    player = next(p for p, i in ids.items() if i == target)
    if request['service'] == 'volume_set':
        wanted = round(request['data']['volume_level'] * 100)
        mean = (2 * (levels[1] + levels[2]) + 2) // 4
        updated = {p: max(0, min(100, levels[p] + wanted - mean)) for p in (1, 2)}
    else:
        assert request['domain'] == 'loxone' and request['service'] == 'audio_room_volume'
        updated = {player: request['data']['volume_percent']}
    expected = [{'uuid': action(p), 'value': f'volume/{v}'} for p, v in updated.items() if v != levels[p]]
    wires = []

    async def feedback(event):
        wires.append(dict(event.data))
        p = next(p for p in ids if action(p) == event.data['uuid'])
        await g.callbacks[entry.entry_id]['callback']({f'volume-{p}': int(event.data['value'].split('/')[1])})

    remove = hass.bus.async_listen(SENDDOMAIN, feedback)
    co.api.send_websocket_command.reset_mock()
    try:
        await hass.services.async_call(request['domain'], request['service'], request['data'], target=request['target'], blocking=True)
        await hass.async_block_till_done()
        receipt = os.getenv('PYLOXONE_PROJECT_RECEIPT')
        if not receipt:
            raise RuntimeError('Required synthetic owning-test receipt path absent')
        Path(receipt).with_name(f'mobile-wire-{index:02d}.json').write_text(json.dumps({'request': request, 'expected': expected, 'wires': wires, 'serialized': [list(c.args) for c in co.api.send_websocket_command.await_args_list]}, indent=2) + '\n')
        assert wires == expected
        assert [list(c.args) for c in co.api.send_websocket_command.await_args_list] == [[v['uuid'], v['value']] for v in expected]
        for p, value in updated.items():
            raw[ids[p]] = value / 100
        assert {i: hass.states.get(i).attributes['loxone_room_volume_level'] for i in ids.values()} == raw
        assert hass.states.get(ids[1]).attributes['volume_level'] == ((2 * sum(round(raw[ids[p]] * 100) for p in (1, 2)) + 2) // 4) / 100
        assert {i: hass.states.get(i).attributes['group_members'] for i in ids.values()} == groups
        assert {i: catalogue_state(e) for i, e in g.entities.items()} == preserved
        assert not co.audio_grouping.native._scope and not co.audio_grouping.native._requests and not co.audio_grouping.native._tasks
        assert all(not e._transport_tasks for e in g.entities.values())
    finally:
        remove()
        await co.audio_commands.async_close()
