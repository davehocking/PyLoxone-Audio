"""Queued request guards are scoped, monotonic and removed on every exit."""
import asyncio

import pytest
from pyloxone_audio.native import AudioCommandError
from test_group_coordinator import owner
from test_audio_grouping import payload, row


@pytest.mark.parametrize('operation', ['transport', 'mutation'])
@pytest.mark.parametrize('change', ['stable', 'context', 'eligibility', 'outside-eligibility', 'cancel'])
async def test_request_observes_reversion_before_first_lock_await(operation, change):
    c, sender, eligible, context = owner(timeout=1)
    c.observe(payload(row('native', (1, 2))))
    calls = []

    async def transport(members, action, *, is_current, on_send):
        assert is_current()
        on_send()
        calls.append((members, action))

    sender.async_group_transport = transport
    task = None
    try:
        async with c._lock:
            request = c.async_transport(1, 'play', lambda players: (lambda: True, lambda: None)) if operation == 'transport' else c.async_join(1, (3,))
            task = asyncio.create_task(request)
            await asyncio.sleep(0)
            if change == 'context':
                context[0] = 'session-b'
                c.observe(payload(row('native', (1, 2))))
                context[0] = 'session-a'
                c.observe(payload(row('native', (1, 2))))
            elif change in ('eligibility', 'outside-eligibility'):
                player = 2 if change == 'eligibility' else 6
                eligible.remove(player)
                c.observe(payload(row('native', (1, 2))))
                eligible.add(player)
                c.observe(payload(row('native', (1, 2))))
            elif change == 'cancel':
                task.cancel()
        result = (await asyncio.gather(task, return_exceptions=True))[0]
        if change in ('context', 'eligibility'):
            assert isinstance(result, AudioCommandError)
        elif change == 'cancel':
            assert isinstance(result, asyncio.CancelledError)
        else:
            assert result is None
        assert len(calls if operation == 'transport' else sender.calls) == (change in ('stable', 'outside-eligibility'))
        assert not c._tasks
        assert not c._scope
        assert not c.uncertain
        assert not c._requests
    finally:
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await c.async_close()
