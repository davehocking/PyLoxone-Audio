"""Real HA grouped seek; native authenticated synthetic socket only."""
import asyncio
import json

import pytest
from homeassistant.components.media_player import MediaPlayerEntityFeature as F
from homeassistant.exceptions import HomeAssistantError
from test_audio_grouping_ha import grouped_setup, row  # noqa: F401
from test_audioserver_ha import audio_setup  # noqa: F401
from test_audioserver_playback import SyntheticAudioSocket, rsa_key  # noqa: F401
from test_native_source_return_ha import library_row
from custom_components.loxone.pyloxone_api import audioserver as wire


async def track_feedback(hass, audio_setup, *rows):
    audio_setup.queues[0].put_nowait(json.dumps({'audio_event':list(rows)}))
    await hass.async_block_till_done()


@pytest.mark.parametrize('player',range(1,13))
@pytest.mark.parametrize('spotify',[False,True],ids=['library','spotify'])
async def test_group_leader_seek_uses_native_track_command_without_regrouping(
    hass, grouped_setup, audio_setup, monkeypatch, rsa_key, player, spotify
):
    g = grouped_setup
    entry, co, ids = await g.setup()
    ids={e._audio_player_id:e.entity_id for e in g.entities.values()}
    other=player%12+1
    await g.feed(entry,row('shared',(player,other)))
    original=library_row(playerid=player)
    if spotify:original.update(audiopath='spotify:track:synthetic-seek',parent={'id':'spotify:playlist:synthetic'},sourceName='Synthetic owner')
    await track_feedback(hass,audio_setup,original,{**original,'playerid':other})
    leader,follower=g.entities[ids[player]],g.entities[ids[other]]
    assert leader.supported_features & F.SEEK
    assert not follower.supported_features & F.SEEK
    commands, writes = leader._audio_commands, []
    commands._credentials = lambda: ('synthetic-user','synthetic-active-token')
    commands._timeout = 1

    install_seek_socket(monkeypatch, rsa_key, audio_setup, commands, writes, original=original)
    await hass.services.async_call('media_player','media_seek',
        {'entity_id':ids[player],'seek_position':31},blocking=True)
    assert len(writes)==1 and writes[0].startswith(f'audio/{player}/position/')
    assert float(writes[0].rsplit('/',1)[1])==31
    assert leader.media_position == 31.25
    assert tuple(co.audio_grouping.native.snapshot.groups[0].players)==(player,other)
    assert g.calls == []
    before=len(writes)
    with pytest.raises(HomeAssistantError):
        await follower.async_media_seek(31)
    assert len(writes)==before


def install_seek_socket(monkeypatch, rsa_key, audio_setup, commands, writes, *, gate=None, original=None):
    commands._credentials = lambda: ('synthetic-user','synthetic-active-token')
    commands._timeout = 1
    original=original or library_row(playerid=2)
    class Socket(SyntheticAudioSocket):
        async def send(self, message):
            if message.startswith('audio/') and not message.startswith('audio/cfg/'):
                self.sent.append(message)
                writes.append(message)
                assert '/position/' in message
                position = float(message.rsplit('/',1)[1])
                self.queue.put_nowait(json.dumps({'position_result':[{'position':position}]}))
                asyncio.get_running_loop().call_later(.01, audio_setup.queues[0].put_nowait,
                    json.dumps({'audio_event':[{**original,'time':position+.25}]}))
                return
            await super().send(message)
            if message.startswith('secure/authenticate/') and gate:
                gate[0].set()
                await gate[1].wait()

    monkeypatch.setattr(wire,'connect',lambda *_a,**_kw:Socket(rsa_key))


@pytest.mark.parametrize('restore_token',[False,True],ids=['auth-change','auth-ABA'])
async def test_group_seek_keeps_initiating_auth_context_through_native_authentication(
    hass,grouped_setup,audio_setup,monkeypatch,rsa_key,restore_token
):
    g=grouped_setup
    entry,co,ids=await g.setup()
    await g.feed(entry,row('shared',(2,1)))
    await track_feedback(hass,audio_setup,library_row(playerid=2))
    entity=g.entities[ids[2]]
    entered,release=asyncio.Event(),asyncio.Event()
    writes=[]
    install_seek_socket(monkeypatch,rsa_key,audio_setup,entity._audio_commands,writes,gate=(entered,release))
    before=set(co.audio_grouping.native._requests)
    token=co.api.get_token_dict
    task=asyncio.create_task(hass.services.async_call('media_player','media_seek',
        {'entity_id':ids[2],'seek_position':31},blocking=True))
    try:
        await asyncio.wait_for(entered.wait(),3)
        co.api.get_token_dict=lambda:{**token(),'token':'different-synthetic-context'}
        co.audio_grouping.notify()
        if restore_token:
            co.api.get_token_dict=token
            co.audio_grouping.notify()
        release.set()
        with pytest.raises(HomeAssistantError):
            await asyncio.wait_for(task,4)
    finally:
        release.set()
        if not task.done():task.cancel()
        await asyncio.gather(task,return_exceptions=True)
    assert writes == []
    assert entity.media_position==45
    assert entity._source_context_guard is None
    assert set(co.audio_grouping.native._requests)==before
    assert tuple(co.audio_grouping.native.snapshot.groups[0].players)==(2,1)
    assert g.calls==[]


@pytest.fixture(autouse=True)
def twelve_room_structure(monkeypatch):
    import test_audio_grouping_ha as fixture
    original=fixture.structure
    monkeypatch.setattr(fixture,'structure',lambda:original(count=12))


@pytest.mark.parametrize('refusal',['static','uncertain','busy','missing-member','disabled-member'])
async def test_group_seek_refuses_unqualified_native_membership(hass,grouped_setup,audio_setup,refusal):
    from homeassistant.helpers import entity_registry as er
    g=grouped_setup;entry,co,ids=await g.setup()
    await g.feed(entry,row('shared',(2,1),kind='static' if refusal=='static' else 'dynamic'))
    await track_feedback(hass,audio_setup,library_row(playerid=2))
    if refusal=='uncertain':co.audio_grouping.native.uncertain=True
    if refusal=='busy':co.audio_grouping.native._scope=frozenset({1,2})
    if refusal=='missing-member':co.audio_grouping.entities.pop(1)
    if refusal=='disabled-member':er.async_get(hass).async_update_entity(ids[1],disabled_by=er.RegistryEntryDisabler.USER)
    entity=g.entities[ids[2]]
    assert not entity.supported_features&F.SEEK
    with pytest.raises(HomeAssistantError):await entity.async_media_seek(31)
    assert g.calls==[]


@pytest.mark.parametrize('capability',[None,0,1])
async def test_group_seek_requires_native_seek_capability(hass,grouped_setup,audio_setup,capability):
    g=grouped_setup;entry,co,ids=await g.setup()
    await g.feed(entry,row('shared',(2,1)))
    value=library_row(playerid=2,pbr=capability)
    if capability is None:value.pop('pbr')
    await track_feedback(hass,audio_setup,value)
    entity=g.entities[ids[2]]
    assert not entity.supported_features&F.SEEK
    with pytest.raises(HomeAssistantError):await entity.async_media_seek(31)
    assert g.calls==[]


async def test_export_grouped_seek_native_fixture(hass,grouped_setup,audio_setup):
    import os
    from pathlib import Path
    g=grouped_setup;entry,co,_=await g.setup()
    ids={e._audio_player_id:e.entity_id for e in g.entities.values()}
    await track_feedback(hass,audio_setup,*(library_row(playerid=p)for p in ids))
    snapshots=[]
    for label,groups in [('initial',[row('shared',(2,1)),row('other',(3,4))]),
        ('changed-leader',[row('shared',(3,1)),row('other',(2,4))]),
        ('restored-leader',[row('shared',(2,1)),row('other',(3,4))]),
        ('became-leader',[row('shared',(1,2)),row('other',(3,4))]),
        ('independent',[row('other',(3,4))])]:
        await g.feed(entry,*groups)
        await g.callbacks[entry.entry_id]['callback']({**{f'play-{p}':1 for p in ids},**{f'volume-{p}':10 for p in ids}})
        await hass.async_block_till_done()
        snapshots.append({'scenario':label,'target':ids[1],'states':{eid:hass.states.get(eid).as_dict()for eid in ids.values()}})
    assert g.calls==[]
    output=os.environ.get('GM03_BROWSER_STATES')
    if output:Path(output).write_text(json.dumps({'snapshots':snapshots,'display_registry':{'entities':[{'ei':eid,'pl':'loxone','lb':[]}for eid in ids.values()],'entity_categories':{}},'device_registry':[],'provenance':'Real Core11/native adapter;12invented rooms/track/auth/socket; no household data'},default=str,indent=2))
