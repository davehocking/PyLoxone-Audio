"""Warm owning-source guards, distinct from explicit legacy cold-auth probes."""
import asyncio

import pytest
from test_audioserver_ha import audio_setup
from test_audioserver_playback import rsa_key
from test_seek_readiness_ha import readiness_harness, select
from session_fixture_policy import close_retained_peer


@pytest.mark.parametrize('spotify', [False, True], ids=['library', 'spotify'])
@pytest.mark.parametrize('change', ['stable', 'track', 'account', 'source', 'stop', 'event', 'capability-held', 'capability-recovered', 'announcement', 'credentials'])
async def test_warm_source_seek_rechecks_authority_after_real_lock_wait(
    hass, audio_setup, monkeypatch, rsa_key, spotify, change,
):
    h = await readiness_harness(hass, audio_setup, monkeypatch, rsa_key, spotify=spotify)
    tokens = ['synthetic-active-token']
    monkeypatch.setattr(h.commands, '_credentials', lambda: ('synthetic-user', tokens[0]))
    pending = asyncio.create_task(select(hass, h))
    locked = False
    try:
        await asyncio.wait_for(h.started.wait(), 1)
        async with asyncio.timeout(1):
            while h.commands._socket is not None:
                await asyncio.sleep(0)
        assert h.commands.reuse_session
        assert h.commands._session is not None and h.commands._session.valid()
        await h.commands._lock.acquire()
        locked = True
        await h.emit({**h.target, 'pbr': 32})
        async with asyncio.timeout(1):
            while not h.commands._lock._waiters:
                if pending.done():
                    raise AssertionError('Owning optional seek never reached its native lock')
                await asyncio.sleep(0)
        if change == 'announcement':
            h.commands.announcement_fences[7] = lambda: None
            await h.emit({**h.target, 'pbr': 32})
            h.commands.announcement_fences.pop(7)
        elif change == 'credentials':
            for token in ('synthetic-other-token', 'synthetic-active-token'):
                tokens[0] = token
                h.commands.observe_authentication()
        elif change != 'stable':
            fields = {
                'track': {'audiopath': h.target['audiopath'] + '-other'},
                'account': {'sourceName': 'Different synthetic owner'},
                'source': {'audiopath': 'tunein:station:other'},
                'stop': {'mode': 'stop'},
                'event': {'eventype': 3},
                'capability-held': {'pbr': 0},
                'capability-recovered': {'pbr': 0},
            }[change]
            await h.emit({**h.target, 'pbr': 32, **fields})
        if change not in ('stable', 'capability-held'):
            await h.emit({**h.target, 'pbr': 32})
        h.commands._lock.release()
        locked = False
        await asyncio.wait_for(pending, 1)
        # Existing readiness policy permits a still-current track's recovered
        # capability, unlike identity/intent/credential revocation. Keep a held
        # unsupported case beside that positive, without changing the policy.
        seeks = change in ('stable', 'capability-recovered')
        assert len(h.writes) == (2 if seeks else 1)
        if seeks:
            assert h.writes[-1] == 'audio/7/position/45.0'
        # One real handshake for the source and warm optional seek. Neither an
        # intervening conflict nor a restored identity may cause replay.
        assert len(h.sockets) == 1
        assert sum(m.startswith('secure/authenticate/') for s in h.sockets for m in s.sent) == 1
        assert h.shortcuts == []
        assert not h.commands.source_observations
        audio_setup.apis[0].send_websocket_command.assert_not_awaited()
    finally:
        if locked:
            h.commands._lock.release()
        h.commands.announcement_fences.pop(7, None)
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        await close_retained_peer(h.commands)
