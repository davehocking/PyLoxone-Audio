"""F3 trusted new-press/pointer recovery literals through the registered HA owner.

Browser input stays immutable and separate from fresh owning state timestamps.
Every one of the 34 recovery calls is exercised; no household I/O.
"""
import copy
import json
import os
from pathlib import Path

import pytest
from custom_components.loxone.const import SENDDOMAIN
from test_audio_grouping_ha import action, row
from test_audio_grouping_ha import audio_setup, grouped_setup
from test_audioserver_playback import rsa_key
from test_gm03_browser_states_ha import fixed_entry
from test_owner_removal_scroll_r2_ha import test_owner_removal_registered_native_confirmation as replay_removal
from test_room_transport_ha import catalogue_state


@pytest.mark.parametrize('index', range(34))
async def test_f3_literal_new_press_recovery(hass, grouped_setup, fixed_entry, monkeypatch, rsa_key, index):
    source = Path(os.environ['GM03_BROWSER_REQUESTS'])
    requests = json.loads(source.read_text())
    assert len(requests) == 34
    request = requests[index]['request']
    if request['service'] == 'audio_group_manage':
        # Reuse the accepted exact authenticated wire/confirmation assertions,
        # not a replacement removal implementation or a normalized payload.
        literals = source.with_name('f3-removal-literals.json')
        all_requests = json.loads(literals.read_text())
        assert all_requests == [r['request'] for r in requests]
        monkeypatch.setenv('GM03_FOCUS_REQUESTS', str(literals))
        await replay_removal(hass, grouped_setup, fixed_entry, monkeypatch, rsa_key, index)
        return
    assert request['domain'] == 'loxone' and request['service'] == 'audio_room_volume'
    assert request['target'] == {'entity_id': 'media_player.synthetic_speaker_5'}
    assert request['data'] in [{'volume_percent': 21}, {'volume_percent': 61}]
    g = grouped_setup
    entry, co, ids = await g.setup()
    co.api.get_token_dict = lambda: {'token': 'synthetic-active-token', 'valid_until': 9999999999}
    co.audio_commands._credentials = lambda: ('synthetic-user', 'synthetic-active-token')
    await g.feed(entry, row('one', (1, 2, 5)), row('outside', (3, 4)))
    before = request['states']
    levels = {p: round(before[i]['attributes']['loxone_room_volume_level'] * 100) for p, i in ids.items()}
    await g.callbacks[entry.entry_id]['callback']({**{f'play-{p}': 1 for p in ids}, **{f'volume-{p}': value for p, value in levels.items()}})
    await hass.async_block_till_done()
    for i in ids.values():
        actual = hass.states.get(i).attributes
        for key in ['group_members', 'loxone_group_control', 'loxone_room_volume_level', 'volume_level']:
            assert actual[key] == before[i]['attributes'][key]
    groups = {i: list(hass.states.get(i).attributes['group_members']) for i in ids.values()}
    catalogue = {i: copy.deepcopy(catalogue_state(e)) for i, e in g.entities.items()}
    wanted = request['data']['volume_percent']
    expected = [{'uuid': action(5), 'value': f'volume/{wanted}'}]
    wires = []

    async def feedback(event):
        wires.append(dict(event.data))
        assert event.data == expected[0]
        await g.callbacks[entry.entry_id]['callback']({'volume-5': wanted})

    remove = hass.bus.async_listen(SENDDOMAIN, feedback)
    co.api.send_websocket_command.reset_mock()
    try:
        await hass.services.async_call(request['domain'], request['service'], copy.deepcopy(request['data']), target=copy.deepcopy(request['target']), blocking=True)
        await hass.async_block_till_done()
        serialized = [list(c.args) for c in co.api.send_websocket_command.await_args_list]
        assert wires == expected
        assert serialized == [[action(5), f'volume/{wanted}']]
        assert {i: hass.states.get(i).attributes['group_members'] for i in ids.values()} == groups
        levels[5] = wanted
        assert {i: hass.states.get(i).attributes['loxone_room_volume_level'] for i in ids.values()} == {i: levels[p] / 100 for p, i in ids.items()}
        assert {i: catalogue_state(e) for i, e in g.entities.items()} == catalogue
        assert not co.audio_grouping.native._scope and not co.audio_grouping.native._requests and not co.audio_grouping.native._tasks
        assert all(not e._transport_tasks for e in g.entities.values())
        Path(os.environ['PYLOXONE_PROJECT_RECEIPT']).with_name(f'f3-volume-{index:02d}.json').write_text(json.dumps({'literal': requests[index], 'expected': expected, 'wires': wires, 'serialized': serialized, 'confirmed_own_percent': round(hass.states.get(ids[5]).attributes['loxone_room_volume_level'] * 100)}, indent=2) + '\n')
    finally:
        remove()
        await co.audio_commands.async_close()
