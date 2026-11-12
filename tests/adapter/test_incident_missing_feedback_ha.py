"""Discriminate missing member confirmation from projection cost; invented I/O only."""
import asyncio
import json
from pathlib import Path
from time import perf_counter

from homeassistant.exceptions import HomeAssistantError
from custom_components.loxone.const import SENDDOMAIN
from test_audio_grouping_ha import grouped_setup as grouped_setup
from test_audio_grouping_ha import audio_setup as audio_setup
from test_audio_grouping_ha import action, structure, row


async def test_four_writes_then_missing_fourth_feedback_refuses_without_retry(hass, grouped_setup):
    g=grouped_setup
    g.source.clear()
    g.source.update(structure(count=13))
    entry,co,_=await g.setup()
    ids={e._audio_player_id:i for i,e in g.entities.items()}
    await g.feed(entry,row('invented-group',(1,2,3,4,5)))
    callback=g.callbacks[entry.entry_id]['callback']
    initial={p:([17,20,20,20,30][p-1] if p<=5 else 10) for p in ids}
    await callback({**{f'play-{p}':1 for p in ids},**{f'volume-{p}':v for p,v in initial.items()}})
    await hass.async_block_till_done()
    owner=co.audio_grouping
    assert owner.native.timeout==8
    writes=[]
    async def feedback(event):
        player=next(p for p in ids if action(p)==event.data['uuid'])
        value=int(event.data['value'].split('/')[1])
        writes.append((player,value))
        if player!=4:
            await callback({f'volume-{player}':value})
    remove=hass.bus.async_listen(SENDDOMAIN,feedback)
    error=None
    start=perf_counter()
    try:
        try:
            await asyncio.wait_for(hass.services.async_call('loxone','audio_group_volume',{'entity_id':ids[1],'volume_percent':22},blocking=True),30)
        except HomeAssistantError as caught:
            error=type(caught).__name__
        await hass.async_block_till_done()
        report={'cause':'synthetic fourth-member confirmation withheld','historical_cause_proven':False,'error':error,'writes':writes,'elapsed_s':perf_counter()-start,'deadline':owner.native.timeout}
        Path('volume-missing-fourth-feedback.json').write_text(json.dumps(report,indent=2)+'\n')
        assert error=='HomeAssistantError',report
        assert writes==[(1,18),(2,21),(3,21),(4,21)],report
        assert g.entities[ids[4]]._room_volume_percent==20
        assert g.entities[ids[5]]._room_volume_percent==30
        assert not owner.native._scope and not owner.native._tasks and not owner.native._requests
        assert not owner.native._lock.locked()
    finally:
        remove()
