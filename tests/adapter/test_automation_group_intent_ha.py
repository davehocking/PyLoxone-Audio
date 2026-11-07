"""Automation service through real HA with confirmed synthetic native grouping."""
import asyncio
from pathlib import Path
import yaml
import pytest
from homeassistant.exceptions import HomeAssistantError
from custom_components.loxone import media_player
from custom_components.loxone.pyloxone_api.audioserver import AudioCommandError
from test_audio_grouping_ha import grouped_setup,audio_setup,row,payload,STATE


async def manage(hass,ids,target,action='create',members=(2,),**extra):
    await hass.services.async_call('loxone','audio_group_manage',{'entity_id':ids[target],'action':action,'members':[ids[p]for p in members],**extra},blocking=True)


async def test_actual_action_creates_without_manual_native_tokens_and_is_idempotent(hass,grouped_setup):
    g=grouped_setup;entry,co,ids=await g.setup();g.wire(entry,co);await g.feed(entry)
    await manage(hass,ids,1)
    assert g.calls==['audio/cfg/dgroup/update/new/1,2']
    assert co.audio_grouping.native.snapshot.groups[0].players==(1,2)
    await manage(hass,ids,1)
    assert len(g.calls)==1


async def test_actual_action_override_extracts_selected_follower_leader_and_preserves_both_remainders(hass,grouped_setup):
    g=grouped_setup;entry,co,ids=await g.setup();g.wire(entry,co)
    await g.feed(entry,row('old',(2,1,3)),row('other',(4,5,6)))
    await manage(hass,ids,1,members=(4,),override_existing_membership=True)
    assert g.calls==['audio/cfg/dgroup/update/old/2,3','audio/cfg/dgroup/update/other/5,6','audio/cfg/dgroup/update/new/1,4']
    groups={r.group_id:r.players for r in co.audio_grouping.native.snapshot.groups}
    assert groups=={'old':(2,3),'other':(5,6),'created':(1,4)}


async def test_override_default_off_refuses_occupied_rooms_before_writes(hass,grouped_setup):
    g=grouped_setup;entry,co,ids=await g.setup();g.wire(entry,co);await g.feed(entry,row('old',(2,3)))
    with pytest.raises(HomeAssistantError)as conflict:await manage(hass,ids,1)
    assert 'Override any existing group membership'in str(conflict.value)
    assert g.calls==[]


async def test_explicit_ui_revision_remains_supported_and_stale_token_is_not_replaced(hass,grouped_setup):
    g=grouped_setup;entry,co,ids=await g.setup();g.wire(entry,co);await g.feed(entry)
    with pytest.raises(HomeAssistantError):await manage(hass,ids,1,revision='obsolete-literal')
    assert g.calls==[]
    revision=co.audio_grouping.control_descriptor(1)['revision']
    await manage(hass,ids,1,revision=revision)
    assert g.calls==['audio/cfg/dgroup/update/new/1,2']


async def test_edit_action_resolves_real_existing_group_id_internally(hass,grouped_setup):
    g=grouped_setup;entry,co,ids=await g.setup();g.wire(entry,co);await g.feed(entry,row('actual-native-id',(2,1)))
    await manage(hass,ids,1,action='add',members=(3,))
    assert g.calls==['audio/cfg/dgroup/update/actual-native-id/2,1,3']


async def test_queued_auto_revision_does_not_rebase_and_steal_newly_changed_membership(hass,grouped_setup):
    g=grouped_setup;entry,co,ids=await g.setup();g.wire(entry,co);await g.feed(entry)
    native=co.audio_grouping.native
    await native._lock.acquire();task=asyncio.create_task(manage(hass,ids,1,override_existing_membership=True))
    try:
        for _ in range(30):
            if native._requests:break
            await asyncio.sleep(0)
        assert native._requests
        await g.callbacks[entry.entry_id]['callback']({STATE:payload(row('external',(2,3)))})
    finally:
        native._lock.release()
        result=await asyncio.wait_for(asyncio.gather(task,return_exceptions=True),3)
    assert isinstance(result[0],HomeAssistantError)
    assert g.calls==[]


async def test_partial_native_transfer_failure_is_not_replayed_or_rolled_back(hass,grouped_setup,monkeypatch):
    g=grouped_setup;entry,co,ids=await g.setup();g.wire(entry,co)
    await g.feed(entry,row('old',(2,1,3)),row('other',(4,5,6)))
    original=co.audio_commands._async_request;attempts=[]
    async def request(command,*args,**kwargs):
        attempts.append(command)
        if len(attempts)==2:raise AudioCommandError('Synthetic native refusal')
        return await original(command,*args,**kwargs)
    monkeypatch.setattr(co.audio_commands,'_async_request',request)
    with pytest.raises(HomeAssistantError):await manage(hass,ids,1,members=(4,),override_existing_membership=True)
    assert attempts==['audio/cfg/dgroup/update/old/2,3','audio/cfg/dgroup/update/other/5,6']
    assert g.calls==['audio/cfg/dgroup/update/old/2,3']


async def test_action_form_hides_native_tokens_and_offers_default_off_override():
    fields=yaml.safe_load(Path(media_player.__file__).with_name('services.yaml').read_text())['audio_group_manage']['fields']
    assert 'revision'not in fields and'group_id'not in fields
    checkbox=fields['override_existing_membership']
    assert checkbox['default']is False and'boolean'in checkbox['selector']
    assert fields['members']['selector']['entity']['integration']=='loxone'
