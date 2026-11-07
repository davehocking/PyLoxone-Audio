"""Actual registered callers captured before failed playback stay revoked."""
import asyncio
import pytest
from homeassistant.exceptions import HomeAssistantError
from test_owner_playback_recovery_ha import playback_peer, assert_clean
from test_audio_grouping_ha import grouped_setup, audio_setup
from test_audioserver_playback import rsa_key


@pytest.mark.parametrize('queued', ['group', 'room', 'volume', 'manage'])
async def test_failed_registered_play_revokes_queued_caller_not_new_intent(hass, playback_peer, queued):
    p = playback_peer
    p.mode = 'hold'
    native = p.co.audio_grouping.native
    async def invoke(service, data=None, domain='media_player', player=1):
        return await hass.services.async_call(domain, service, data or {}, target={'entity_id': p.ids[player]}, blocking=True)
    active = asyncio.create_task(invoke('media_play'))
    pending = None
    try:
        await asyncio.wait_for(p.sent.wait(), 2)
        if queued == 'group': work = invoke('media_pause')
        elif queued == 'room': work = invoke('audio_room_transport', {'action': 'pause'}, 'loxone', 3)
        elif queued == 'volume': work = invoke('volume_set', {'volume_level': .4})
        else:
            d = p.co.audio_grouping.control_descriptor(1)
            work = invoke('audio_group_manage', {'action': 'add', 'revision': d['revision'], 'members': [p.ids[3]], 'group_id': 'pair'}, 'loxone')
        pending = asyncio.create_task(work)
        async with asyncio.timeout(2):
            while len(native._tasks) < 2: await asyncio.sleep(0)
        p.mode = 'reject'
        p.release.set()
        results = await asyncio.gather(active, pending, return_exceptions=True)
        assert all(isinstance(v, HomeAssistantError) for v in results)
        assert p.sent_commands() == ['audio/grouped/play/1,2'] and not p.writes
        assert not native.uncertain
        assert_clean(p)
        p.mode = 'normal'
        assert await p.call('media_player', 'media_play') == 'success'
        assert_clean(p)
    finally:
        for t in (active, pending):
            if t: t.cancel()
        await asyncio.gather(*(t for t in (active, pending) if t), return_exceptions=True)
