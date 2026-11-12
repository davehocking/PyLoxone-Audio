"""Staged supplemental actual-owning service trace for the unchanged compiled UI."""
import asyncio,json
import pytest
from custom_components.loxone.const import SENDDOMAIN
from custom_components.loxone.pyloxone_api import audioserver as wire
from homeassistant.exceptions import HomeAssistantError
from test_audio_grouping_ha import STATE,action,row,payload
from test_audio_grouping_ha import grouped_setup as grouped_setup
from test_audio_grouping_ha import audio_setup as audio_setup
from test_audioserver_playback import SyntheticAudioSocket
from test_audioserver_playback import rsa_key as rsa_key
from test_stage2_modes_ha import output


async def test_current_compiled_ui_owner_failure_journey_registered_wire(hass,grouped_setup,audio_setup,monkeypatch,rsa_key):
    g=grouped_setup;entry,co,ids=await g.setup()
    groups={'pair':(2,1),'untouched':(3,4)}
    await g.feed(entry,*(row(k,v) for k,v in groups.items()))
    callback=g.callbacks[entry.entry_id]['callback']
    await callback({**{f'play-{p}':2 for p in ids},**{f'volume-{p}':20 for p in ids},'volume-2':10,'volume-1':38})
    await hass.async_block_till_done()
    owner=co.audio_grouping
    assert owner.native.timeout==8
    sockets=[];writes=[];confirm=False
    co.audio_commands._credentials=lambda:('synthetic-user','synthetic-active-token')
    class Socket(SyntheticAudioSocket):
        async def send(self,message):
            if message.startswith('audio/cfg/dgroup/update/'):
                self.sent.append(message);parts=message.split('/')
                name='fresh-created' if parts[4]=='new' else parts[4]
                members=tuple(map(int,parts[5].split(','))) if len(parts)>5 else ()
                groups.pop(name,None)
                if members:groups[name]=members
                await callback({STATE:payload(*(row(k,v) for k,v in groups.items()))})
                self.queue.put_nowait(json.dumps({'dgroup_update_result':{'id':name}}))
            elif message.startswith('audio/grouped/'):
                self.sent.append(message);_,_,mode,raw=message.split('/')
                self.queue.put_nowait(json.dumps({f'grouped_{mode}_result':{'players':[{'playerid':int(p),'mode':mode} for p in raw.split(',')]}}))
            elif message.startswith('audio/') and message.rsplit('/',1)[1] in ('play','pause'):
                self.sent.append(message);self.queue.put_nowait(json.dumps({message.rsplit('/',1)[1]+'_result':True}))
            else:await super().send(message)
    def connect(*args,**kwargs):
        s=Socket(rsa_key);sockets.append(s);return s
    monkeypatch.setattr(wire,'connect',connect)
    async def sent(event):
        writes.append(dict(event.data))
        if confirm:
            p=next(p for p in ids if action(p)==event.data['uuid'])
            await callback({f'volume-{p}':int(event.data['value'].split('/')[1])})
    remove=hass.bus.async_listen(SENDDOMAIN,sent)
    states=lambda:{eid:hass.states.get(eid).as_dict() for eid in ids.values()}
    steps=[]
    async def call(label,domain,service,p,**data):
        before=states();status='success'
        try:await hass.services.async_call(domain,service,data,target={'entity_id':ids[p]},blocking=True)
        except HomeAssistantError:status='HomeAssistantError'
        await hass.async_block_till_done()
        # Service registry may add entity_id to its supplied dictionary. Store
        # the exact browser call-service body separately from HA target expansion.
        body={k:v for k,v in data.items() if k!='entity_id'}
        steps.append({'label':label,'call':{'domain':domain,'service':service,'data':body,'target':{'entity_id':ids[p]}},'result':status,'before':before,'after':states(),'volume_writes':list(writes)})
    async def manage(label,p,kind,members=(),group=None):
        data={'action':kind,'revision':owner.control_descriptor(p)['revision']}
        if members:data['members']=[ids[m] for m in members]
        if group:data['group_id']=group
        await call(label,'loxone','audio_group_manage',p,**data)
    try:
        await call('unconfirmed-group-volume','loxone','audio_group_volume',2,volume_percent=7)
        assert steps[-1]['result']=='HomeAssistantError' and writes==[{'uuid':action(2),'value':'volume/0'}]
        assert not owner.native.uncertain and len(owner.eligible())==6
        await call('group-pause','media_player','media_pause',2)
        await call('own-room-pause','loxone','audio_room_transport',1,action='pause')
        confirm=True
        await call('own-room-volume','loxone','audio_room_volume',1,volume_percent=21)
        await manage('add-room',2,'add',(5,),'pair')
        await manage('remove-room',5,'remove',group='pair')
        await manage('destroy-group',2,'destroy',group='pair')
        await manage('create-group',5,'create',(6,))
        await manage('remove-to-dissolve',6,'remove',group='fresh-created')
        assert all(s['result']=='success' for s in steps[1:])
        assert groups=={'untouched':(3,4)}
        assert writes==[{'uuid':action(2),'value':'volume/0'},{'uuid':action(1),'value':'volume/21'}]
        assert all(s.closed for s in sockets) and co.audio_commands._socket is None
        assert not owner.native._tasks and not owner.native._requests and not owner.native._scope
        output('owner-ui-journey.json',{'steps':steps,'native_requests':[m for s in sockets for m in s.sent if m.startswith('audio/') and m!='audio/cfg/getkey/full'],'all_sockets_closed':all(s.closed for s in sockets),'physical_efficacy':'UNVERIFIED','compiled_asset_rebuilt':False})
    finally:remove()
