"""Authoritative UI export through actual owning HA states, no household data."""
import json
import os
from pathlib import Path
from homeassistant.helpers import entity_registry as er
from test_audio_grouping_ha import grouped_setup as grouped_setup
from test_audio_grouping_ha import audio_setup as audio_setup
from test_audio_grouping_ha import row


async def test_room_partition_states_from_real_ha(hass, grouped_setup, tmp_path):
    g = grouped_setup
    entry, co, ids = await g.setup()
    # Owner display names are preserved verbatim, independent of room metadata.
    names = {1:'Zulu',2:'alpha',3:'BRAVO',4:'Alpine',5:'charlie',6:'delta'}
    for p in ids:
        er.async_get(hass).async_update_entity(ids[p], name=names[p])
    await hass.async_block_till_done()
    await g.feed(entry, row('native',(1,3,2)), row('fixed',(5,6),'static'))
    await g.callbacks[entry.entry_id]['callback']({**{f'play-{p}':1 for p in ids}, **{f'volume-{p}':p*10 for p in ids}})
    await hass.async_block_till_done()
    snapshots = []
    def capture(label):
        snapshots.append({'scenario':label,'target':ids[3], 'states':{i:hass.states.get(i).as_dict() for i in ids.values()}, 'entities':{i:{'entity_id':i,'platform':'loxone','config_entry_id':entry.entry_id,'area_id':'DUPLICATE-AREA-NOT-FOR-DISPLAY'} for i in ids.values()}})
    capture('confirmed')
    d = hass.states.get(ids[3]).attributes.get('loxone_group_control')
    assert d is not None, 'Optional popup needs authoritative native eligibility, not same-platform guessing'
    assert d['members'] == [ids[1],ids[3],ids[2]]
    assert d['candidates'] == [ids[p] for p in (1,2,3,4)]
    assert d['group_id'] == 'native'
    assert d['owner']
    assert not hass.states.get(ids[5]).attributes.get('loxone_group_control')
    await g.feed(entry, row('native',(1,3)), row('fixed',(5,6),'static'))
    capture('two-members')
    await g.feed(entry, row('native',(1,4,2)), row('fixed',(5,6),'static'))
    capture('external')
    assert hass.states.get(ids[3]).attributes['loxone_group_control']['members'] == [ids[3]]
    await g.feed(entry,row('native',(1,3,2)),row('other',(5,4)),row('fixed',(6,),'static'))
    capture('other-group')
    await g.feed(entry,row('native',(1,4,2)),row('fixed',(5,6),'static'))
    co.audio_grouping.connection_state('disconnected')
    await hass.async_block_till_done()
    capture('unknown')
    assert not hass.states.get(ids[3]).attributes.get('loxone_group_control')
    Path(os.environ.get('ROOM_CONTROL_STATES',tmp_path/'room-control-states.json')).write_text(json.dumps(snapshots,default=str,indent=2)+'\n')
