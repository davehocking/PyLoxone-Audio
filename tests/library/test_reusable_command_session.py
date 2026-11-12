"""Reuse acceptance at the actual authenticated native transport boundary."""
import asyncio
import pytest
from pyloxone_audio import native
from session_support import Peer, Clock, settle
from pyloxone_audio import session


async def test_clean_warm_requests_share_authentication(monkeypatch):
    peer = Peer()
    monkeypatch.setattr(native, 'connect', peer.connect)
    commands = native.AudioServerCommands('synthetic.invalid', lambda: ('synthetic-user', 'synthetic-token'))
    # Existing constructor/entrypoint is intentional: exact 0.1.5 ignores this
    # flag and fails the handshake-count assertion, not fixture setup/import.
    commands.reuse_session = True
    try:
        first = await commands.async_player_status(7, is_current=lambda: True)
        await commands.async_execute(7, 'pause')
        second = await commands.async_player_status(7, is_current=lambda: True)
        assert first == second or first.player_id == second.player_id == 7
        assert peer.sends == ['audio/7/status', 'audio/7/pause', 'audio/7/status']
        assert peer.opens == peer.auths == 1
        assert peer.closes == 0
    finally:
        await commands.async_close()
        await peer.finish()
    assert peer.closes == 1


@pytest.mark.parametrize('background', [False, True])
async def test_idle_expiry_is_active_and_polls_do_not_extend_it(monkeypatch, background):
    clock, peer = Clock(), Peer()
    monkeypatch.setattr(session, 'monotonic', clock.time, raising=False)
    monkeypatch.setattr(session, 'call_later', clock.call_later, raising=False)
    monkeypatch.setattr(native, 'connect', peer.connect)
    commands = native.AudioServerCommands('synthetic.invalid', lambda: ('u', 't'))
    commands.reuse_session = True
    try:
        await commands.async_player_status(7, is_current=lambda: True)
        await clock.advance(299)
        assert peer.closes == 0
        if background:
            await commands.async_player_status(7, is_current=lambda: True)
        await clock.advance(1)
        assert peer.closes == 1
        await commands.async_player_status(7, is_current=lambda: True)
        assert peer.opens == peer.auths == 2
    finally:
        await commands.async_close()
        await peer.finish()


async def test_meaningful_command_refreshes_five_minute_idle_allowance(monkeypatch):
    clock, peer = Clock(), Peer()
    monkeypatch.setattr(session, 'monotonic', clock.time, raising=False)
    monkeypatch.setattr(session, 'call_later', clock.call_later, raising=False)
    monkeypatch.setattr(native, 'connect', peer.connect)
    commands = native.AudioServerCommands('synthetic.invalid', lambda: ('u', 't'))
    commands.reuse_session = True
    try:
        await commands.async_player_status(7, is_current=lambda: True)
        await clock.advance(299)
        await commands.async_execute(7, 'pause')
        await clock.advance(299)
        assert peer.closes == 0
        await clock.advance(1)
        assert peer.closes == 1
    finally:
        await commands.async_close()
        await peer.finish()
