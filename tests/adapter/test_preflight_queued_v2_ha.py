"""Owning service must bind its content before the first queued-lock await."""
import asyncio
import pytest
from test_preflight_lifetimes_ha import preflight_peer
from test_precommand_parent_qualification_v2_ha import native_row
from test_audio_grouping_ha import grouped_setup, audio_setup
from test_audioserver_playback import rsa_key


async def test_grouped_content_ABA_while_queued_never_rebinds(preflight_peer):
    p = preflight_peer
    n = p.co.audio_grouping.native
    await n._lock.acquire()
    task = asyncio.create_task(p.call('queued-content-ABA'))
    try:
        async with asyncio.timeout(2):
            while not n._tasks:
                await asyncio.sleep(0)
        await p.emit(native_row(2, None, audiopath='library:local:track:replacement'))
        await p.emit(native_row(2, None))
    finally:
        n._lock.release()
    try:
        assert await task == 'HomeAssistantError', p.receipt
        assert not p.routes, p.receipt
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
