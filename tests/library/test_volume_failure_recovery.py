"""Short, pure coordinator controls; decisive real8s owning oracle is separate."""
import asyncio
import pytest
from pyloxone_audio.grouping import mean_volume_percent
from pyloxone_audio.native import AudioCommandError
from test_group_coordinator import owner
from test_audio_grouping import payload, row


@pytest.mark.parametrize('players', [(1, 2), (4, 3)])
@pytest.mark.parametrize('failure', ['timeout', 'cancel', 'send-error', 'outside-volume', 'partial-confirmed'])
async def test_volume_failure_keeps_topology_and_confirmed_values_not_success(players, failure):
    c, sender, _, _ = owner(timeout=.06)
    c.observe(payload(row('pair', players)))
    snapshot = c.snapshot
    first, second = players
    levels = {first: 10, second: 38}
    writes = []
    sent = asyncio.Event()
    def send(p, v):
        writes.append((p, v)); sent.set()
        if failure == 'send-error':
            raise AudioCommandError('synthetic send failed')
        if failure == 'outside-volume':
            levels[second] = 50; c.observe_current()
        if failure == 'partial-confirmed' and p == first:
            levels[p] = v; c.observe_current()
    task = asyncio.create_task(c.async_volume(second, 7, levels.get, send))
    try:
        await sent.wait()
        if failure == 'cancel': task.cancel()
        result = (await asyncio.gather(task, return_exceptions=True))[0]
        assert isinstance(result, asyncio.CancelledError if failure == 'cancel' else AudioCommandError)
        assert writes == ([(first, 0), (second, 21)] if failure == 'partial-confirmed' else [(first, 0)])
        assert c.snapshot is snapshot and not c.uncertain
        assert levels[first] == (0 if failure == 'partial-confirmed' else 10)
        assert levels[second] == (50 if failure == 'outside-volume' else 38)
        assert not c._tasks and not c._requests and not c._scope and not c._lock.locked()
        # A later feedback updates actual state, never replays the remaining send.
        levels[first] = 0; c.observe_current(); await asyncio.sleep(0)
        assert len(writes) == (2 if failure == 'partial-confirmed' else 1)
        assert mean_volume_percent(list(levels.values())) == (25 if failure == 'outside-volume' else 19)
        def confirm(p, v):
            writes.append((p, v)); levels[p] = v; c.observe_current()
        await c.async_volume(second, 21, levels.get, confirm, room_only=True)
        assert writes[-1] == (second, 21)
        await c.async_unjoin(first)
        assert sender.calls == [('pair', ())]
    finally:
        await c.async_close()


@pytest.mark.parametrize('queued', ['volume', 'mutation', 'group-play', 'room-pause'])
async def test_failed_volume_revokes_captured_queue_not_future_deliberate_work(queued):
    c, sender, _, _ = owner(timeout=.5)
    c.observe(payload(row('pair', (1, 2))))
    levels = {1: 10, 2: 38, 3: 20}
    writes, transports = [], []
    sent = asyncio.Event()
    def send(p, v): writes.append((p, v)); sent.set()
    async def execute(*args, **kwargs):
        assert kwargs['is_current'](); kwargs['on_send'](); transports.append(args)
    sender.async_execute = sender.async_group_transport = execute
    def request():
        if queued == 'volume': return c.async_volume(2, 50, levels.get, send)
        if queued == 'mutation': return c.async_join(1, (3,))
        reserve = lambda players: (lambda: True, lambda: None)
        if queued == 'group-play': return c.async_transport(1, 'play', reserve)
        return c.async_room_transport(2, 'pause', reserve)
    active = asyncio.create_task(c.async_volume(1, 7, levels.get, send))
    pending = None
    try:
        await sent.wait()
        pending = asyncio.create_task(request()); await asyncio.sleep(0)
        assert len(c._tasks) == 2 and writes == [(1, 0)]
        active.cancel()
        results = await asyncio.gather(active, pending, return_exceptions=True)
        assert isinstance(results[0], asyncio.CancelledError)
        assert isinstance(results[1], AudioCommandError)
        assert writes == [(1, 0)] and not sender.calls and not transports
        assert not c.uncertain and not c._requests and not c._scope
        await c.async_join(1, (3,))
        assert sender.calls == [('pair', (1, 2, 3))]
        assert not c._scope and not c._lock.locked()
    finally:
        for task in (active, pending):
            if task is not None: task.cancel()
        await asyncio.gather(*(t for t in (active, pending) if t is not None), return_exceptions=True)
        await c.async_close()


@pytest.mark.parametrize('boundary', ['context-aba', 'eligibility-aba', 'membership-aba', 'invalid-membership', 'invalidate', 'close'])
async def test_volume_failure_does_not_revive_revoked_membership_or_request(boundary):
    c, sender, eligible, context = owner(timeout=.08)
    c.observe(payload(row('pair', (1, 2))))
    levels, writes = {1: 10, 2: 38}, []
    def send(p, v):
        writes.append((p, v))
        if boundary == 'context-aba':
            for token in ('session-b', 'session-a'): context[0] = token; c.observe_current()
        elif boundary == 'eligibility-aba':
            eligible.remove(2); c.observe_current(); eligible.add(2); c.observe_current()
        elif boundary == 'membership-aba':
            c.observe(payload(row('other', (1, 3)))); c.observe(payload(row('pair', (1, 2))))
        elif boundary == 'invalid-membership': c.observe('{}')
        elif boundary == 'invalidate': c.invalidate()
        else:
            asyncio.create_task(c.async_close())
    try:
        result = (await asyncio.gather(c.async_volume(1, 7, levels.get, send), return_exceptions=True))[0]
        assert isinstance(result, (AudioCommandError, asyncio.CancelledError))
        assert writes == [(1, 0)] and not c._requests and not c._scope
        if boundary in ('invalid-membership', 'invalidate', 'close'):
            assert c.snapshot is None
            with pytest.raises(AudioCommandError): await c.async_join(1, (3,))
            assert not sender.calls
        else:
            assert not c.uncertain
            await c.async_join(1, (3,))
            assert sender.calls == [('pair', (1, 2, 3))]
    finally: await c.async_close()


@pytest.mark.parametrize('uncertain_kind', ['membership', 'transport'])
async def test_existing_true_uncertainty_cannot_be_cleared_by_volume(uncertain_kind):
    c, sender, _, _ = owner(timeout=.05)
    c.observe(payload(row('pair', (1, 2))))
    if uncertain_kind == 'membership':
        sender.mode = 'ack'
        with pytest.raises(AudioCommandError): await c.async_join(1, (3,))
    else:
        # Playback is not membership uncertainty. Establish a genuine prior
        # unconfirmed membership write; failed transport must never clear it.
        sender.mode = 'ack'
        with pytest.raises(AudioCommandError): await c.async_join(1, (3,))
        async def failed(*args, **kwargs):
            kwargs['on_send'](); raise AudioCommandError('synthetic unconfirmed transport')
        sender.async_group_transport = failed
        with pytest.raises(AudioCommandError):
            await c.async_transport(1, 'play', lambda players: (lambda: True, lambda: None))
    writes = []
    try:
        assert c.uncertain
        with pytest.raises(AudioCommandError):
            await c.async_volume(1, 7, {1: 10, 2: 38}.get, lambda *args: writes.append(args))
        assert c.uncertain and not writes
        with pytest.raises(AudioCommandError): await c.async_unjoin(1)
    finally: await c.async_close()
