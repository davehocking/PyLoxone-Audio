"""Deterministic synthetic owning HA exports AND exact emitted browser replay."""
import functools
import copy
import json
import os
from pathlib import Path
import pytest
from homeassistant.core import callback
from test_audio_grouping_ha import audio_setup as audio_setup, grouped_setup as grouped_setup, row, action
from test_audio_grouping_ha import STATE,payload
from test_audioserver_playback import SyntheticAudioSocket,rsa_key
import test_audioserver_ha as base
from custom_components.loxone.const import SENDDOMAIN
from custom_components.loxone.pyloxone_api import audioserver as wire
from test_room_transport_ha import catalogue_state
from pyloxone_audio.catalogue import CatalogueTarget, ConfiguredSource
from gm03_native_trace import native_trace
from pyloxone_audio.native import AudioZoneMetadata

@pytest.fixture
def fixed_entry(monkeypatch):
    monkeypatch.setattr(base,'MockConfigEntry',functools.partial(base.MockConfigEntry,entry_id='gm03-synthetic-fixed-entry'))

@pytest.mark.parametrize('replay_browser',[False,True],ids=['owning-export','exact-native-emissions'])
async def test_export_actual_owning_states_and_replay_exact_browser_requests(hass,grouped_setup,fixed_entry,monkeypatch,rsa_key,replay_browser):
    g=grouped_setup;entry,co,ids=await g.setup();rows=[row('one',(1,2)),row('outside',(3,4))]
    commands=[];sockets=[]
    class Socket(SyntheticAudioSocket):
        async def send(self,message):
            if not message.startswith('audio/cfg/dgroup/update/'):
                await super().send(message);return
            self.sent.append(message);commands.append(message);bits=message.split('/');gid=bits[4]
            if gid=='new':gid='created'
            players=tuple(int(x) for x in bits[5].split(',')) if len(bits)>5 else ()
            rows[:]=[r for r in rows if r['group']!=gid]
            if players:rows.append(row(gid,players))
            self.queue.put_nowait(json.dumps({'dgroup_update_result':{'id':gid}}))
            await g.callbacks[entry.entry_id]['callback']({STATE:payload(*rows)})
    def make_socket(*args,**kwargs):
        s=Socket(rsa_key);sockets.append(s);return s
    monkeypatch.setattr(wire,'connect',make_socket)
    co.api.get_token_dict=lambda:{'token':'synthetic-active-token','valid_until':9999999999}
    co.audio_commands._credentials=lambda:('synthetic-user','synthetic-active-token')
    await g.feed(entry,*rows)
    await g.callbacks[entry.entry_id]['callback']({**{f'play-{p}':1 for p in ids},**{f'volume-{p}':v for p,v in zip(ids,[10,40,60,90,20,30])}})
    await hass.async_block_till_done()
    for p,i in ids.items():
        c=g.entities[i]._radio_catalogue
        c._source_accounts=[{'id':f'synthetic-account-{p}','name':f'Synthetic account {p}'}]
        c.source_choices={'Library':CatalogueTarget('track',f'Synthetic track {p}','library',f'library:local:track:{p}',audio_path=f'library:local:track:{p}')}
        c.source_descriptors={'Library':ConfiguredSource('library')}
        c.source_sessions={ConfiguredSource('library'):AudioZoneMetadata(player_id=p,audio_path=f'library:local:track:{p}',position=17.0,duration=300.0,source='Local Library',native_mode='pause',event_idle=True,event_active=False)}
        c.previous_selected=f'synthetic-bookmark-{p}'
    preserved={i:copy.deepcopy(catalogue_state(e)) for i,e in g.entities.items()}
    exports=[];writes=[]
    def capture(label):
        exports.append({'scenario':label,'target':ids[2],'states':{i:hass.states.get(i).as_dict() for i in ids.values()}})
    async def sent(event):
        writes.append(dict(event.data));p=next(p for p in ids if action(p)==event.data['uuid'])
        await g.callbacks[entry.entry_id]['callback']({f'volume-{p}':int(event.data['value'].split('/')[1])})
    remove=hass.bus.async_listen(SENDDOMAIN,sent)
    capture('initial')
    script=[('media_player','volume_set',{'volume_level':.45},2,'group-volume'),('media_player','volume_set',{'volume_level':.55},1,'manager-group-volume'),('loxone','audio_room_volume',{'volume_percent':29},1,'room-volume'),
        ('loxone','audio_room_volume',{'volume_percent':30},1,'room-nudge'),('loxone','audio_group_manage',{'action':'create','members':[ids[6]]},5,'created'),
        ('loxone','audio_group_manage',{'action':'destroy','group_id':'outside'},3,'destroyed-outside'),
        ('loxone','audio_group_manage',{'action':'remove','group_id':'one'},1,'dissolved-pair'),
        ('loxone','audio_group_manage',{'action':'destroy','group_id':'created'},5,'empty'),
        ('loxone','audio_group_manage',{'action':'add','members':[ids[5]],'group_id':'one'},2,'added-five'),
        ('loxone','audio_group_manage',{'action':'remove','group_id':'one'},1,'removed-leader-picker'),
        ('loxone','audio_group_manage',{'action':'add','members':[ids[1]],'group_id':'one'},2,'readded-leader'),
        ('loxone','audio_group_manage',{'action':'remove','group_id':'one'},5,'removed-five'),
        ('loxone','audio_group_manage',{'action':'destroy','group_id':'one'},2,'destroyed-one')]
    replay=native_trace('workflow') if replay_browser else None
    if replay:
        script=[]
        for request in replay:
            target=(request.get('target') or request['data'])['entity_id'];p=next(p for p in ids if ids[p]==target)
            script.append((request['domain'],request['service'],request['data'],p,request['label']))
    try:
        for domain,service,data,p,label in script:
            if label=='added-five':
                rows[:]=[row('one',(1,2)),row('outside',(3,4))]
                await g.feed(entry,*rows)
                await g.callbacks[entry.entry_id]['callback']({f'volume-{p}':v for p,v in zip(ids,[10,40,60,90,20,30])})
                await hass.async_block_till_done();capture('reset')
            data=dict(data)
            if replay:
                before=next(r['states'] for r in replay if r['label']==label)
                for i in ids.values():
                    actual=hass.states.get(i).attributes
                    assert actual['group_members']==before[i]['attributes']['group_members']
                    assert actual['loxone_room_volume_level']==before[i]['attributes']['loxone_room_volume_level']
            if service=='audio_group_manage' and not replay:data['revision']=hass.states.get(ids[p]).attributes['loxone_group_control']['revision']
            target=next((r.get('target') for r in replay if r['label']==label),None) if replay else {'entity_id':ids[p]}
            await hass.services.async_call(domain,service,data,target=target,blocking=True)
            await hass.async_block_till_done();capture(label)
            assert {i:catalogue_state(e) for i,e in g.entities.items()}==preserved,'Browser management never replaces source accounts, selections or bookmarks'
            assert not co.audio_grouping.native._scope and not co.audio_grouping.native._requests and not co.audio_grouping.native._tasks
            assert all(not e._transport_tasks for e in g.entities.values())
        assert writes==[{'uuid':action(1),'value':'volume/30'},{'uuid':action(2),'value':'volume/60'}, {'uuid':action(1),'value':'volume/40'},{'uuid':action(2),'value':'volume/70'}, {'uuid':action(1),'value':'volume/29'},{'uuid':action(1),'value':'volume/30'}]
        assert commands==['audio/cfg/dgroup/update/new/5,6','audio/cfg/dgroup/update/outside','audio/cfg/dgroup/update/one','audio/cfg/dgroup/update/created','audio/cfg/dgroup/update/one/1,2,5','audio/cfg/dgroup/update/one/2,5','audio/cfg/dgroup/update/one/2,5,1','audio/cfg/dgroup/update/one/2,1','audio/cfg/dgroup/update/one']
        assert sockets and all(any(s.startswith('secure/authenticate/') for s in socket.sent) for socket in sockets)
        output=os.environ.get('GM03_BROWSER_STATES')
        if output and not replay:Path(output).write_text(json.dumps({'snapshots':exports,'volume_wires':writes,'group_wires':commands,'independently_decrypted_auth':True},indent=2,default=str)+'\n')
    finally:
        remove();await co.audio_commands.async_close()
        assert all(socket.closed for socket in sockets)
