"""Separate volume scale oracle. Feedback is synthetic, never household data."""
import asyncio
import pytest
from test_audio_grouping_ha import grouped_setup, audio_setup, structure, row, action
from custom_components.loxone.const import SENDDOMAIN


@pytest.mark.parametrize('count,delay',[(2,.01),(4,.01),(5,.01),(12,.75)])
async def test_party_volume_preserves_balance_with_delayed_per_room_feedback(hass,grouped_setup,count,delay):
    g=grouped_setup;g.source.clear();g.source.update(structure(count=12))
    entry,co,_=await g.setup();ids={e._audio_player_id:i for i,e in g.entities.items()}
    players=tuple(range(1,count+1));await g.feed(entry,row('party',players))
    old={p:20+p for p in ids};mean=(2*sum(old[p] for p in players)+count)//(2*count)
    await g.callbacks[entry.entry_id]['callback']({**{f'play-{p}':1 for p in ids},**{f'volume-{p}':v for p,v in old.items()}})
    await hass.async_block_till_done();writes=[]
    async def feedback(event):
        writes.append(dict(event.data));p=next(p for p in ids if action(p)==event.data['uuid'])
        await asyncio.sleep(delay)
        await g.callbacks[entry.entry_id]['callback']({f'volume-{p}':old[p]+10})
    remove=hass.bus.async_listen(SENDDOMAIN,feedback)
    try:
        await hass.services.async_call('media_player','volume_set',{'entity_id':ids[1],'volume_level':(mean+10)/100},blocking=True)
        await hass.async_block_till_done()
        assert writes==[{'uuid':action(p),'value':f'volume/{old[p]+10}'}for p in players]
        assert {p:g.entities[i]._room_volume_percent for p,i in ids.items()}=={p:v+(10 if p in players else 0)for p,v in old.items()}
        assert co.audio_grouping.native.snapshot.groups[0].players==players
        assert not co.audio_grouping.native._scope and not co.audio_grouping.native._requests
        assert not co.audio_grouping.native._lock.locked()
    finally:remove()
