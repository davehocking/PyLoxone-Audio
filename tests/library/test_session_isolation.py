"""Lifecycle/reply-isolation controls through authenticated synthetic native I/O."""
import asyncio
import pytest
from pyloxone_audio import native, session
from pyloxone_audio.diagnostic_events import DiagnosticEmitter
from session_support import Peer, Clock, settle


@pytest.fixture
async def connected(monkeypatch):
    peer = Peer()
    token = ['A']
    monkeypatch.setattr(native, 'connect', peer.connect)
    commands = native.AudioServerCommands('synthetic.invalid', lambda: ('u', token[0]), timeout=.3)
    commands.reuse_session = True
    try:
        await commands.async_execute(7, 'pause')
        yield commands, peer, token
    finally:
        await commands.async_close()
        await peer.finish()


@pytest.mark.parametrize('aba', [False, True])
async def test_idle_auth_revocation_actively_retires_socket(connected, aba):
    commands, peer, token = connected
    token[0] = 'B'
    commands.observe_authentication()
    if aba:
        token[0] = 'A'
        commands.observe_authentication()
    await settle()
    assert peer.closes == 1
    await commands.async_execute(7, 'play')
    assert peer.auths == 2
    assert peer.sends == ['audio/7/pause', 'audio/7/play']


async def test_idle_receiver_failure_closes_without_a_later_command(connected):
    commands, peer, _ = connected
    peer.sockets[0].put(OSError('synthetic disconnect'))
    await settle()
    assert peer.closes == 1
    await commands.async_execute(7, 'play')
    assert peer.auths == 2


async def test_unsolicited_idle_frames_are_drained_with_one_receiver(connected):
    commands, peer, _ = connected
    for _ in range(1000):
        peer.sockets[0].put({'audio_event': [{'playerid': 999, 'mode': 'play'}]})
    for _ in range(100):
        await settle()
    assert peer.sockets[0].incoming.empty()
    await commands.async_execute(7, 'play')
    assert peer.auths == 1


@pytest.mark.parametrize('payload', [
    '{"command":"audio/7/play","play_result":true,"play_result":false}',
    '{"command":"audio/7/play","play_result":true,"play_result":true}',
    '{"command":"audio/7/play","play_result":true,"error":"","error":"no"}',
    {'command': 'audio/8/play', 'play_result': True},
    {'command': 'audio/7/play', 'play_result': False},
    {'command': 'audio/7/play', 'play_result': True, 'error': 'refused'},
])
async def test_rejected_ambiguous_wrong_player_never_replays(connected, payload):
    commands, peer, _ = connected
    peer.response = lambda _: payload
    with pytest.raises(native.AudioCommandError):
        await commands.async_execute(7, 'play', guard_cleanup=True)
    assert peer.sends == ['audio/7/pause', 'audio/7/play']


@pytest.mark.parametrize('failure', ['timeout', 'cancel', 'send_error', 'disconnect_after_send'])
async def test_uncertain_request_retires_before_late_reply_or_next_request(connected, failure):
    commands, peer, _ = connected
    entered, release = asyncio.Event(), asyncio.Event()
    old = peer.sockets[0]
    async def send(socket, command):
        entered.set()
        if failure == 'send_error':
            raise OSError('synthetic failed send')
        if failure == 'disconnect_after_send':
            socket.put(OSError('synthetic disconnect'))
        else:
            await release.wait()
    peer.on_send = send
    task = asyncio.create_task(commands.async_execute(7, 'play'))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        if failure == 'cancel':
            task.cancel()
        with pytest.raises(asyncio.CancelledError if failure == 'cancel' else native.AudioCommandError):
            await task
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert old.closed
    old.put({'command': 'audio/7/play', 'play_result': True})
    peer.on_send = None
    await commands.async_execute(7, 'play')
    assert peer.auths == 2
    assert peer.sends == ['audio/7/pause', 'audio/7/play', 'audio/7/play']


async def test_long_inflight_background_read_is_not_closed_at_idle_expiry(monkeypatch):
    clock, peer = Clock(), Peer()
    monkeypatch.setattr(session, 'monotonic', clock.time)
    monkeypatch.setattr(session, 'call_later', clock.call_later)
    monkeypatch.setattr(native, 'connect', peer.connect)
    commands = native.AudioServerCommands('synthetic.invalid', lambda: ('u', 't'))
    commands.reuse_session = True
    entered, release = asyncio.Event(), asyncio.Event()
    async def send(*_):
        entered.set()
        await release.wait()
    task = None
    try:
        await commands.async_player_status(7, is_current=lambda: True)
        await clock.advance(299)
        peer.on_send = send
        task = asyncio.create_task(commands.async_player_status(7, is_current=lambda: True))
        await asyncio.wait_for(entered.wait(), 1)
        await clock.advance(1000)
        assert peer.closes == 0
        release.set()
        await task
        await clock.advance(0)
        assert peer.closes == 1
    finally:
        release.set()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        await commands.async_close()
        await peer.finish()


async def test_warm_diagnostics_do_not_invent_new_open_or_authentication(connected):
    commands, peer, _ = connected
    rows = []
    commands.diagnostics = DiagnosticEmitter(b'synthetic', rows.append)
    commands.diagnostics.enabled = True
    await commands.async_execute(7, 'play')
    stages = [row['stage'] for row in rows]
    assert 'session_reused' in stages
    assert not {'authenticated', 'connection_opened'} & set(stages)
    assert stages[-1] == 'request_finished'
    assert rows[-1]['outcome'] == 'returned'
    assert peer.auths == 1
