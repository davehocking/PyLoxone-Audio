"""Transport failure revokes old work without fabricating membership authority."""
import asyncio
import pytest
from pyloxone_audio.native import AudioCommandError
from test_group_coordinator import owner
from test_audio_grouping import payload, row


@pytest.mark.parametrize('queued', ['mutation', 'volume', 'group', 'room'])
async def test_failed_transport_revokes_queue_not_fresh_requests(queued):
    c, s, _, _ = owner(timeout=.5)
    c.observe(payload(row('pair', (1, 2))))
    sent, release = asyncio.Event(), asyncio.Event()
    writes, calls = [], []
    async def execute(*args, **kwargs):
        assert kwargs['is_current']()
        kwargs['on_send']()
        calls.append(args)
        sent.set()
        await release.wait()
        raise AudioCommandError('synthetic rejected')
    s.async_execute = s.async_group_transport = execute
    reserve = lambda players: (lambda: True, lambda: None)
    def request():
        if queued == 'mutation': return c.async_join(1, (3,))
        if queued == 'volume': return c.async_volume(1, 40, {1: 10, 2: 20}.get, lambda *args: writes.append(args))
        if queued == 'group': return c.async_transport(1, 'play', reserve)
        return c.async_room_transport(3, 'pause', reserve)
    active = asyncio.create_task(c.async_transport(1, 'play', reserve))
    pending = None
    try:
        await sent.wait()
        pending = asyncio.create_task(request())
        await asyncio.sleep(0)
        assert len(c._tasks) == 2
        release.set()
        results = await asyncio.gather(active, pending, return_exceptions=True)
        assert all(isinstance(v, AudioCommandError) for v in results)
        assert calls == [((1, 2), 'play')] and not writes and not s.calls
        assert not c.uncertain and not c._tasks and not c._requests and not c._scope
        await c.async_join(1, (3,))
        assert s.calls == [('pair', (1, 2, 3))]
    finally:
        for t in (active, pending):
            if t: t.cancel()
        await asyncio.gather(*(t for t in (active, pending) if t), return_exceptions=True)
        await c.async_close()


@pytest.mark.parametrize('boundary', ['context-ABA', 'eligibility-ABA', 'membership-ABA', 'invalid', 'invalidate', 'preexisting-uncertain'])
async def test_transport_failure_never_clears_genuine_revocation(boundary):
    c, s, eligible, context = owner(timeout=.1)
    c.observe(payload(row('pair', (1, 2))))
    calls = []
    async def execute(*args, **kw):
        kw['on_send'](); calls.append(args)
        if boundary == 'context-ABA':
            for v in ('changed', 'session-a'): context[0] = v; c.observe_current()
        elif boundary == 'eligibility-ABA':
            eligible.remove(2); c.observe_current(); eligible.add(2); c.observe_current()
        elif boundary == 'membership-ABA':
            c.observe(payload(row('pair', (1, 3)))); c.observe(payload(row('pair', (1, 2))))
        elif boundary == 'invalid': c.observe('{}')
        elif boundary == 'invalidate': c.invalidate()
        else: c.uncertain = True  # synthetic already-unknown authority; never cleared
        raise AudioCommandError('synthetic rejected')
    s.async_group_transport = execute
    try:
        with pytest.raises(AudioCommandError):
            await c.async_transport(1, 'play', lambda players: (lambda: True, lambda: None))
        assert calls == [((1, 2), 'play')]
        assert not c._requests and not c._tasks and not c._scope
        if boundary in ('invalid', 'invalidate', 'preexisting-uncertain'):
            with pytest.raises(AudioCommandError): await c.async_unjoin(1)
            assert not s.calls
        else:
            await c.async_join(1, (3,))
            assert s.calls == [('pair', (1, 2, 3))]
    finally: await c.async_close()
