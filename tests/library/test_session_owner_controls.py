"""Cross-owner, idle-boundary and cancellation controls for real sessions."""
import asyncio
import pytest
from pyloxone_audio import native, session
from session_support import Clock, Peer, Socket, settle


async def test_separate_entries_and_servers_never_share_or_close_each_other(monkeypatch):
    peer = Peer()
    monkeypatch.setattr(native, 'connect', peer.connect)
    owners = [native.AudioServerCommands(host, lambda: ('u', 't')) for host in
              ('first.invalid', 'first.invalid', 'second.invalid')]
    for owner in owners:
        owner.reuse_session = True
    try:
        await asyncio.gather(*(o.async_execute(7, 'pause') for o in owners))
        assert peer.auths == 3
        assert len({id(o._session) for o in owners}) == 3
        await owners[0].async_close()
        await asyncio.gather(*(o.async_execute(7, 'play') for o in owners[1:]))
        assert peer.auths == 3
        assert peer.closes == 1
        assert peer.sends.count('audio/7/play') == 2
    finally:
        await asyncio.gather(*(o.async_close() for o in owners))
        await peer.finish()
    assert peer.closes == 3
    assert all(o._session is None for o in owners)


async def test_playback_resumes_at_idle_boundary_and_old_timer_cannot_close_it(monkeypatch):
    clock, peer = Clock(), Peer()
    monkeypatch.setattr(session, 'monotonic', clock.time)
    monkeypatch.setattr(session, 'call_later', clock.call_later)
    monkeypatch.setattr(native, 'connect', peer.connect)
    owner = native.AudioServerCommands('synthetic.invalid', lambda: ('u', 't'))
    owner.reuse_session = True
    try:
        await owner.async_execute(7, 'pause')
        expired_callback = clock.timers[-1][2]
        await clock.advance(299)
        owner.observe_playback(7, True)
        await clock.advance(1)
        expired_callback()  # queued obsolete callback must re-evaluate authority
        await settle()
        assert peer.closes == 0
        await owner.async_execute(7, 'pause')
        await clock.advance(299)
        assert peer.closes == 0
        await clock.advance(30)
        assert peer.closes == 1
    finally:
        await owner.async_close()
        await peer.finish()


@pytest.mark.parametrize('point', ['idle', 'active'])
async def test_unload_closes_exact_session_reader_and_timers(monkeypatch, point):
    peer = Peer()
    monkeypatch.setattr(native, 'connect', peer.connect)
    owner = native.AudioServerCommands('synthetic.invalid', lambda: ('u', 't'), timeout=.3)
    owner.reuse_session = True
    task = None
    try:
        await owner.async_execute(7, 'pause')
        saved = owner._session
        if point == 'active':
            peer.response = lambda _: None
            task = asyncio.create_task(owner.async_execute(7, 'play'))
            for _ in range(50):
                if len(peer.sends) == 2:
                    break
                await asyncio.sleep(0)
            assert peer.sends[-1] == 'audio/7/play'
        await owner.async_close()
        if task:
            with pytest.raises(native.AudioCommandError):
                await task
        assert saved.reader.done()
        assert saved._idle_timer is None
        assert saved._close_task.done()
        assert peer.closes == 1
        with pytest.raises(native.AudioCommandError):
            await owner.async_execute(7, 'play')
        assert peer.auths == 1
    finally:
        if task and not task.done():
            task.cancel()
        if task:
            await asyncio.gather(task, return_exceptions=True)
        await owner.async_close()
        await peer.finish()


async def test_idle_expiry_cannot_close_an_inflight_authentication(monkeypatch):
    clock, peer = Clock(), Peer()
    monkeypatch.setattr(session, 'monotonic', clock.time)
    monkeypatch.setattr(session, 'call_later', clock.call_later)
    monkeypatch.setattr(native, 'connect', peer.connect)
    entered, release = asyncio.Event(), asyncio.Event()
    original = Socket.send
    async def held_auth(socket, command):
        if command.startswith('secure/authenticate/'):
            entered.set()
            await release.wait()
        await original(socket, command)
    monkeypatch.setattr(Socket, 'send', held_auth)
    owner = native.AudioServerCommands('synthetic.invalid', lambda: ('u', 't'))
    owner.reuse_session = True
    task = asyncio.create_task(owner.async_execute(7, 'pause'))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        await clock.advance(301)
        assert peer.closes == 0
        release.set()
        await task
        assert peer.sends == ['audio/7/pause']
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await owner.async_close()
        await peer.finish()
