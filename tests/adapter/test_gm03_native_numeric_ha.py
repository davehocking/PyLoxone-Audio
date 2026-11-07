"""All 200 literal native-compiled manager nudges through owning HA and bus."""
import copy
from custom_components.loxone.const import SENDDOMAIN
from test_audio_grouping_ha import action, row
from test_audio_grouping_ha import grouped_setup as grouped_setup, audio_setup as audio_setup
from test_room_transport_ha import catalogue_state
from gm03_native_trace import native_trace


async def test_exact_native_integer_nudges_owning_bus_and_raw_scope(hass,grouped_setup,monkeypatch):
    requests=native_trace('integer_nudges')
    assert {(r['from'],r['delta']) for r in requests}=={(p,d) for p in range(101) for d in [-1,1] if 0<=p+d<=100}
    g=grouped_setup;entry,co,ids=await g.setup()
    await g.feed(entry,row('one',(1,2)),row('outside',(3,4)))
    captured=[]
    async def sent(event):
        captured.append(dict(event.data))
        p=next(p for p in ids if action(p)==event.data['uuid'])
        await g.callbacks[entry.entry_id]['callback']({f'volume-{p}':int(event.data['value'].split('/')[1])})
    remove=hass.bus.async_listen(SENDDOMAIN,sent)
    try:
        for request in requests:
            before=request['states']
            await g.callbacks[entry.entry_id]['callback']({**{f'play-{p}':1 for p in ids},**{f'volume-{p}':round(before[i]['attributes']['loxone_room_volume_level']*100) for p,i in ids.items()}})
            await hass.async_block_till_done()
            raw={i:hass.states.get(i).attributes['loxone_room_volume_level'] for i in ids.values()}
            groups={i:hass.states.get(i).attributes['group_members'] for i in ids.values()}
            preserved={i:copy.deepcopy(catalogue_state(e)) for i,e in g.entities.items()}
            assert all(groups[i]==before[i]['attributes']['group_members'] for i in ids.values())
            co.api.send_websocket_command.reset_mock();start=len(captured)
            await hass.services.async_call(request['domain'],request['service'],request['data'],target=request['target'],blocking=True)
            await hass.async_block_till_done()
            p=request['from']+request['delta'];assert request['data']['volume_percent']==p
            assert captured[start:]==[{'uuid':action(1),'value':f'volume/{p}'}]
            assert [list(c.args) for c in co.api.send_websocket_command.await_args_list]==[[action(1),f'volume/{p}']]
            raw[ids[1]]=p/100
            assert {i:hass.states.get(i).attributes['loxone_room_volume_level'] for i in ids.values()}==raw
            assert hass.states.get(ids[2]).attributes['volume_level']==((2*(p+40)+2)//4)/100
            assert {i:hass.states.get(i).attributes['group_members'] for i in ids.values()}==groups
            assert {i:catalogue_state(e) for i,e in g.entities.items()}==preserved
            assert not co.audio_grouping.native._scope and not co.audio_grouping.native._requests and not co.audio_grouping.native._tasks
            assert all(not e._transport_tasks for e in g.entities.values())
    finally:
        remove();await co.audio_commands.async_close()
