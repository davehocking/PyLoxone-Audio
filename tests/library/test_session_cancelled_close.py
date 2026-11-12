"""One-time cancellation outcome must not poison later idempotent unload."""
import asyncio
import pytest
from pyloxone_audio import native
from session_support import Peer


async def test_repeated_unload_does_not_replay_owned_close_cancellation(monkeypatch):
    peer = Peer()
    peer.response = lambda _: {'pause_result': True}
    original_connect = peer.connect
    def connect(*args, **kwargs):
        context = original_connect(*args, **kwargs)
        original_exit = context.__aexit__
        async def cancel_close(*values):
            await original_exit(*values)
            asyncio.current_task().cancel()
            await asyncio.sleep(0)
        context.__aexit__ = cancel_close
        return context
    monkeypatch.setattr(native, 'connect', connect)
    owner = native.AudioServerCommands('synthetic.invalid', lambda: ('u', 't'))
    owner.reuse_session = True
    try:
        with pytest.raises(asyncio.CancelledError):
            await owner.async_execute(7, 'pause')
        assert peer.sends == ['audio/7/pause']
        assert peer.closes == 1
        await owner.async_close()
        await owner.async_close()
        assert owner._session is None
        assert not asyncio.current_task().cancelling()
    finally:
        await peer.finish()
