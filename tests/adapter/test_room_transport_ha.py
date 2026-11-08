"""Owner-decided room-only transport; real HA dispatch and authenticated fake peer.

All identities, credentials and I/O are synthetic. ACK never fabricates playback.
The initial RED uses a registered/scaffolded entity service with the old grouped
routing, so failure is an exact-wire behavioural mismatch, not a missing API.
"""
import asyncio
import copy
import json

import pytest
from homeassistant.exceptions import HomeAssistantError
from custom_components.loxone.pyloxone_api import audioserver as wire
from test_audio_grouping_ha import row
from test_audio_grouping_ha import grouped_setup as grouped_setup
from test_audio_grouping_ha import audio_setup as audio_setup
from test_audioserver_playback import SyntheticAudioSocket
from test_audioserver_playback import rsa_key as rsa_key


def catalogue_state(entity):
    return {key: value for key, value in entity._radio_catalogue.__dict__.items() if key != 'commands'}


@pytest.mark.parametrize('player', [1, 2, 3, 4])
@pytest.mark.parametrize('action', ['play', 'pause'])
async def test_registered_row_service_is_exact_room_but_standard_transport_is_group(
    hass, grouped_setup, monkeypatch, rsa_key, player, action
):
    g = grouped_setup
    entry, co, ids = await g.setup()
    await g.feed(entry, row('native', (2, 1, 3)), row('other', (5, 6)))
    co.audio_commands._credentials = lambda: ('synthetic-user', 'synthetic-active-token')
    sockets = []

    class Socket(SyntheticAudioSocket):
        async def send(self, message):
            if message.startswith('audio/grouped/'):
                self.sent.append(message)
                mode, players = message.split('/')[2:]
                self.queue.put_nowait(json.dumps({f'grouped_{mode}_result': {'players': [
                    {'playerid': int(p), 'mode': mode} for p in players.split(',')
                ]}}))
                return
            if message in (f'audio/{player}/play', f'audio/{player}/pause'):
                self.sent.append(message)
                self.queue.put_nowait(json.dumps({action+'_result': True}))
                return
            await super().send(message)

    def connect(*args, **kwargs):
        socket = Socket(rsa_key)
        sockets.append(socket)
        return socket

    monkeypatch.setattr(wire, 'connect', connect)
    assert hass.services.has_service('loxone', 'audio_room_transport')
    before = {p: (e._source_generation, e._source_feedback, e._source_target,
                  e._source_return_rejection, copy.deepcopy(catalogue_state(e)))
              for p, entity_id in ids.items() for e in (g.entities[entity_id],)}
    states = {i: hass.states.get(i) for i in ids.values()}
    groups = co.audio_grouping.native.snapshot.groups
    await hass.services.async_call('loxone', 'audio_room_transport', {'action': action},
                                   target={'entity_id': ids[player]}, blocking=True)
    messages = [m for s in sockets for m in s.sent if m.startswith('audio/') and m != 'audio/cfg/getkey/full']
    assert messages == [f'audio/{player}/{action}'], 'A row must never redirect to the native leader or group'
    assert co.audio_grouping.native.snapshot.groups == groups
    for p, entity_id in ids.items():
        e = g.entities[entity_id]
        assert (e._source_generation, e._source_feedback, e._source_target,
                e._source_return_rejection, catalogue_state(e)) == before[p]
        assert hass.states.get(entity_id).state == states[entity_id].state
    assert all(s.closed for s in sockets)
    assert co.audio_commands._socket is None
    assert not co.audio_grouping.native._scope
    assert not co.audio_grouping.native._tasks
    assert not co.audio_grouping.native._requests
    assert all(not e._transport_tasks for e in g.entities.values())
    co.api.send_websocket_command.assert_not_awaited()
    # Same follower's ordinary HA action remains whole-group in native order.
    await hass.services.async_call('media_player', 'media_'+action,
                                   {'entity_id': ids[1]}, blocking=True)
    assert [m for s in sockets for m in s.sent if m.startswith('audio/') and m != 'audio/cfg/getkey/full'] == [f'audio/{player}/{action}', f'audio/grouped/{action}/2,1,3']
