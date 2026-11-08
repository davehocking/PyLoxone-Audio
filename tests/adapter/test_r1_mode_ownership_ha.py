"""R1 obligation ownership through actual owning HA, receiver and auth peer.

All identities/credentials are invented. No revision/cache writes, shortened
production constants, patched mode predicates, or household connections.
"""
import asyncio
import hashlib
import json
from pathlib import Path
import time

import pytest
from homeassistant.components.media_player import MediaPlayerEntityFeature
from custom_components.loxone.const import EVENT
from custom_components.loxone.pyloxone_api import audioserver as wire
from test_audioserver_ha import audio_setup
from test_audioserver_playback import SyntheticAudioSocket, rsa_key
from test_audio_modes_ha import FULL, mode_harness, request
from test_stage2_modes_ha import output
from test_review_races_ha import eventually

BITS = MediaPlayerEntityFeature.SHUFFLE_SET | MediaPlayerEntityFeature.REPEAT_SET


async def held(hass, audio_setup, monkeypatch, rsa_key):
    h = await mode_harness(hass, audio_setup, monkeypatch, rsa_key, source='library')
    h.mode_connect = wire.connect
    entered, release = asyncio.Event(), asyncio.Event()
    sparse = {k: v for k, v in h.rows[7].items() if k not in {'pbr', 'plshuffle', 'plrepeat'}}
    sparse.update(audiopath='library:local:track:R1-B', time=1)
    peers, reads = [], []

    class Peer(SyntheticAudioSocket):
        async def send(self, message):
            if message == 'audio/7/status':
                self.sent.append(message)
                reads.append(time.monotonic())
                answer = {**sparse, 'pbr': FULL, 'plshuffle': True, 'plrepeat': 3}
                entered.set()
                await release.wait()
                self.queue.put_nowait(json.dumps({'status_result': [answer]}))
            else:
                await super().send(message)

    def connect(*_a, **_kw):
        peer = Peer(rsa_key)
        peers.append(peer)
        return peer

    monkeypatch.setattr(wire, 'connect', connect)
    await h.emit(sparse)
    assert await eventually(entered.is_set)
    assert 7 in h.metadata._requested_refresh and 7 in h.metadata._mode_recovery
    return h, sparse, release, peers, reads


@pytest.mark.parametrize('boundary', [
    'account', 'parent', 'source', 'denial', 'null', 'invalid', 'pause', 'event',
    'account-ABA', 'parent-ABA', 'source-ABA', 'frame-ABA',
    'auth', 'auth-ABA', 'intent', 'stop', 'unload', 'disconnect', 'binding',
])
async def test_r1_pending_obligation_revoked_not_revived_by_returning_context(
    hass, audio_setup, monkeypatch, rsa_key, boundary,
):
    h, sparse, release, peers, reads = await held(hass, audio_setup, monkeypatch, rsa_key)
    metadata = h.metadata
    original = metadata._mode_recovery[7]
    try:
        changes = {
            'account': {'sourceName': 'Different synthetic account'},
            'parent': {'parent': {'id': 'library:local:album:other'}},
            'source': {'audiopath': 'tunein:station:other'},
            'denial': {'pbr': 0}, 'null': {'plshuffle': None},
            'invalid': {'plrepeat': 2}, 'pause': {'mode': 'pause'}, 'event': {'eventype': 3},
        }
        if boundary in changes or boundary in {'account-ABA', 'parent-ABA', 'source-ABA'}:
            key = boundary.removesuffix('-ABA')
            await h.emit({**sparse, **changes[key]})
            if boundary.endswith('-ABA'):
                await h.emit({**sparse, 'time': 2})
        elif boundary == 'frame-ABA':
            # Both observations are in one native frame. The real receiver
            # applies its batch before notifying the coordinator.
            audio_setup.queues[0].put_nowait(json.dumps({'audio_event': [
                {**sparse, **changes['account']}, {**sparse, 'time': 2},
            ]}))
            assert await eventually(lambda: 7 not in metadata._mode_recovery)
        elif boundary.startswith('auth'):
            h.commands._credentials = lambda: ('synthetic-user', 'synthetic-other-token')
            await h.emit({**sparse, 'time': 2})
            if boundary.endswith('ABA'):
                h.commands._credentials = lambda: ('synthetic-user', 'synthetic-active-token')
                await h.emit({**sparse, 'time': 3})
        elif boundary == 'intent':
            await hass.services.async_call('media_player', 'media_stop',
                                          {'entity_id': h.entities[7].entity_id}, blocking=True)
            await h.emit({**sparse, 'time': 2})
        elif boundary == 'stop':
            hass.bus.async_fire(EVENT, {'play-7': 0})
            await hass.async_block_till_done()
            hass.bus.async_fire(EVENT, {'play-7': 2})
            await hass.async_block_till_done()
        elif boundary == 'unload':
            assert await hass.config_entries.async_unload(h.entry.entry_id)
        elif boundary == 'disconnect':
            audio_setup.queues[0].put_nowait(None)
            assert await eventually(lambda: 7 not in metadata._mode_recovery)
        elif boundary == 'binding':
            old = metadata._bindings[7]
            metadata.async_add_reconciler(7, old[0], intent=old[1], available=old[2])
        assert metadata._mode_recovery.get(7) is not original
        assert 7 not in metadata._mode_recovery and 7 not in metadata._requested_refresh
    finally:
        release.set()
    assert await eventually(lambda: not metadata._recoveries)
    await hass.async_block_till_done()
    assert len(reads) == 1 and all(p.closed for p in peers)
    assert h.entities[7].shuffle is not True
    assert not h.entities[7].supported_features & BITS
    assert not h.writes
    output('r1-revoke-' + boundary + '.json', {
        'boundary': boundary, 'reads': len(reads), 'pending': sorted(metadata._requested_refresh),
        'mode_obligations': sorted(metadata._mode_recovery), 'no_stale_modes': True,
        'closed': all(p.closed for p in peers), 'writes': h.writes,
    })


async def test_r1_unusable_status_retains_obligation_and_real_backoff_without_spin(
    hass, audio_setup, monkeypatch, rsa_key,
):
    h, sparse, release, peers, reads = await held(hass, audio_setup, monkeypatch, rsa_key)
    # A genuine current-player update supersedes the held authenticated reply.
    await h.emit({**sparse, 'time': 2})
    obligation = h.metadata._mode_recovery[7]
    release.set()
    assert await eventually(lambda: not h.metadata._recoveries)
    loop = asyncio.get_running_loop()
    retry = h.metadata._retry_at[7]
    assert 29 < retry - loop.time() <= 30
    assert h.metadata._retry_delay[7] == 60
    for index in range(16):
        await h.emit({**sparse, 'time': 3 + index})
        await asyncio.sleep(0)
        assert h.metadata._mode_recovery[7] is obligation
    assert h.metadata._retry_at[7] == retry
    assert len(reads) == 1 and all(p.closed for p in peers)
    assert h.entities[7].shuffle is None and not h.writes
    # Later authoritative ordinary feedback clears only the pending obligation.
    h.rows[7] = {**sparse, 'pbr': FULL, 'plshuffle': False, 'plrepeat': 0}
    await h.emit(h.rows[7])
    await hass.async_block_till_done()
    assert 7 not in h.metadata._mode_recovery and 7 not in h.metadata._requested_refresh
    assert h.entities[7].shuffle is False and h.entities[7].repeat == 'off'
    # An explicit new service remains usable despite background read backoff.
    monkeypatch.setattr(wire, 'connect', h.mode_connect)
    await request(hass, h, 7, 'repeat', 'one')
    assert h.writes == ['audio/7/repeat/3']
    assert h.entities[7].repeat == 'one'
    output('r1-backoff-no-spin.json', {'reads': len(reads), 'first_backoff_seconds': 30,
        'next_failure_delay': 60, 'sparse_observations': 16, 'retry_deadline_unchanged': True,
        'explicit_later_service': h.writes})


async def test_r1_latest_recovery_exports_actual_owning_ha_for_full_native_app(
    hass, audio_setup, monkeypatch, rsa_key,
):
    from test_review_races_ha import test_review_pending_sparse_status_preserves_liveness_without_stale_revival as oracle
    states = []

    def changed(event):
        state = event.data.get('new_state')
        if state is not None and state.entity_id == 'media_player.duplicate_zone_name_7':
            states.append({'entity_id': state.entity_id, 'state': state.state,
                           'attributes': dict(state.attributes)})

    remove = hass.bus.async_listen('state_changed', changed)
    try:
        # Exact immutable body: real authenticated held B, native C supersession,
        # unchanged 30-second backoff, eight real four-second sparse updates.
        await oracle(hass, audio_setup, monkeypatch, rsa_key, 'library', 'next-track')
        await hass.async_block_till_done()
    finally:
        remove()
    known = [s for s in states if s['attributes'].get('supported_features', 0) & int(BITS) == int(BITS)]
    unknown = [s for s in states if not s['attributes'].get('supported_features', 0) & int(BITS)]
    assert known and unknown and known[-1]['attributes']['shuffle'] is True
    assert known[-1]['attributes']['repeat'] == 'one'
    exports = [{**known[0], 'label': 'before'}, {**unknown[-1], 'label': 'missing-awaiting-status'},
               {**known[-1], 'label': 'fresh-status'}]
    output('r1-mode-exports.json', {'states': exports, 'all_owning_events': states,
                                  'source': 'actual HA StateMachine, unchanged immutable oracle'})


async def test_r1_current_f63_native_literals_reach_registered_services_and_wire(
    hass, audio_setup, monkeypatch, rsa_key,
):
    root = Path(__file__).resolve().parents[2]
    asset = root / 'adapters/pyloxone/frontend/dist/group-control-card-0.1.3.dev7-gm03-mobile-r2.js'
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    assert digest == 'f63a3a46cc619a8889b6b7620c7e31f89641aae2b7f25a02bac1729b18533437'
    historical = json.loads((root / 'tests/frontend/stage2-native-calls.json').read_text())
    assert historical['module_sha256'] == '911eed0c78f7bc13e013e51bddd42e14274bf8d892f18109a2c9d0f96c69660a'
    # Native Core's buttons, not the custom grouping module, emit these calls.
    trace = {**historical, 'module_sha256': digest}
    h = await mode_harness(hass, audio_setup, monkeypatch, rsa_key, source='library')
    await h.emit({**h.rows[7], 'plshuffle': True, 'plrepeat': 3})
    for call in trace['calls']:
        await hass.services.async_call(call['domain'], call['service'], call['data'],
                                       target=call['target'], blocking=True)
    await hass.async_block_till_done()
    assert h.writes == ['audio/7/shuffle/disable', 'audio/7/repeat/0']
    assert h.entities[7].shuffle is False and h.entities[7].repeat == 'off'
    assert all(p.closed for p in h.sockets)
    output('r1-current-native-literal-replay.json', {'trace': trace, 'historical_epoch': historical['module_sha256'],
        'current_asset_sha256': digest, 'native_writes': h.writes, 'registered_services': True,
        'authentication': 'synthetic RSA/AES peer', 'hardware_efficacy': 'UNVERIFIED'})
