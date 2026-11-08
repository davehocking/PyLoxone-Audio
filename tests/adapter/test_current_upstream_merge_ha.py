"""Native upstream receive fixes remain active in the combined adapter."""
import asyncio
import json
import struct
from types import SimpleNamespace

import pytest

@pytest.mark.parametrize('cmd', ['keyexchange','getkey','getkey2','getvisusalt','getjwt','gettoken','refreshjwt','refreshtoken','authwithtoken','killtoken'])
@pytest.mark.parametrize('prefix', ['jdev/sys/', 'dev/sys/', ''])
async def test_upstream_auth_reply_never_reaches_public_callback(enable_custom_integrations, cmd, prefix):
    from custom_components.loxone.pyloxone_api.connection import LoxoneConnection, is_auth_response
    from custom_components.loxone.pyloxone_api.message import TextMessage
    from custom_components.loxone.pyloxone_api.exceptions import LoxoneConnectionClosedOk
    control = prefix + cmd + '/synthetic'
    body = json.dumps({'LL': {'control': control, 'Code': '200', 'value': 'SYNTHETIC-NOT-CREDENTIAL'}}).encode()
    assert is_auth_response(TextMessage(body))
    messages = [struct.pack('<BBBBI', 3, 0, 0, 0, len(body)), body]
    class Wire:
        state = SimpleNamespace(CLOSED='closed')
        def __aiter__(self):
            self.it = iter(messages)
            return self
        async def __anext__(self):
            try:
                return next(self.it)
            except StopIteration:
                raise StopAsyncIteration
    seen = []
    internal = []
    tasks = []
    client = object.__new__(LoxoneConnection)
    client._auth_failure = None
    async def event(message):
        internal.append(message.control)
    client._websocket_event = event
    client._spawn_task = lambda coro, **kwargs: tasks.append(asyncio.create_task(coro))
    with pytest.raises(LoxoneConnectionClosedOk):
        await client._do_start_listening(seen.append, Wire())
    await asyncio.gather(*tasks)
    assert seen == []
    assert internal == [control]

@pytest.mark.parametrize('async_callback', [False, True])
async def test_upstream_ordinary_callback_sync_and_async(enable_custom_integrations, async_callback, caplog):
    from custom_components.loxone.pyloxone_api.connection import LoxoneConnection, is_auth_response
    from custom_components.loxone.pyloxone_api.message import TextMessage
    from custom_components.loxone.pyloxone_api.exceptions import LoxoneConnectionClosedOk
    body = json.dumps({'LL': {'control': 'jdev/sps/io/synthetic/status', 'Code': '200', 'value': 'ordinary'}}).encode()
    assert not is_auth_response(TextMessage(body))
    class Wire:
        state = SimpleNamespace(CLOSED='closed')
        def __aiter__(self):
            self.it = iter([struct.pack('<BBBBI', 3, 0, 0, 0, len(body)), body])
            return self
        async def __anext__(self):
            try:
                return next(self.it)
            except StopIteration:
                raise StopAsyncIteration
    seen, tasks = [], []
    async def callback(message):
        await asyncio.sleep(0)
        seen.append(message)
    async def event(message):
        pass
    client = object.__new__(LoxoneConnection)
    client._auth_failure = None
    client._websocket_event = event
    client._spawn_task = lambda coro, **kwargs: tasks.append(asyncio.create_task(coro))
    with pytest.raises(LoxoneConnectionClosedOk):
        await client._do_start_listening(callback if async_callback else seen.append, Wire())
    await asyncio.gather(*tasks)
    assert len(seen) == 1
    assert seen[0]['value'] == 'ordinary'
    assert 'Callback error' not in caplog.text
