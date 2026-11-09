"""Replay exact emitted full-native12-room requests at the owning HA bus boundary."""
import asyncio
import json
import os
from pathlib import Path
from custom_components.loxone.const import SENDDOMAIN
from test_audio_grouping_ha import grouped_setup,audio_setup,structure,row,action


async def test_exact_party_native_volume_requests_owning_ha(hass,grouped_setup,monkeypatch):
    trace=os.environ.get('GM03_BROWSER_REQUESTS')
    if not trace:raise RuntimeError('Required synthetic party request trace was not supplied')
    calls=json.loads(Path(trace).read_text())
    assert len(calls)==8 and {c['service'] for c in calls}=={'audio_room_volume','volume_set'}
    g=grouped_setup;g.source.clear();g.source.update(structure(count=12))
    entry,co,_=await g.setup();ids={e._audio_player_id:i for i,e in g.entities.items()}
    writes=[]
    async def feedback(event):
        writes.append(dict(event.data));p=next(p for p in ids if action(p)==event.data['uuid'])
        await g.callbacks[entry.entry_id]['callback']({f'volume-{p}':int(event.data['value'].split('/')[1])})
    remove=hass.bus.async_listen(SENDDOMAIN,feedback)
    try:
        for call in calls:
            states=call['states'];members=states[ids[1]]['attributes']['group_members'];players=tuple(next(p for p,i in ids.items() if i==m)for m in members)
            await g.feed(entry,row('party',players))
            old={p:round(states[i]['attributes']['loxone_room_volume_level']*100)for p,i in ids.items()}
            await g.callbacks[entry.entry_id]['callback']({**{f'play-{p}':1 for p in ids},**{f'volume-{p}':v for p,v in old.items()}})
            await hass.async_block_till_done()
            before=len(writes);room=call['service']=='audio_room_volume';target=next(p for p,i in ids.items() if i==call['target']['entity_id'])
            wanted=call['data']['volume_percent'] if room else round(call['data']['volume_level']*100)
            mean=(2*sum(old[p] for p in players)+len(players))//(2*len(players))
            expected={p:(wanted if p==target else v) if room else max(0,min(100,v+wanted-mean))for p,v in old.items()}
            await hass.services.async_call(call['domain'],call['service'],call['data'],target=call['target'],blocking=True)
            await hass.async_block_till_done()
            assert writes[before:]==[{'uuid':action(p),'value':f'volume/{expected[p]}'}for p in ((target,)if room else players)if expected[p]!=old[p]]
            assert {p:g.entities[i]._room_volume_percent for p,i in ids.items()}==expected
            assert co.audio_grouping.native.snapshot.groups[0].players==players
            assert not co.audio_grouping.native._scope and not co.audio_grouping.native._requests
    finally:remove()
