"""GM03 owning HA volume contract: invented native identities, no household I/O."""
from test_audio_grouping_ha import grouped_setup as grouped_setup
from test_audio_grouping_ha import audio_setup as audio_setup
from test_audio_grouping_ha import row
from test_audio_grouping_ha import action
import asyncio
from custom_components.loxone.const import SENDDOMAIN
import pytest
from homeassistant.exceptions import HomeAssistantError


@pytest.mark.parametrize('levels,requested,expected', [
    ([10.0,40.0],45,[30,60]), ([10,11],12,[11,12]),
    ([90,100],100,[95,100]), ([0,10],0,[0,5]),
    ([0,100],50,[0,100]), ([28,28],29,[29,29]),
    ([56,56],57,[57,57]), ([57,57],58,[58,58]),
    ([10,40],0,[0,15]), ([10,40],100,[85,100]),
])
async def test_integer_mean_delta_clamp_noop_and_native_float_feedback(hass,grouped_setup,levels,requested,expected):
    g=grouped_setup;entry,co,ids=await g.setup();await g.feed(entry,row('one',(1,2)))
    await g.callbacks[entry.entry_id]['callback']({'play-1':1,'play-2':1,'volume-1':levels[0],'volume-2':levels[1]});await hass.async_block_till_done()
    writes=[]
    async def feedback(event):
        writes.append(dict(event.data));p=next(p for p in ids if action(p)==event.data['uuid'])
        await g.callbacks[entry.entry_id]['callback']({f'volume-{p}':int(event.data['value'].split('/')[1])})
    remove=hass.bus.async_listen(SENDDOMAIN,feedback)
    try:
        await hass.services.async_call('loxone','audio_group_volume',{'volume_percent':requested},target={'entity_id':ids[2]},blocking=True)
        await hass.async_block_till_done()
        assert writes==[{'uuid':action(p),'value':f'volume/{v}'} for p,v,old in zip((1,2),expected,levels) if v!=old]
        assert [hass.states.get(ids[p]).attributes['loxone_room_volume_level'] for p in (1,2)]==[v/100 for v in expected]
        assert hass.states.get(ids[1]).attributes['loxone_group_volume_level']==((sum(expected)*2+len(expected))//(2*len(expected)))/100
    finally:remove()


@pytest.mark.parametrize('bad',[None,True,-1,101,'10',float('nan')])
async def test_unknown_member_does_not_fabricate_mean_and_room_remains_independent(hass,grouped_setup,bad):
    g=grouped_setup;entry,co,ids=await g.setup();await g.feed(entry,row('one',(1,2)))
    await g.callbacks[entry.entry_id]['callback']({'play-1':1,'play-2':1,'volume-1':10,'volume-2':bad});await hass.async_block_till_done()
    assert hass.states.get(ids[1]).attributes.get('loxone_group_volume_level') is None
    with pytest.raises(HomeAssistantError):await hass.services.async_call('loxone','audio_group_volume',{'volume_percent':45},target={'entity_id':ids[1]},blocking=True)
    assert co.api.send_websocket_command.call_count==0


@pytest.mark.parametrize('invalidate',['timeout','auth-aba','group-aba','disconnect','unload'])
async def test_partial_group_volume_never_continues_after_latched_invalidation(hass,grouped_setup,invalidate):
    g=grouped_setup;entry,co,ids=await g.setup();await g.feed(entry,row('one',(1,2)))
    await g.callbacks[entry.entry_id]['callback']({'play-1':1,'play-2':1,'volume-1':10,'volume-2':40});await hass.async_block_till_done()
    co.audio_grouping.native.timeout=.12;writes=[]
    async def sent(event):
        writes.append(dict(event.data))
        if invalidate=='auth-aba':
            getter=co.api.get_token_dict;co.api.get_token_dict=lambda:{**getter(),'token':'other-synthetic'};co.audio_grouping.notify();co.api.get_token_dict=getter;co.audio_grouping.notify()
        elif invalidate=='group-aba':
            await g.feed(entry,row('changed',(1,3)));await g.feed(entry,row('one',(1,2)))
        elif invalidate=='disconnect':co.audio_grouping.connection_state('disconnected')
        elif invalidate=='unload':co.audio_grouping.disabled=True;co.audio_grouping.native.invalidate()
    remove=hass.bus.async_listen(SENDDOMAIN,sent)
    try:
        with pytest.raises(HomeAssistantError):await hass.services.async_call('loxone','audio_group_volume',{'volume_percent':45},target={'entity_id':ids[1]},blocking=True)
        assert writes==[{'uuid':action(1),'value':'volume/30'}]
        assert g.entities[ids[1]]._room_volume_percent==10
        assert g.entities[ids[2]]._room_volume_percent==40
    finally:remove()


@pytest.mark.parametrize('percent', [0,1,29,57,58,99,100])
async def test_explicit_integer_room_service_never_fans_out(hass, grouped_setup, percent):
    g=grouped_setup;entry,co,ids=await g.setup()
    await g.feed(entry,row('one',(1,2)),row('other',(3,4)))
    await g.callbacks[entry.entry_id]['callback']({**{f'play-{p}':1 for p in ids},**{f'volume-{p}':10*p for p in ids}})
    await hass.async_block_till_done()
    assert hass.services.has_service('loxone','audio_room_volume'), 'Raw room volume needs a distinct typed service before public group scope changes'
    writes=[]
    async def sent(event):
        writes.append(dict(event.data))
        player=next(p for p in ids if action(p)==event.data['uuid'])
        await g.callbacks[entry.entry_id]['callback']({f'volume-{player}':int(event.data['value'].split('/')[1])})
    remove=hass.bus.async_listen(SENDDOMAIN,sent)
    try:
        await hass.services.async_call('loxone','audio_room_volume',{'volume_percent':percent},target={'entity_id':ids[1]},blocking=True)
        await hass.async_block_till_done()
        assert writes==[{'uuid':action(1),'value':f'volume/{percent}'}]
        assert hass.states.get(ids[2]).attributes['loxone_room_volume_level']==.2
    finally:remove()


async def test_native_public_group_volume_is_additive_clamped_and_feedback_confirmed(hass, grouped_setup):
    g=grouped_setup
    entry,co,ids=await g.setup()
    await g.feed(entry,row('one',(1,2)),row('other',(3,4)))
    await g.callbacks[entry.entry_id]['callback']({**{f'play-{p}':1 for p in ids},'volume-1':10,'volume-2':40,'volume-3':90,'volume-4':100})
    await hass.async_block_till_done()
    writes=[]
    async def sent(event):
        writes.append(dict(event.data))
        player=next(p for p in ids if action(p)==event.data['uuid'])
        await g.callbacks[entry.entry_id]['callback']({f'volume-{player}':int(event.data['value'].split('/')[1])})
    remove=hass.bus.async_listen(SENDDOMAIN,sent)
    try:
        await hass.services.async_call('loxone','audio_group_volume',{'volume_percent':45},target={'entity_id':ids[2]},blocking=True)
        await hass.async_block_till_done()
        assert writes==[{'uuid':action(1),'value':'volume/30'},{'uuid':action(2),'value':'volume/60'}], 'Explicit group setter must shift every member, never equalize or only change clicked room'
        assert hass.states.get(ids[1]).attributes['loxone_group_volume_level']==.45
        assert hass.states.get(ids[1]).attributes['loxone_room_volume_level']==.3
        assert hass.states.get(ids[3]).attributes['loxone_room_volume_level']==.9
    finally:
        remove()

async def test_public_group_mean_and_explicit_raw_room_level(hass, grouped_setup):
    g=grouped_setup
    entry,co,ids=await g.setup()
    await g.feed(entry,row('one',(1,2)),row('other',(3,4)))
    await g.callbacks[entry.entry_id]['callback']({'play-1':1,'play-2':1,'play-3':1,'play-4':1,'volume-1':10,'volume-2':40,'volume-3':90,'volume-4':100})
    await hass.async_block_till_done()
    assert hass.states.get(ids[1]).attributes['loxone_group_volume_level']==.25, 'Explicit group slider must expose all-member mean, not leader volume'
    assert hass.states.get(ids[2]).attributes['loxone_group_volume_level']==.25
    assert hass.states.get(ids[1]).attributes['loxone_room_volume_level']==.1
    assert hass.states.get(ids[2]).attributes['loxone_room_volume_level']==.4
    assert hass.states.get(ids[3]).attributes['loxone_group_volume_level']==.95
    assert hass.states.get(ids[1]).attributes['loxone_group_control']['version']==3
