"""GM03 explicit management at actual registered HA entry/service boundary."""
import pytest
from homeassistant.exceptions import HomeAssistantError
from test_audio_grouping_ha import grouped_setup as grouped_setup
from test_audio_grouping_ha import audio_setup as audio_setup
from test_audio_grouping_ha import row


async def test_immediate_free_add_explicit_leader_removal_then_singleton_dissolve(hass, grouped_setup):
    g=grouped_setup;entry,co,ids=await g.setup();g.wire(entry,co)
    await g.feed(entry,row('one',(1,2)),row('outside',(3,4)))
    async def manage(p,action,members=(),group='one'):
        revision=hass.states.get(ids[p]).attributes['loxone_group_control']['revision']
        await hass.services.async_call('loxone','audio_group_manage',{'action':action,'revision':revision,'group_id':group,'members':[ids[m] for m in members]},target={'entity_id':ids[p]},blocking=True)
    await manage(2,'add',(5,))
    assert g.calls==['audio/cfg/dgroup/update/one/1,2,5']
    await manage(1,'remove')
    assert g.calls[-1]=='audio/cfg/dgroup/update/one/2,5'
    assert hass.states.get(ids[1]).attributes['group_members']==[ids[1]]
    await manage(5,'remove')
    assert g.calls[-1]=='audio/cfg/dgroup/update/one'
    assert hass.states.get(ids[2]).attributes['group_members']==[ids[2]]
    assert hass.states.get(ids[5]).attributes['group_members']==[ids[5]]
    assert hass.states.get(ids[3]).attributes['group_members']==[ids[3],ids[4]]


@pytest.mark.parametrize('kind',['steal-create','steal-add','single-create','stale','wrong-group','aba'])
async def test_manager_rejects_nonfree_or_stale_exact_generation_without_write(hass,grouped_setup,kind):
    g=grouped_setup;entry,co,ids=await g.setup();g.wire(entry,co)
    await g.feed(entry,row('one',(1,2)),row('outside',(3,4)))
    p=5 if kind in ('steal-create','single-create') else 1
    d=hass.states.get(ids[p]).attributes['loxone_group_control']
    data={'action':'add','revision':d['revision'],'group_id':'one','members':[ids[6]]}
    if kind=='steal-create':data={'action':'create','revision':d['revision'],'members':[ids[3]]}
    if kind=='steal-add':data['members']=[ids[3]]
    if kind=='single-create':data={'action':'create','revision':d['revision'],'members':[]}
    if kind=='stale':data['revision']='stale'
    if kind=='wrong-group':data={'action':'destroy','revision':d['revision'],'group_id':'outside'}
    if kind=='aba':
        await g.feed(entry,row('one',(1,6)),row('outside',(3,4)))
        await g.feed(entry,row('one',(1,2)),row('outside',(3,4)))
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call('loxone','audio_group_manage',data,target={'entity_id':ids[p]},blocking=True)
    assert g.calls==[]

async def test_create_free_pair_then_destroy_exact_group_preserves_outside(hass, grouped_setup):
    g=grouped_setup;entry,co,ids=await g.setup();g.wire(entry,co)
    await g.feed(entry,row('outside',(3,4)))
    assert hass.services.has_service('loxone','audio_group_manage'), 'Create/free-only/destroy needs a revision-checked explicit management contract'
    def revision(p):return hass.states.get(ids[p]).attributes['loxone_group_control']['revision']
    await hass.services.async_call('loxone','audio_group_manage',{'action':'create','revision':revision(1),'members':[ids[2]]},target={'entity_id':ids[1]},blocking=True)
    assert g.calls==['audio/cfg/dgroup/update/new/1,2']
    assert hass.states.get(ids[1]).attributes['group_members']==[ids[1],ids[2]]
    assert hass.states.get(ids[3]).attributes['group_members']==[ids[3],ids[4]]
    await hass.services.async_call('loxone','audio_group_manage',{'action':'destroy','revision':revision(2),'group_id':'created'},target={'entity_id':ids[2]},blocking=True)
    assert g.calls==['audio/cfg/dgroup/update/new/1,2','audio/cfg/dgroup/update/created']
    assert hass.states.get(ids[1]).attributes['group_members']==[ids[1]]
    assert hass.states.get(ids[2]).attributes['group_members']==[ids[2]]
    assert hass.states.get(ids[3]).attributes['group_members']==[ids[3],ids[4]]
