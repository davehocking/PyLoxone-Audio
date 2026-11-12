"""Actual registered ROOM route; initiating authority remains observed while queued."""
import asyncio
import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from custom_components.loxone.const import SENDDOMAIN
from test_audio_grouping_ha import action, row, grouped_setup, audio_setup
from test_group_modes_leader_ha import harness, rsa_key


@pytest.mark.parametrize('change',['stable-volume','source-aba','account-aba','token-aba','membership-aba','registry-aba','content-aba','busy-aba'])
async def test_room_queue_rebases_volume_only_not_initiating_context(hass,grouped_setup,audio_setup,monkeypatch,rsa_key,change):
    h=await harness(hass,grouped_setup,audio_setup,monkeypatch,rsa_key,count=6)
    g=h.g;ids={p:e.entity_id for p,e in h.entities.items()}
    await g.feed(h.entry,row('pair',(1,2)))
    await g.callbacks[h.entry.entry_id]['callback']({f'volume-{p}':10*p for p in ids})
    await hass.async_block_till_done()
    writes=[]
    async def feedback(event):
        writes.append(dict(event.data))
        await g.callbacks[h.entry.entry_id]['callback']({'volume-1':int(event.data['value'].split('/')[1])})
    remove=hass.bus.async_listen(SENDDOMAIN,feedback)
    task=None
    try:
        async with h.co.audio_grouping.native._lock:
            task=asyncio.create_task(hass.services.async_call('media_player','volume_set',{'volume_level':.5},target={'entity_id':ids[1]},blocking=True))
            for _ in range(100):
                if len(h.co.audio_grouping.native._requests)==2:break
                await asyncio.sleep(.001)
            assert len(h.co.audio_grouping.native._requests)==2
            if change=='stable-volume':await g.callbacks[h.entry.entry_id]['callback']({'volume-1':22})
            elif change in ('source-aba','account-aba','content-aba'):
                field={'source-aba':'sourceName','account-aba':'parent','content-aba':'audiopath'}[change]
                old=h.rows[1][field]
                new={'id':'library:local:album:other-account'} if field=='parent' else 'synthetic-changed'
                await h.emit(1,**{field:new});await h.emit(1,**{field:old})
            elif change=='token-aba':
                original=h.co.api.get_token_dict
                h.co.api.get_token_dict=lambda:{'token':'synthetic-replaced'};h.co.audio_grouping.notify()
                h.co.api.get_token_dict=original;h.co.audio_grouping.notify()
            elif change=='membership-aba':
                await g.feed(h.entry,row('other',(1,3)));await g.feed(h.entry,row('pair',(1,2)))
            elif change=='registry-aba':
                registry=er.async_get(hass)
                original=registry.async_get(ids[1]).unique_id
                registry.async_update_entity(ids[1],new_unique_id='synthetic-rebound-identity')
                await asyncio.sleep(0)
                registry.async_update_entity(ids[1],new_unique_id=original)
                await asyncio.sleep(0)
            else:
                e=h.entities[1];e._source_task=asyncio.current_task();h.co.audio_grouping.notify();e._source_task=None;h.co.audio_grouping.notify()
        result=(await asyncio.gather(task,return_exceptions=True))[0]
        await hass.async_block_till_done()
        if change=='stable-volume':assert result is None and writes==[{'uuid':action(1),'value':'volume/50'}]
        else:assert isinstance(result,HomeAssistantError) and writes==[]
        assert all(h.entities[p]._room_volume_percent==p*10 for p in ids if p!=1)
        assert not h.co.audio_grouping.native._requests and not h.co.audio_grouping.native._scope
        assert h.writes==[] and h.sockets==[]
        await hass.services.async_call('media_player','volume_set',{'volume_level':.51},target={'entity_id':ids[1]},blocking=True)
        assert writes[-1]=={'uuid':action(1),'value':'volume/51'}
    finally:
        if task and not task.done():task.cancel();await asyncio.gather(task,return_exceptions=True)
        remove()
