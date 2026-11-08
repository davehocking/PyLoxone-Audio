"""Additional owning-service challenges; synthetic peer, no eligibility replacements."""
import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from homeassistant.exceptions import HomeAssistantError
from custom_components.loxone.pyloxone_api import audioserver as wire
from custom_components.loxone.pyloxone_api.connection import LoxoneConnection
from custom_components.loxone.pyloxone_api.message import TextMessage
from test_audio_grouping_ha import audio_setup, grouped_setup, row
from test_audioserver_playback import SyntheticAudioSocket, rsa_key
from test_precommand_parent_qualification_v2_ha import native_row, FIELDS


@pytest.fixture
async def preflight_peer(hass, grouped_setup, audio_setup, monkeypatch, rsa_key):
    g = grouped_setup
    entry, co, ids = await g.setup()
    await g.feed(entry, row('pair', (1, 2)), row('untouched', (5, 6)))
    callback = g.callbacks[entry.entry_id]['callback']
    await callback({**{f'play-{v}': 1 for v in ids}, **{f'volume-{v}': v * 10 for v in ids}})
    p = SimpleNamespace(g=g, entry=entry, co=co, ids=ids, sockets=[], routes=[], phases=[], observations=[],
                        hook=None, status=[native_row(2, 'parent-A')], raw_status=None,
                        after=[native_row(2, 'parent-A', mode='play', time=24.945)],
                        before_send=[], status_sent=asyncio.Event(), status_release=None,
                        group_reply='exact', status_baseline=None)

    api = LoxoneConnection('synthetic.invalid', 'synthetic-user', 'synthetic-password',
        token={'token': 'synthetic-active-token', 'valid_until': 9999999999, 'hash_alg': 'SHA256'},
        token_change_callback=co._on_token_changed)
    monkeypatch.setattr(co.api, 'get_token_dict', api.get_token_dict)
    co.audio_commands._credentials = lambda: ('synthetic-user', co.api.get_token_dict()['token'])

    async def publish(token):
        await api._websocket_event(TextMessage(json.dumps({'LL': {
            'control': 'jdev/sys/refreshjwt/synthetic', 'Code': 200,
            'value': {'token': token, 'validUntil': 9999999999}}})))
        assert api.get_token_dict()['token'] == token
        p.phases.append('published-token')
    p.publish = publish

    def identity(player):
        m = co.audio_metadata.get(player)
        return None if m is None else [getattr(m, f) for f in FIELDS]
    p.identity = identity

    async def emit(frame):
        v = frame['playerid']
        future = asyncio.get_running_loop().create_future()
        remove = co.audio_metadata.async_add_listener(v, lambda: future.done() or future.set_result(None))
        try:
            audio_setup.queues[0].put_nowait(json.dumps({'audio_event': [frame]}))
            await asyncio.wait_for(future, 2)
        finally:
            remove()
        p.observations.append({'frame': frame, 'identity': identity(v)})
    p.emit = emit
    for v in (1, 2):
        await emit(native_row(v, None if v == 2 else 'parent-A'))
    original = co.audio_grouping.native.snapshot

    async def stage(name):
        p.phases.append(name)
        if p.hook is not None:
            await p.hook(name)
    p.stage = stage

    class Socket(SyntheticAudioSocket):
        def __init__(self, index):
            super().__init__(rsa_key)
            self.index = index
            self.kind = 'status' if index == 0 else 'group'
        async def send(self, message):
            if message.startswith('audio/') and message != 'audio/cfg/getkey/full':
                self.sent.append(message)
                p.routes.append(message)
                if message.endswith('/status'):
                    self.kind = 'status'
                    await stage('status-send')
                    p.status_sent.set()
                    if p.status_release is not None:
                        await p.status_release.wait()
                    if p.raw_status is not None:
                        self.queue.put_nowait(p.raw_status)
                    else:
                        self.queue.put_nowait(json.dumps({'status_result': p.status}))
                    return
                self.kind = 'group'
                assert message == 'audio/grouped/play/1,2', message
                p.before_send.append(identity(2))
                await stage('group-send')
                for frame in p.after:
                    await emit(frame)
                value = True if p.group_reply == 'boolean' else {'players': [
                    {'playerid': v, 'mode': 'play'} for v in ((1,) if p.group_reply == 'partial' else (1, 2))]}
                reply = {'grouped_play_result': value}
                if p.group_reply == 'error':
                    reply['error'] = 'synthetic rejection'
                self.queue.put_nowait(json.dumps(reply))
                return
            await super().send(message)
            if message.startswith('secure/authenticate/'):
                await stage(self.kind + '-auth')
        async def __aexit__(self, *args):
            await stage(self.kind + '-cleanup')
            await super().__aexit__(*args)
    def connect(*args, **kwargs):
        socket = Socket(len(p.sockets))
        p.sockets.append(socket)
        return socket
    monkeypatch.setattr(wire, 'connect', connect)

    async def call(label):
        result = 'success'
        try:
            await hass.services.async_call('media_player', 'media_play', {}, target={'entity_id': ids[1]}, blocking=True)
        except HomeAssistantError:
            result = 'HomeAssistantError'
        except asyncio.CancelledError:
            result = 'CancelledError'
        await hass.async_block_till_done()
        n = co.audio_grouping.native
        p.receipt = {'label': label, 'result': result, 'routes': list(p.routes), 'phases': list(p.phases),
            'observations': list(p.observations), 'before_send': list(p.before_send),
            'all_sockets_closed': all(s.closed for s in p.sockets),
            'membership_equal': n.snapshot is not None and n.snapshot.groups == original.groups,
            'status': p.status, 'raw_status': p.raw_status,
            'pending_requests': len(n._requests), 'pending_tasks': len(n._tasks),
            'scope': sorted(n._scope), 'acoustic_success': 'UNVERIFIED'}
        out = Path(os.environ['STAGE2_EVIDENCE_ROOT'])
        out.mkdir(parents=True, exist_ok=True)
        (out / (label + '.json')).write_text(json.dumps(p.receipt, indent=2) + '\n')
        assert p.receipt['all_sockets_closed'] and co.audio_commands._socket is None
        assert not n._scope and not n._requests and not n._tasks and not n._lock.locked()
        assert all(not e._transport_tasks for e in g.entities.values())
        co.api.send_websocket_command.assert_not_awaited()
        return result
    p.call = call
    try:
        yield p
    finally:
        if p.status_release is not None:
            p.status_release.set()


async def test_ordinary_parentless_valid_status_must_remain_playable(preflight_peer):
    p = preflight_peer
    p.status = [native_row(2, None)]
    p.after = [native_row(2, None, mode='play', time=24.945)]
    result = await p.call('ordinary-parentless')
    assert result == 'success', p.receipt
    assert [r for r in p.routes if not r.endswith('/status')] == ['audio/grouped/play/1,2']
    assert len([r for r in p.routes if r.endswith('/status')]) <= 1


async def test_duplicate_status_fields_do_not_qualify(preflight_peer):
    p = preflight_peer
    good = json.dumps(p.status)
    # A native status envelope with two contradictory values is ambiguous.
    p.raw_status = '{"status_result":false,"status_result":' + good + '}'
    assert await p.call('duplicate-status') == 'HomeAssistantError', p.receipt
    assert all(r.endswith('/status') for r in p.routes), p.receipt
