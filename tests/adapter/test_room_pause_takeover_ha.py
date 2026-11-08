"""Exact-room pause preserves existing independent-source cancellation precedence."""
import asyncio
import pytest
from homeassistant.exceptions import HomeAssistantError
from test_audio_grouping_ha import row
from test_audio_grouping_ha import grouped_setup as grouped_setup
from test_audio_grouping_ha import audio_setup as audio_setup
from test_audioserver_playback import rsa_key as rsa_key
from test_room_transport_fences_ha import room_peer as room_peer


@pytest.mark.parametrize('change', ['stable','token','event'])
async def test_row_pause_drains_only_its_independent_source_and_fences_drain(hass, room_peer, change):
    p=room_peer
    await p.g.feed(p.entry,row('other',(5,6)))
    await p.emit(1)
    e=p.g.entities[p.ids[1]]
    other=p.g.entities[p.ids[2]]
    entered,release=asyncio.Event(),asyncio.Event()
    async def source():
        try:
            await asyncio.Event().wait()
        finally:
            entered.set()
            await release.wait()
    old=asyncio.create_task(source())
    sibling=asyncio.create_task(asyncio.Event().wait())
    await asyncio.sleep(0)
    e._source_task=old
    other._source_task=sibling
    task=asyncio.create_task(hass.services.async_call('loxone','audio_room_transport',{'action':'pause'},target={'entity_id':p.ids[1]},blocking=True))
    try:
        await asyncio.wait_for(entered.wait(),1)
        assert p.sent()==[] and not task.done()
        if change=='token':
            for token in ('synthetic-replacement-token','synthetic-active-token'):
                p.token[0]=token;p.co._on_token_changed({'token':token})
        elif change=='event':
            await p.emit(1,mode='play',eventype=3)
            await p.emit(1)
        release.set()
        result=(await asyncio.wait_for(asyncio.gather(task,return_exceptions=True),2))[0]
        assert (result is None)==(change=='stable')
        if change!='stable': assert isinstance(result,(HomeAssistantError,asyncio.CancelledError))
        assert p.sent()==(['audio/1/pause'] if change=='stable' else [])
        assert not sibling.done() and other._source_task is sibling
        assert e._source_task is None and old.done()
        assert not p.co.audio_grouping.native._requests and not p.co.audio_grouping.native._scope
    finally:
        release.set()
        e._source_task=other._source_task=None
        for t in (task,old,sibling):t.cancel()
        await asyncio.gather(task,old,sibling,return_exceptions=True)
