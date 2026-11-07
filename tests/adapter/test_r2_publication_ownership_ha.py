"""Additional R2 queue, failure-isolation and bounded-lifetime controls.

Real refreshjwt parser and production credential expression, synthetic I/O only.
The separate immutable reviewer matrix is intentionally not edited here.
"""
import asyncio
import gc
import json
from unittest.mock import Mock

import pytest
from custom_components.loxone.pyloxone_api import audioserver as wire
from custom_components.loxone.pyloxone_api.connection import LoxoneConnection
from custom_components.loxone.pyloxone_api.message import TextMessage
from test_audioserver_ha import audio_setup
from test_audioserver_playback import SyntheticAudioSocket, rsa_key
from test_audio_modes_ha import FULL, mode_harness, request
from test_review_races_ha import eventually
from test_stage2_modes_ha import output


async def producer(hass, audio_setup, monkeypatch, rsa_key):
    h = await mode_harness(hass, audio_setup, monkeypatch, rsa_key, source='library')
    co = hass.data['loxone'][h.entry.entry_id]
    publications = []

    def changed(token):
        assert api.get_token_dict()['token'] == token['token']
        publications.append(True)
        co._on_token_changed(token)

    api = LoxoneConnection('synthetic.invalid', 'synthetic-user', 'synthetic-password',
        token={'token': 'synthetic-active-token', 'valid_until': 9999999999, 'hash_alg': 'SHA256'},
        token_change_callback=changed)
    monkeypatch.setattr(co.api, 'get_token_dict', api.get_token_dict)
    h.commands._credentials = lambda: (h.entry.options.get('username', ''), co.api.get_token_dict().get('token', ''))

    async def publish(token):
        await api._websocket_event(TextMessage(json.dumps({'LL': {
            'control': 'jdev/sys/refreshjwt/synthetic', 'Code': 200,
            'value': {'token': token, 'validUntil': 9999999999}}})))
        assert api.get_token_dict()['token'] == token

    return h, co, publish, publications


@pytest.mark.parametrize('history', ['stable', 'identical', 'ABA'])
@pytest.mark.parametrize('persistence_fails', [False, True])
async def test_r2_publication_while_queued_before_shared_lock(
    hass, audio_setup, monkeypatch, rsa_key, caplog, history, persistence_fails,
):
    h, co, publish, publications = await producer(hass, audio_setup, monkeypatch, rsa_key)
    sparse = {k: v for k, v in h.rows[7].items() if k not in {'pbr', 'plshuffle', 'plrepeat'}}
    sparse.update(audiopath='library:local:track:r2-queue', time=1)
    reads, peers = [], []
    normal_connect = wire.connect

    class Peer(SyntheticAudioSocket):
        async def send(self, message):
            if message == 'audio/7/status':
                self.sent.append(message)
                reads.append(message)
                self.queue.put_nowait(json.dumps({'status_result': [
                    {**sparse, 'pbr': FULL, 'plshuffle': True, 'plrepeat': 3}]}))
            else:
                await super().send(message)

    def connect(*args, **kwargs):
        peer = Peer(rsa_key)
        peers.append(peer)
        return peer

    monkeypatch.setattr(wire, 'connect', connect)
    await h.commands._lock.acquire()
    try:
        await h.emit(sparse)
        assert await eventually(lambda: bool(h.metadata._recoveries))
        # No group membership mutation or intervening metadata observation.
        with monkeypatch.context() as patch:
            patch.setattr(co, 'audio_grouping', None)
            if persistence_fails:
                def failed(*args, **kwargs):
                    raise RuntimeError('synthetic-private-exception-do-not-log')
                patch.setattr(hass.config_entries, 'async_update_entry', failed)
            if history == 'identical':
                await publish('synthetic-active-token')
            elif history == 'ABA':
                await publish('synthetic-replacement-token')
                await publish('synthetic-active-token')
        assert not reads and not peers
    finally:
        h.commands._lock.release()
    assert await eventually(lambda: not h.metadata._recoveries)
    await hass.async_block_till_done()
    revoked = history == 'ABA'
    assert len(reads) == (0 if revoked else 1)
    assert (h.entities[7].shuffle is None) == revoked
    assert all(peer.closed for peer in peers) and not h.writes
    assert 'synthetic-private-exception-do-not-log' not in caplog.text
    gc.collect()
    assert len(h.commands._authentication_guards) == 0
    # A new deliberate native read captures current authority and is not disabled.
    fresh = await h.commands.async_player_status(7, is_current=lambda: True)
    assert fresh.shuffle is True and fresh.repeat == 3
    monkeypatch.setattr(wire, 'connect', normal_connect)
    await h.emit({**sparse, 'pbr': FULL, 'plshuffle': False, 'plrepeat': 0})
    await request(hass, h, 7, 'repeat', 'one')
    assert h.writes == ['audio/7/repeat/3']
    output(f'r2-queue-{history}-{persistence_fails}.json', {
        'history': history, 'persistence_fails': persistence_fails,
        'producer_order_checked': publications, 'pre_new_operation_reads': 0 if revoked else 1,
        'new_deliberate_read_passed': True, 'fresh_registered_write': h.writes,
        'all_peers_closed': all(peer.closed for peer in peers), 'observers_remaining': 0})


@pytest.mark.parametrize('boundary', ['cancel', 'unload'])
async def test_r2_queued_lifetime_observer_removed_on_cancellation(
    hass, audio_setup, monkeypatch, rsa_key, boundary,
):
    h, co, publish, publications = await producer(hass, audio_setup, monkeypatch, rsa_key)
    sparse = {k: v for k, v in h.rows[7].items() if k not in {'pbr', 'plshuffle', 'plrepeat'}}
    sparse.update(audiopath='library:local:track:r2-cancel', time=1)
    await h.commands._lock.acquire()
    try:
        await h.emit(sparse)
        assert await eventually(lambda: bool(h.metadata._recoveries))
        assert len(h.commands._authentication_guards) == 1
        if boundary == 'unload':
            assert await hass.config_entries.async_unload(h.entry.entry_id)
        else:
            h.metadata.set_playing(7, False)
            assert await eventually(lambda: not h.metadata._recoveries)
        await publish('synthetic-replacement-token')
        await publish('synthetic-active-token')
    finally:
        h.commands._lock.release()
    await hass.async_block_till_done()
    gc.collect()
    assert not h.metadata._recoveries and not h.metadata._mode_recovery
    assert len(h.commands._authentication_guards) == 0
    assert not h.writes and all(peer.closed for peer in h.sockets)


@pytest.mark.parametrize('failed_observer', ['grouping', 'commands'])
async def test_r2_observation_failure_isolated_from_other_observer_and_persistence(
    hass, audio_setup, monkeypatch, rsa_key, caplog, failed_observer,
):
    h, co, publish, publications = await producer(hass, audio_setup, monkeypatch, rsa_key)
    guard = h.commands.authentication_guard()
    group = Mock()
    with monkeypatch.context() as patch:
        patch.setattr(co, 'audio_grouping', group)
        def failed():
            raise RuntimeError('synthetic-private-observer-do-not-log')
        if failed_observer == 'grouping':
            group.native.observe_current.side_effect = failed
        else:
            patch.setattr(h.commands, 'observe_authentication', failed)
        await publish('synthetic-replacement-token')
        if failed_observer == 'grouping':
            await publish('synthetic-active-token')
            assert not guard()
        else:
            group.native.observe_current.assert_called_once_with()
            assert not guard()
    assert h.entry.data['token'] == ('synthetic-active-token' if failed_observer == 'grouping' else 'synthetic-replacement-token')
    assert 'synthetic-private-observer-do-not-log' not in caplog.text
    assert not h.writes
