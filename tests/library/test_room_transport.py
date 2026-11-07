"""Portable exact-room scope and backward-compatible optional native fencing."""
import asyncio
from unittest.mock import AsyncMock

import pytest
from pyloxone_audio import native
from test_group_coordinator import owner
from test_audio_grouping import payload, row


async def test_old_execute_callers_keep_exact_old_request_signature(monkeypatch):
    client=native.AudioServerCommands('synthetic.invalid',lambda:('synthetic','synthetic'))
    current=lambda:True
    request=AsyncMock(return_value=True)
    monkeypatch.setattr(client,'_async_request',request)
    await client.async_execute(13,'play',is_current=current)
    request.assert_awaited_once_with('audio/13/play','play_result',is_current=current)
    await client.async_close()


@pytest.mark.parametrize('change',['stable','credentials','applicability','closed'])
async def test_optional_execute_cleanup_fence_and_send_callback(monkeypatch,change):
    credentials=['synthetic','token-a']
    current=[True]
    sent=[]
    client=native.AudioServerCommands('synthetic.invalid',lambda:tuple(credentials))
    async def request(command,reply_key,*,is_current,on_send,strict_reply):
        assert strict_reply is True
        assert command=='audio/13/pause' and reply_key=='pause_result'
        assert is_current();on_send()
        if change=='credentials': credentials[1]='token-b'
        elif change=='applicability': current[0]=False
        elif change=='closed': client._closed=True
        return True  # The synthetic request has completed its cleanup now.
    monkeypatch.setattr(client,'_async_request',request)
    call=client.async_execute(13,'pause',is_current=lambda:current[0],on_send=lambda:sent.append('sent'),guard_cleanup=True)
    if change=='stable': await call
    else:
        with pytest.raises(native.AudioCommandError): await call
    assert sent==['sent']
    await client.async_close()


@pytest.mark.parametrize('target',[1,2,4])
async def test_room_transport_reserves_exact_target_without_changing_native_group(target):
    c,s,eligible,context=owner(timeout=1)
    c.observe(payload(row('native',(2,1,3)),row('other',(5,6))))
    before=c.snapshot
    calls=[]
    released=[]
    async def execute(player,action,*,is_current,on_send,guard_cleanup):
        assert player==target and action=='play' and guard_cleanup is True
        assert c._scope==frozenset({target}) and is_current()
        on_send();calls.append((player,action))
    s.async_execute=execute
    def reserve(players):
        assert players==(target,)
        return lambda:True,lambda:released.append(players)
    await c.async_room_transport(target,'play',reserve)
    assert calls==[(target,'play')] and released==[(target,)]
    assert c.snapshot==before and not c._scope and not c._requests and not c._tasks
    assert s.calls==[]
    await c.async_close()


@pytest.mark.parametrize('boundary',['stable','target','outside','context','cancel'])
async def test_room_request_queued_scope_and_monotonic_context(boundary):
    c,s,eligible,context=owner(timeout=1)
    c.observe(payload(row('native',(2,1,3))))
    calls=[]
    async def execute(player,action,*,is_current,on_send,guard_cleanup):
        assert is_current();on_send();calls.append(player)
    s.async_execute=execute
    task=None
    try:
        async with c._lock:
            task=asyncio.create_task(c.async_room_transport(1,'play',lambda players:(lambda:True,lambda:None)))
            await asyncio.sleep(0)
            if boundary in ('target','outside'):
                player=1 if boundary=='target' else 2
                eligible.remove(player);c.observe_current()
                eligible.add(player);c.observe_current()
            elif boundary=='context':
                context[0]='session-b';c.observe_current()
                context[0]='session-a';c.observe_current()
            elif boundary=='cancel':task.cancel()
        result=(await asyncio.gather(task,return_exceptions=True))[0]
        assert (result is None)==(boundary in ('stable','outside'))
        assert calls==([1] if boundary in ('stable','outside') else [])
        assert not c.uncertain and not c._requests and not c._tasks and not c._scope
    finally:
        if task:task.cancel();await asyncio.gather(task,return_exceptions=True)
        await c.async_close()


async def test_room_and_mutation_share_the_same_serial_lock():
    c,s,eligible,context=owner(timeout=1)
    c.observe(payload(row('native',(2,1,3))))
    entered,release=asyncio.Event(),asyncio.Event()
    order=[]
    async def execute(player,action,*,is_current,on_send,guard_cleanup):
        assert is_current();on_send();order.append('room-send');entered.set()
        await release.wait()
        assert is_current();order.append('room-cleanup')
    s.async_execute=execute
    first=asyncio.create_task(c.async_room_transport(1,'pause',lambda players:(lambda:True,lambda:None)))
    second=None
    try:
        await asyncio.wait_for(entered.wait(),1)
        second=asyncio.create_task(c.async_unjoin(3))
        await asyncio.sleep(0)
        assert not second.done() and s.calls==[]
        release.set()
        await asyncio.gather(first,second)
        assert order==['room-send','room-cleanup']
        assert s.calls==[('native',(2,1))]
        assert not c._requests and not c._tasks and not c._scope
    finally:
        release.set()
        for task in (first,second):
            if task:task.cancel()
        await asyncio.gather(*(t for t in (first,second) if t),return_exceptions=True)
        await c.async_close()
