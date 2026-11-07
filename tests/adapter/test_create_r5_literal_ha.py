"""Exact Stage A compiled native Create emissions through registered HA + synthetic wire."""
import copy
import json
import os
from pathlib import Path

import pytest
from custom_components.loxone.pyloxone_api import audioserver as wire
from test_audio_grouping_ha import audio_setup, grouped_setup, STATE, row, payload
from test_audioserver_playback import SyntheticAudioSocket, rsa_key
from test_gm03_browser_states_ha import fixed_entry
from test_room_transport_ha import catalogue_state


@pytest.mark.parametrize('index', range(2), ids=['portrait', 'short-landscape'])
async def test_exact_native_create_one_wire_and_preservation(hass, grouped_setup, fixed_entry, monkeypatch, rsa_key, index):
    calls = json.loads(Path(os.environ['GM03_BROWSER_REQUESTS']).read_text())
    assert len(calls) == 2
    call = calls[index]
    g = grouped_setup
    entry, co, ids = await g.setup()
    co.audio_commands._credentials = lambda: ('synthetic-user', 'synthetic-active-token')
    co.api.get_token_dict = lambda: {'token': 'synthetic-active-token', 'valid_until': 9999999999}
    # Exact inherited synthetic history used to export removed-five initial state.
    await g.feed(entry, row('one', (1, 2, 5)), row('outside', (3, 4)))
    # Native update removes the old row and appends its replacement: preserve
    # literal row order because it participates in the exported revision hash.
    rows = [row('outside', (3, 4)), row('one', (1, 2))]
    await g.feed(entry, *rows)
    await g.callbacks[entry.entry_id]['callback']({**{f'play-{p}': 1 for p in ids}, **{f'volume-{p}': v for p, v in zip(ids, [10, 40, 60, 90, 20, 30])}})
    await hass.async_block_till_done()
    for i in ids.values():
        actual = hass.states.get(i).attributes
        before = call['states'][i]['attributes']
        for key in ['group_members', 'loxone_group_control', 'volume_level', 'loxone_room_volume_level']:
            assert actual[key] == before[key], (i, key)
    assert call['domain'] == 'loxone' and call['service'] == 'audio_group_manage'
    assert call['target'] == {'entity_id': ids[5]}
    assert call['data'] == {'action': 'create', 'revision': co.audio_grouping.control_descriptor(5)['revision'], 'members': [ids[6]]}
    commands, sockets = [], []
    catalogue = {i: copy.deepcopy(catalogue_state(e)) for i, e in g.entities.items()}
    class Socket(SyntheticAudioSocket):
        async def send(self, message):
            if message.startswith('audio/cfg/dgroup/update/'):
                self.sent.append(message)
                commands.append(message)
                assert message == 'audio/cfg/dgroup/update/new/5,6'
                self.queue.put_nowait(json.dumps({'dgroup_update_result': {'id': 'created'}}))
                await g.callbacks[entry.entry_id]['callback']({STATE: payload(*rows, row('created', (5, 6)))})
                return
            await super().send(message)

    def connect(*args, **kwargs):
        s = Socket(rsa_key)
        sockets.append(s)
        return s

    monkeypatch.setattr(wire, 'connect', connect)
    try:
        await hass.services.async_call(call['domain'], call['service'], copy.deepcopy(call['data']), target=copy.deepcopy(call['target']), blocking=True)
        await hass.async_block_till_done()
        assert commands == ['audio/cfg/dgroup/update/new/5,6']
        assert len(sockets) == 1 and sockets[0].closed
        assert sum(m.startswith('secure/authenticate/') for m in sockets[0].sent) == 1
        assert hass.states.get(ids[5]).attributes['group_members'] == [ids[5], ids[6]]
        assert hass.states.get(ids[1]).attributes['group_members'] == [ids[1], ids[2]]
        assert hass.states.get(ids[3]).attributes['group_members'] == [ids[3], ids[4]]
        assert {i: catalogue_state(e) for i, e in g.entities.items()} == catalogue
        assert not co.audio_grouping.native._scope and not co.audio_grouping.native._requests and not co.audio_grouping.native._tasks
        assert all(not e._transport_tasks for e in g.entities.values())
        co.api.send_websocket_command.assert_not_awaited()
        Path(os.environ['PYLOXONE_PROJECT_RECEIPT']).with_name(f'create-wire-{index}.json').write_text(json.dumps({'literal': call, 'commands': commands, 'authenticated_sockets': len(sockets), 'closed': True, 'confirmed': True}, indent=2) + '\n')
    finally:
        await co.audio_commands.async_close()
