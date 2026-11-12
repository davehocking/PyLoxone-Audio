"""Post-lock absolute ROOM baselines; GROUP policy and revocation remain strict."""
import asyncio
import pytest
from pyloxone_audio.native import AudioCommandError
from test_group_coordinator import owner
from test_audio_grouping import payload, row


@pytest.mark.parametrize('room_only', [True, False])
@pytest.mark.parametrize('change', ['volume', 'context-aba', 'membership-aba', 'eligibility-aba', 'qualified-aba', 'unknown', 'cancel', 'timeout'])
async def test_queued_absolute_room_rebase_preserves_all_nonvolume_fences(room_only, change):
    c, sender, eligible, context = owner(timeout=.06 if change == 'timeout' else 1)
    c.observe(payload(row('pair', (1, 2))))
    levels, writes, valid = {1:10, 2:38}, [], [True]
    def send(p,v): writes.append((p,v)); levels[p]=v; c.observe_current()
    task=None
    try:
        async with c._lock:
            task=asyncio.create_task(c.async_volume(1, 50, levels.get, send, room_only=room_only, qualified=lambda:valid[0]))
            await asyncio.sleep(0)
            assert len(c._requests)==2
            if change=='volume': levels[1]=20; c.observe_current()
            elif change=='context-aba':
                for token in ('session-b','session-a'):context[0]=token; c.observe_current()
            elif change=='membership-aba':
                c.observe(payload(row('other',(1,3))));c.observe(payload(row('pair',(1,2))))
            elif change=='eligibility-aba':
                eligible.remove(1);c.observe_current();eligible.add(1);c.observe_current()
            elif change=='qualified-aba':
                valid[0]=False;c.observe_current();valid[0]=True;c.observe_current()
            elif change=='unknown': levels[1]=None;c.observe_current()
            elif change=='cancel':task.cancel()
            else: await asyncio.sleep(.08)
        outcome=(await asyncio.gather(task,return_exceptions=True))[0]
        if room_only and change=='volume':
            assert outcome is None and writes==[(1,50)] and levels[2]==38
        else:
            assert isinstance(outcome,asyncio.CancelledError if change=='cancel' else AudioCommandError)
            assert writes==[]
        assert not c._requests and not c._tasks and not c._scope and not c._lock.locked()
        levels[1]=20
        await c.async_volume(1,51,levels.get,send,room_only=True)
        assert writes[-1]==(1,51)
    finally:
        if task and not task.done(): task.cancel();await asyncio.gather(task,return_exceptions=True)
        await c.async_close()


@pytest.mark.parametrize('failure',['external-volume','cancel','timeout','send-error'])
async def test_room_dispatch_guards_failure_generation_and_healthy_successor(failure):
    c,sender,_,_=owner(timeout=.08)
    c.observe(payload(row('pair',(1,2))))
    levels,writes={1:10,2:38},[]
    sent=asyncio.Event()
    def send(p,v):
        writes.append((p,v));sent.set()
        if failure=='send-error':raise AudioCommandError('Synthetic failure')
    active=asyncio.create_task(c.async_volume(1,50,levels.get,send,room_only=True))
    queued=None
    try:
        await asyncio.wait_for(sent.wait(),1)
        queued=asyncio.create_task(c.async_volume(1,60,levels.get,send,room_only=True));await asyncio.sleep(0)
        if failure=='external-volume':levels[1]=33;c.observe_current()
        elif failure=='cancel':active.cancel()
        outcomes=await asyncio.gather(active,queued,return_exceptions=True)
        assert isinstance(outcomes[0],(AudioCommandError,asyncio.CancelledError))
        # send-error completes synchronously before the pending request is captured;
        # all other requests were captured before the active failure generation.
        if failure!='send-error': assert isinstance(outcomes[1],AudioCommandError) and writes==[(1,50)]
        assert not c._requests and not c._scope and not c._tasks and not c._lock.locked()
        def confirm(p,v):writes.append((p,v));levels[p]=v;c.observe_current()
        await c.async_volume(1,61,levels.get,confirm,room_only=True)
        assert writes[-1]==(1,61) and levels[2]==38
    finally:
        for t in (active,queued):
            if t and not t.done():t.cancel()
        await asyncio.gather(*(t for t in (active,queued) if t),return_exceptions=True)
        await c.async_close()
