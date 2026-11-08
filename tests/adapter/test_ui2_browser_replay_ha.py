"""Additive UI2 semantic AND complete native Chromium traces -> owning HA.

No household I/O. Historical traces, browser and replay oracles stay unchanged.
"""
import copy
import hashlib
import json
import os
from pathlib import Path

import pytest
from homeassistant.exceptions import HomeAssistantError
from custom_components.loxone.pyloxone_api import audioserver as wire
from test_audio_grouping_ha import STATE, action, row, payload
from test_audio_grouping_ha import grouped_setup as grouped_setup
from test_audio_grouping_ha import audio_setup as audio_setup
from test_audioserver_playback import SyntheticAudioSocket
from test_audioserver_playback import rsa_key as rsa_key
from test_room_transport_ha import catalogue_state
from gm03_trace_support import historical_source, VolumeFeedback


async def test_ui2_emitted_calls_through_unchanged_owning_ha(hass, grouped_setup, monkeypatch, rsa_key, tmp_path, caplog):
    root = Path(__file__).resolve().parents[2]
    paths = [Path(os.environ['UI2_BROWSER_TRACE']), Path(os.environ['UI2_NATIVE_TRACE'])]
    traces = [json.loads(p.read_text()) for p in paths]
    for trace in traces:
        for key, name in (
            ('asset_sha256', 'adapters/pyloxone/frontend/dist/group-control-card-0.1.3.dev6-ui2.js'),
            ('source_sha256', historical_source(root,trace)),
            ('states_sha256', 'tests/frontend/room-ui-states.json'),
        ):
            assert hashlib.sha256((root / name).read_bytes()).hexdigest() == trace[key]
    calls = [call for trace in traces for call in trace['calls']]
    g = grouped_setup
    entry, co, ids = await g.setup()
    numbers = {entity_id: p for p, entity_id in ids.items()}
    co.audio_commands._credentials = lambda: ('synthetic-user', 'synthetic-active-token')
    sockets, rows, records = [], [], []
    reject = False

    class Socket(SyntheticAudioSocket):
        async def send(self, message):
            nonlocal rows
            if message.startswith('audio/grouped/'):
                self.sent.append(message)
                _, _, mode, participants = message.split('/')
                self.queue.put_nowait(json.dumps({f'grouped_{mode}_result': {'players': [{'playerid': int(p), 'mode': mode} for p in participants.split(',')]}}))
                return
            if message.startswith('audio/cfg/dgroup/update/'):
                self.sent.append(message)
                parts = message.split('/')
                name = parts[4]
                if reject:
                    self.queue.put_nowait(json.dumps({'dgroup_update_result': False}))
                    return
                # Invented peer gives a newly created native group its own ID.
                name = 'created-ui1' if name == 'new' else name
                members = tuple(map(int, parts[5].split(','))) if len(parts) > 5 else ()
                rows = [r for r in rows if r['group'] != name]
                if members:
                    rows.append(row(name, members))
                await g.callbacks[entry.entry_id]['callback']({STATE: payload(*rows)})
                self.queue.put_nowait(json.dumps({'dgroup_update_result': {'id': name}}))
                return
            if message.startswith('audio/') and message != 'audio/cfg/getkey/full':
                self.sent.append(message)
                _, player, mode = message.split('/')
                assert player.isdecimal() and mode in ('play', 'pause')
                self.queue.put_nowait(json.dumps({mode + '_result': False if reject else True}))
                return
            await super().send(message)

    def connect(*args, **kwargs):
        socket = Socket(rsa_key)
        sockets.append(socket)
        return socket

    monkeypatch.setattr(wire, 'connect', connect)
    feedback=VolumeFeedback(hass,g,entry,ids)
    co.audio_grouping.native.timeout=.15
    for index, original_request in enumerate(calls):
        request = copy.deepcopy(original_request)
        target = request['target']['entity_id']
        assert target in numbers
        rows = [row(group['id'], tuple(numbers[i] for i in group['members'])) for group in request['groups']]
        static = tuple(numbers[i] for i in request['staticEntities'])
        if static:
            rows.append(row('fixed', static, 'static'))
        await g.feed(entry, *rows)
        await g.callbacks[entry.entry_id]['callback']({
            **{f'play-{numbers[i]}': 0 if s['state'] == 'playing' else 1 for i, s in request['states'].items()},
            **{f'volume-{numbers[i]}': round(s['attributes']['volume_level'] * 100) for i, s in request['states'].items()},
        })
        await hass.async_block_till_done()
        before = co.audio_grouping.native.snapshot.groups
        before_members = {i: list(hass.states.get(i).attributes.get('group_members', [i])) for i in ids.values() if i not in request['staticEntities']}
        sources = {i: (e._source_generation, e._source_feedback, e._source_target, e._source_return_rejection, copy.deepcopy(catalogue_state(e))) for i, e in g.entities.items()}
        playback = {i: hass.states.get(i).state for i in ids.values()}
        volumes = {i: hass.states.get(i).attributes.get('volume_level') for i in ids.values()}
        raw={i:hass.states.get(i).attributes.get('loxone_room_volume_level') for i in ids.values()}
        expected_volume=feedback.expected(g,co,target,request['data']['volume_level']) if request['service']=='volume_set' else None
        grouped=not co.audio_grouping.independent(numbers[target])
        co.api.send_websocket_command.reset_mock()
        count = len(sockets)
        reject = request['mode'] == 'reject'
        feedback.reject=reject
        # volume_set follows the unchanged Miniserver transport, not the audio
        # peer socket. Inject rejection at that existing transport mock only.
        co.api.send_websocket_command.side_effect = HomeAssistantError('Synthetic native rejection') if reject and request['service'] == 'volume_set' else None
        caplog.clear()
        call = hass.services.async_call(request['domain'], request['service'], request['data'], target=request['target'], blocking=True)
        if reject and (request['service'] != 'volume_set' or grouped):
            with pytest.raises(HomeAssistantError):
                await call
        else:
            await call
        await hass.async_block_till_done()
        new_sockets = sockets[count:]
        messages = [m for s in new_sockets for m in s.sent if m.startswith('audio/') and m != 'audio/cfg/getkey/full']
        service = request['service']
        if service == 'volume_set':
            assert messages == []
            assert [tuple(c.args) for c in co.api.send_websocket_command.await_args_list]==(expected_volume[:1] if reject else expected_volume)
            # Existing volume sends are entry-owned BACKGROUND tasks. Rejection
            # is logged rather than propagated as a service error. The new UI
            # confirmation predicate must therefore never rely on that ACK.
            if reject:
                assert 'Could not send command' in caplog.text and 'Synthetic native rejection' in caplog.text
            if reject:
                # Successor only to the owner-rejected global volume lockout;
                # original full body/hash and raw failure retained in HERE.
                assert not co.audio_grouping.native.uncertain
                assert {i: hass.states.get(i).attributes.get('volume_level') for i in ids.values()} == volumes
            feedback.assert_raw(hass,raw,[] if reject else expected_volume)
        else:
            co.api.send_websocket_command.assert_not_awaited()
            assert messages
            # Existing SyntheticAudioSocket verifies the actual native challenge/
            # encrypted-auth flow. Retain its transcript and closed-state evidence.
            assert all(any(m.startswith('secure/authenticate/') for m in s.sent) for s in new_sockets)
            if service == 'audio_room_transport':
                assert request['domain'] == 'loxone'
                assert messages == [f"audio/{numbers[target]}/{request['data']['action']}"]
            elif service in ('media_play', 'media_pause'):
                members = before_members[target]
                assert messages == ['audio/grouped/' + ('play' if service == 'media_play' else 'pause') + '/' + ','.join(str(numbers[i]) for i in members)]
            else:
                assert service in ('join', 'unjoin')
                assert all(m.startswith('audio/cfg/dgroup/update/') for m in messages)
                if not reject:
                    expected = copy.deepcopy(before_members)
                    if service == 'join':
                        additions = request['data']['group_members']
                        destination = before_members[target] + [i for i in additions if i not in before_members[target]]
                        for i, members in before_members.items():
                            if i not in destination:
                                expected[i] = [m for m in members if m not in additions] or [i]
                        for i in destination:
                            expected[i] = destination
                    else:
                        survivors = [i for i in before_members[target] if i != target]
                        expected[target] = [target]
                        for i in survivors:
                            expected[i] = survivors
                    assert {i: list(hass.states.get(i).attributes['group_members']) for i in expected} == expected
        for i, entity in g.entities.items():
            current = (entity._source_generation, entity._source_feedback, entity._source_target, entity._source_return_rejection, catalogue_state(entity))
            if service in ('join', 'unjoin'):
                # Existing dev6 intentionally advances its source-intent fence on
                # topology changes; retained account/bookmarks are not replaced.
                assert current[1:] == sources[i][1:]
            else:
                assert current == sources[i]
            assert hass.states.get(i).state == playback[i], 'ACK/group feedback never fabricates playback'
        if service in ('audio_room_transport', 'media_play', 'media_pause', 'volume_set'):
            assert co.audio_grouping.native.snapshot.groups == before
        if reject and service != 'volume_set':
            assert co.audio_grouping.native.uncertain == (service in ('join', 'unjoin'))
        if static:
            assert any(group.group_id == 'fixed' and group.players == static for group in co.audio_grouping.native.snapshot.groups)
        assert all(s.closed for s in sockets) and co.audio_commands._socket is None
        assert not co.audio_grouping.native._scope and not co.audio_grouping.native._requests and not co.audio_grouping.native._tasks
        assert all(not e._transport_tasks for e in g.entities.values())
        records.append({'index': index, 'request': original_request, 'wire': messages, 'authenticated_sockets': len(new_sockets), 'expected_rejection': reject, 'ha_error_expected': reject and (service != 'volume_set' or grouped), 'volume_confirmation_requires_native_feedback': service == 'volume_set'})
    assert len(records) == len(calls) > 30
    feedback.remove()
    assert any(r['request']['service'] == 'join' and r['request']['target']['entity_id'] == ids[4] for r in records)
    assert any(r['request']['service'] == 'unjoin' and r['request']['target']['entity_id'] == ids[4] for r in records)
    assert len(traces[1]['calls']) == 4, 'Every actual native-app websocket request included'
    receipt_path = Path(os.environ['UI2_REPLAY_RECEIPT']) if 'UI2_REPLAY_RECEIPT' in os.environ else tmp_path / 'ui2-replay.json'
    receipt_path.write_text(json.dumps({'status': 'PASS', 'trace_sha256': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}, 'asset_sha256': traces[0]['asset_sha256'], 'requests': records, 'cleanup': True}, indent=2) + '\n')
