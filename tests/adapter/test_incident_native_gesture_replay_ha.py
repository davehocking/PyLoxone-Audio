"""Literal current native gesture requests, replayed offline through owning HA."""
import json
import os
from pathlib import Path

import pytest
from custom_components.loxone.const import SENDDOMAIN
from test_audio_grouping_ha import grouped_setup as grouped_setup
from test_audio_grouping_ha import audio_setup as audio_setup
from test_audio_grouping_ha import structure, row, action


@pytest.mark.parametrize('index',range(4))
async def test_exact_new_incident_native_gesture_volume_request(hass,grouped_setup,index):
    trace=os.environ.get('GM03_BROWSER_REQUESTS')
    if not trace:
        raise RuntimeError('Required invented native gesture trace is missing')
    calls=json.loads(Path(trace).read_text())
    assert len(calls)==4
    call=calls[index]
    assert call['domain']=='media_player' and call['service']=='volume_set'
    assert call['data']=={'volume_level':.65}
    g=grouped_setup
    g.source.clear()
    g.source.update(structure(count=12))
    entry,co,_=await g.setup()
    ids={e._audio_player_id:i for i,e in g.entities.items()}
    numbers={i:p for p,i in ids.items()}
    states=call['states']
    target=call['target']['entity_id']
    members=(numbers[target],)  # v3 native public volume is room-only.
    groups={}
    for entity_id in ids.values():
        descriptor=states[entity_id]['attributes']['loxone_group_control']
        if descriptor.get('group_id') is not None:
            groups[descriptor['group_id']]=tuple(numbers[i] for i in descriptor['members'])
    await g.feed(entry,*(row(name,players) for name,players in groups.items()))
    old={p:round(states[i]['attributes']['loxone_room_volume_level']*100) for p,i in ids.items()}
    await g.callbacks[entry.entry_id]['callback']({**{f'play-{p}':1 for p in ids},**{f'volume-{p}':v for p,v in old.items()}})
    await hass.async_block_till_done()
    original_groups=co.audio_grouping.native.snapshot.groups
    mean=(2*sum(old[p] for p in members)+len(members))//(2*len(members))
    expected={p:max(0,min(100,v+65-mean)) if p in members else v for p,v in old.items()}
    writes=[]
    async def feedback(event):
        writes.append(dict(event.data))
        player=next(p for p in ids if action(p)==event.data['uuid'])
        await g.callbacks[entry.entry_id]['callback']({f'volume-{player}':int(event.data['value'].split('/')[1])})
    remove=hass.bus.async_listen(SENDDOMAIN,feedback)
    try:
        await hass.services.async_call(call['domain'],call['service'],call['data'],target=call['target'],blocking=True)
        await hass.async_block_till_done()
        assert writes==[{'uuid':action(p),'value':f'volume/{expected[p]}'} for p in members if expected[p]!=old[p]]
        assert {p:g.entities[i]._room_volume_percent for p,i in ids.items()}==expected
        assert co.audio_grouping.native.snapshot.groups==original_groups
        assert not co.audio_grouping.native._scope and not co.audio_grouping.native._requests
        assert not co.audio_grouping.native._lock.locked()
    finally:
        remove()
