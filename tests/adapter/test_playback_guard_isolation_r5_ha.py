"""Stage B: unchanged guards at registered media_play + real synthetic authentication.

Characterisation, NOT firmware causation or an authorised backend correction.
No replacement eligibility algorithm: wrappers observe and return actual results.
"""
import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest
from homeassistant.exceptions import HomeAssistantError
from custom_components.loxone.pyloxone_api import audioserver as wire
from pyloxone_audio.native import AudioCommandError
from pyloxone_audio.diagnostic_events import DiagnosticEmitter
from test_audio_grouping_ha import audio_setup, grouped_setup, STATE, row, payload
from test_audioserver_playback import SyntheticAudioSocket, rsa_key

# Expected CURRENT behaviour, deliberately not desired new policy.
CASES = [
    ('stable', 'send', 'exact', True),
    ('progress', 'send', 'exact', True),
    ('title', 'send', 'exact', True),
    ('pbr-omitted', 'send', 'exact', True),
    ('no-metadata-stable', 'send', 'exact', True),
    ('parent-enrichment', 'send', 'exact', False),
    ('content', 'send', 'exact', False),
    ('content-parent', 'send', 'exact', False),
    ('parent-replacement', 'send', 'exact', False),
    ('parent-ABA', 'send', 'exact', False),
    ('sparse-mode-only', 'send', 'exact', False),
    ('sparse-account-omitted', 'send', 'exact', False),
    ('known-parent-omitted', 'send', 'exact', False),
    ('metadata-arrives', 'send', 'exact', False),
    ('account', 'send', 'exact', False),
    ('source', 'send', 'exact', False),
    ('active-event', 'send', 'exact', False),
    ('topology-ABA', 'send', 'exact', False),
    ('auth-ABA', 'send', 'exact', False),
    ('lifecycle-ABA', 'send', 'exact', False),
    ('parent-enrichment', 'auth', 'exact', False),
    ('parent-enrichment', 'cleanup', 'exact', False),
    ('stable', 'send', 'boolean', False),
    ('stable', 'send', 'extra', False),
    ('stable', 'send', 'missing', False),
    ('stable', 'send', 'duplicate', False),
    ('stable', 'send', 'wrong-mode', False),
    ('stable', 'send', 'error', False),
    ('stable', 'send', 'reversed', True),
]


def case_id(case):
    return '/'.join(map(str, case[:3]))


@pytest.mark.parametrize('change,when,reply_kind,expected_success', CASES, ids=[case_id(c) for c in CASES])
async def test_current_playback_guard_matrix(hass, grouped_setup, audio_setup, monkeypatch, rsa_key, change, when, reply_kind, expected_success):
    g = grouped_setup
    entry, co, ids = await g.setup()
    groups = [row('native', (1, 2, 3)), row('untouched', (5, 6))]
    await g.feed(entry, *groups)
    callback = g.callbacks[entry.entry_id]['callback']
    await callback({**{f'play-{p}': 1 for p in ids}, **{f'volume-{p}': p * 10 for p in ids}})
    co.api.get_token_dict = lambda: {'token': 'synthetic-active-token', 'valid_until': 9999999999}
    co.audio_commands._credentials = lambda: ('synthetic-user', 'synthetic-active-token')
    original_snapshot = co.audio_grouping.native.snapshot
    baseline = {}
    stages, identities, guards, errors, sockets, routes = [], [], [], [], [], []
    diagnostic_events = []
    status_routes, request_route = [], [None]
    emitter = DiagnosticEmitter(b'synthetic-stage-b-offline-only', diagnostic_events.append)
    emitter.enabled = True
    co.audio_commands.diagnostics = emitter

    def identity(player):
        m = co.audio_metadata.get(player)
        return None if m is None else {f: getattr(m, f) for f in ('source', 'source_name', 'audio_path', 'parent_id', 'native_mode', 'position', 'event_active')}

    async def emit(player, sparse=False, omit=(), **fields):
        delivered = asyncio.get_running_loop().create_future()
        remove = co.audio_metadata.async_add_listener(player, lambda: delivered.done() or delivered.set_result(None))
        base = {} if sparse else {'mode': 'pause', 'eventype': 0, 'audiopath': f'library:local:track:existing-{player}', 'sourceName': 'Synthetic retained account', 'time': 20, 'duration': 600, 'pbr': 63, 'parent': {'id': 'parent-A'}}
        if change in ('parent-enrichment', 'content-parent'):
            base.pop('parent', None)
        for key in omit:
            base.pop(key, None)
        try:
            audio_setup.queues[0].put_nowait(json.dumps({'audio_event': [{'playerid': player, **base, **fields}]}))
            await asyncio.wait_for(delivered, 1)
        finally:
            remove()
        identities.append({'stage': stages[-1] if stages else 'initial', 'player': player, 'identity': identity(player)})

    if change not in ('metadata-arrives', 'no-metadata-stable'):
        for player in (1, 2, 3):
            await emit(player)
    baseline = {p: identity(p) for p in (1, 2, 3)}

    async def perturb():
        stages.append('perturb-' + when)
        if change in ('stable', 'no-metadata-stable'):
            return
        if change == 'topology-ABA':
            await g.feed(entry, row('native', (1, 2, 4)), row('untouched', (5, 6)))
            await g.feed(entry, *groups)
            return
        if change == 'auth-ABA':
            for token in ('synthetic-other-token', 'synthetic-active-token'):
                co.api.get_token_dict = lambda token=token: {'token': token, 'valid_until': 9999999999}
                co.audio_grouping.native.observe_current()
            return
        if change == 'lifecycle-ABA':
            for removed in (True, False):
                g.entities[ids[2]]._audio_removed = removed
                co.audio_grouping.native.observe_current()
            return
        updates = {
            'progress': {'mode': 'play', 'time': 24.945},
            'title': {'mode': 'play', 'time': 24.945, 'title': 'Synthetic changed title'},
            'pbr-omitted': {'mode': 'play', 'time': 24.945},
            'parent-enrichment': {'mode': 'play', 'parent': {'id': 'parent-A'}, 'time': 24.945},
            'content': {'mode': 'play', 'audiopath': 'library:local:track:replacement'},
            'content-parent': {'mode': 'play', 'audiopath': 'library:local:track:replacement', 'parent': {'id': 'parent-A'}},
            'parent-replacement': {'mode': 'play', 'parent': {'id': 'parent-B'}},
            'parent-ABA': {'mode': 'play', 'parent': {'id': 'parent-B'}},
            'sparse-mode-only': {'mode': 'play'},
            'sparse-account-omitted': {'mode': 'play', 'eventype': 0, 'audiopath': 'library:local:track:existing-2', 'parent': {'id': 'parent-A'}},
            'known-parent-omitted': {'mode': 'play', 'parent': None},
            'metadata-arrives': {'mode': 'play'},
            'account': {'mode': 'play', 'sourceName': 'Synthetic replacement account'},
            'source': {'mode': 'play', 'audiopath': 'tunein:station:replacement'},
            'active-event': {'mode': 'play', 'eventype': 1, 'eventstate': 'active'},
        }
        await emit(2, sparse=change.startswith('sparse-'), omit=('pbr',) if change == 'pbr-omitted' else (), **updates[change])
        if change == 'parent-ABA':
            await emit(2, mode='play', parent={'id': 'parent-A'})
        await callback({'play-1': 2, 'play-2': 2, 'play-3': 2})

    # Observe the real shared applicability, preserving the actual return/raise.
    request = co.audio_commands._async_request
    async def observe_request(command, reply_key, **kwargs):
        request_route[0] = command
        if command.startswith('audio/grouped/'):
            original = kwargs['is_current']
            def current():
                value = original()
                guards.append({'stage': stages[-1], 'value': value, 'identity': identity(2)})
                return value
            kwargs['is_current'] = current
        try:
            result = await request(command, reply_key, **kwargs)
            if command.startswith('audio/grouped/'):
                stages.append('request-returned')
            return result
        except AudioCommandError as exc:
            errors.append({'layer': '_async_request', 'message': str(exc)})
            raise
    monkeypatch.setattr(co.audio_commands, '_async_request', observe_request)
    transport = co.audio_commands.async_group_transport
    async def observe_transport(*args, **kwargs):
        try:
            return await transport(*args, **kwargs)
        except AudioCommandError as exc:
            errors.append({'layer': 'async_group_transport', 'message': str(exc)})
            raise
    monkeypatch.setattr(co.audio_commands, 'async_group_transport', observe_transport)

    class Socket(SyntheticAudioSocket):
        async def send(self, message):
            if message.startswith('audio/') and message.endswith('/status'):
                self.sent.append(message)
                status_routes.append(message)
                player = int(message.split('/')[1])
                m = co.audio_metadata.get(player)
                assert m is not None
                native = {'playerid': player, 'mode': m.native_mode, 'eventype': 0,
                          'audiopath': m.audio_path, 'sourceName': m.source_name}
                if m.parent_id is not None:
                    native['parent'] = {'id': m.parent_id}
                self.queue.put_nowait(json.dumps({'status_result': [native]}))
                return
            if message.startswith('audio/grouped/'):
                self.sent.append(message)
                routes.append(message)
                stages.append('send-entered')
                if when == 'send':
                    await perturb()
                players = (3, 2, 1) if reply_kind == 'reversed' else (1, 2) if reply_kind == 'missing' else (1, 1, 3) if reply_kind == 'duplicate' else (1, 2, 3)
                value: Any = True if reply_kind == 'boolean' else {'players': [{'playerid': p, 'mode': 'pause' if reply_kind == 'wrong-mode' else 'play'} for p in players]}
                if reply_kind == 'extra':
                    value['extra'] = 'synthetic'
                response: dict[str, Any] = {'grouped_play_result': value}
                if reply_kind == 'error':
                    response['error'] = 'synthetic refusal'
                self.queue.put_nowait(json.dumps(response))
                stages.append('reply-enqueued')
                return
            await super().send(message)
            if message.startswith('secure/authenticate/'):
                stages.append('authenticated-envelope-sent')
                if when == 'auth' and self.request_route.startswith('audio/grouped/'):
                    await perturb()
        async def __aexit__(self, *args):
            stages.append('cleanup-entered')
            if when == 'cleanup' and self.request_route.startswith('audio/grouped/'):
                await perturb()
            await super().__aexit__(*args)
            stages.append('cleanup-complete')
    def connect(*args, **kwargs):
        s = Socket(rsa_key)
        s.request_route = request_route[0]
        sockets.append(s)
        return s
    monkeypatch.setattr(wire, 'connect', connect)
    stages.append('registered-service-call')
    outcome = 'success'
    try:
        await hass.services.async_call('media_player', 'media_play', {}, target={'entity_id': ids[1]}, blocking=True)
    except HomeAssistantError as exc:
        outcome = type(exc).__name__
    await hass.async_block_till_done()
    native = co.audio_grouping.native
    receipt = {'case': [change, when, reply_kind], 'expected_current_success': expected_success, 'outcome': outcome, 'stages': stages, 'diagnostic_events': diagnostic_events, 'actual_guard_results': guards, 'errors': errors, 'baseline_metadata': baseline, 'metadata_observations': identities, 'final_metadata': {p: identity(p) for p in (1, 2, 3)}, 'routes': routes, 'status_routes': status_routes, 'authenticated_sockets': sum(any(m.startswith('secure/authenticate/') for m in s.sent) for s in sockets), 'all_sockets_closed': all(s.closed for s in sockets), 'snapshot_preserved': native.snapshot is original_snapshot, 'membership_unchanged': native.snapshot.groups == original_snapshot.groups, 'uncertain': native.uncertain, 'acoustic_success': 'UNVERIFIED'}
    dest = Path(os.environ['STAGE2_EVIDENCE_ROOT'])
    dest.mkdir(parents=True, exist_ok=True)
    (dest / ('guard-' + '-'.join((change, when, reply_kind)) + '.json')).write_text(json.dumps(receipt, indent=2) + '\n')
    assert outcome == ('success' if expected_success else 'HomeAssistantError'), receipt
    assert routes == ([] if when == 'auth' else ['audio/grouped/play/1,2,3'])
    assert len(sockets) == 1 + len(status_routes) and receipt['authenticated_sockets'] == len(sockets) and receipt['all_sockets_closed']
    assert len(status_routes) == len(set(status_routes)) and set(status_routes) <= {'audio/1/status', 'audio/2/status', 'audio/3/status'}
    assert not native._scope and not native._tasks and not native._requests and not native._lock.locked()
    assert co.audio_commands._socket is None
    assert all(not e._transport_tasks for e in g.entities.values())
    assert receipt['membership_unchanged'] and not native.uncertain
    all_stages = [event['stage'] for event in diagnostic_events]
    assert all_stages.count('request_finished') == all_stages.count('request')
    assert 'lock_acquired' in all_stages and 'connection_opened' in all_stages
    diagnostic_stages = [stage for stage in all_stages if stage not in {'lock_acquired', 'connection_opened', 'request_finished'}]
    if when != 'auth' and reply_kind != 'error':
        assert diagnostic_stages[:5] == ['request', 'authenticated', 'send_attempt', 'send_completed', 'reply']
    if reply_kind in ('boolean', 'extra', 'missing', 'duplicate', 'wrong-mode') or when == 'cleanup':
        # Real schema/cleanup rejection occurs outside _async_request's catch:
        # this native-only observer can report a reply before the owning HA rejection;
        # owning-operation outcomes are asserted separately in diagnostics-v2 tests.
        assert outcome == 'HomeAssistantError' and 'error' not in diagnostic_stages
    elif not expected_success:
        assert diagnostic_stages[-1] == 'error'
    assert emitter.sink_failures == 0
    co.api.send_websocket_command.assert_not_awaited()
