"""F01 actual native keyboard caller -> registered HA -> synthetic authenticated wire."""
import copy
import json
import os
from pathlib import Path
import pytest
from test_audio_grouping_ha import audio_setup, grouped_setup, row, action, STATE, payload
from test_audioserver_playback import SyntheticAudioSocket, rsa_key
from test_gm03_browser_states_ha import fixed_entry
from custom_components.loxone.pyloxone_api import audioserver as wire
from custom_components.loxone.const import SENDDOMAIN


def output_path(key):
    value=os.getenv(key)
    if not value:raise AssertionError('Required synthetic focus test input absent: '+key)
    return Path(value)


@pytest.mark.parametrize('scenario',['moved','handover'])
async def test_export_moved_group_focus_states(hass,grouped_setup,fixed_entry,scenario):
    g=grouped_setup;entry,co,ids=await g.setup()
    co.api.get_token_dict=lambda:{'token':'synthetic-active-token','valid_until':9999999999}
    co.audio_commands._credentials=lambda:('synthetic-user','synthetic-active-token')
    await g.feed(entry,row('one',(1,2)),row('outside',(3,4)))
    await g.feed(entry,*( [row('one',(2,5)),row('outside',(1,3,4))] if scenario=='moved' else [row('one',(2,5,1)),row('outside',(3,4))]))
    await g.callbacks[entry.entry_id]['callback']({**{f'play-{p}':1 for p in ids},**{f'volume-{p}':v for p,v in zip(ids,[10,40,60,90,20,30])}})
    await hass.async_block_till_done()
    states={i:hass.states.get(i).as_dict() for i in ids.values()}
    assert states[ids[2]]['attributes']['group_members']==([ids[2],ids[5]] if scenario=='moved' else [ids[2],ids[5],ids[1]])
    assert states[ids[1]]['attributes']['loxone_group_control']['group_id']==('outside' if scenario=='moved' else 'one')
    output_path('GM03_FOCUS_EXPORT').with_name(scenario+'-owning-states.json').write_text(json.dumps(states,indent=2,default=str)+'\n')


@pytest.mark.parametrize('request_index',range(7))
async def test_replay_exact_keyboard_focus_requests(hass,grouped_setup,fixed_entry,monkeypatch,rsa_key,request_index):
    requests=json.loads(output_path('GM03_FOCUS_REQUESTS').read_text())
    assert [r['label'] for r in requests]==['outside-destroy-unrelated','overview-remove-one','overview-remove-outside','grey-remove-outside','group-volume-handover','group-play-handover','add-picker-moved-leader']
    g=grouped_setup;entry,co,ids=await g.setup();rows=[];commands=[];sockets=[];writes=[];outcomes=[]
    co.api.get_token_dict=lambda:{'token':'synthetic-active-token','valid_until':9999999999}
    co.audio_commands._credentials=lambda:('synthetic-user','synthetic-active-token')
    class Socket(SyntheticAudioSocket):
        async def send(self,message):
            if message.startswith('audio/cfg/dgroup/update/'):
                self.sent.append(message);commands.append(message);bits=message.split('/');gid=bits[4]
                players=tuple(int(p) for p in bits[5].split(',')) if len(bits)>5 else ()
                rows[:]=[r for r in rows if r['group']!=gid]
                if players:rows.append(row(gid,players))
                self.queue.put_nowait(json.dumps({'dgroup_update_result':{'id':gid}}))
                await g.callbacks[entry.entry_id]['callback']({STATE:payload(*rows)});return
            if message.startswith('audio/grouped/play/'):
                self.sent.append(message);commands.append(message);players=message.rsplit('/',1)[1]
                self.queue.put_nowait(json.dumps({'grouped_play_result':{'players':[{'playerid':int(p),'mode':'play'} for p in players.split(',')]}}));return
            await super().send(message)
    def connect(*a,**k):
        s=Socket(rsa_key);sockets.append(s);return s
    monkeypatch.setattr(wire,'connect',connect)
    async def sent(event):
        writes.append(dict(event.data));p=next(p for p in ids if action(p)==event.data['uuid'])
        await g.callbacks[entry.entry_id]['callback']({f'volume-{p}':int(event.data['value'].split('/')[1])})
    remove=hass.bus.async_listen(SENDDOMAIN,sent)
    try:
        for request in [requests[request_index]]:
            if 'handover' in request['label'] or request['label']=='add-picker-moved-leader':
                await g.feed(entry,row('one',(1,2)),row('outside',(3,4)))
            before=request['states'];groups={}
            for state in before.values():
                d=state['attributes'].get('loxone_group_control')
                if d and d['group_id']:groups[d['group_id']]=tuple(next(p for p in ids if ids[p]==i) for i in d['members'])
            rows[:]=[row(gid,groups[gid]) for gid in sorted(groups)]
            await g.feed(entry,*rows)
            await g.callbacks[entry.entry_id]['callback']({**{f'play-{p}':1 for p in ids},**{f'volume-{p}':round(before[i]['attributes']['loxone_room_volume_level']*100) for p,i in ids.items()}})
            await hass.async_block_till_done()
            for i in ids.values():
                actual=hass.states.get(i).attributes;expected=before[i]['attributes']
                assert actual['loxone_group_control']==expected['loxone_group_control']
                assert actual['group_members']==expected['group_members']
                assert actual['loxone_room_volume_level']==expected['loxone_room_volume_level']
                assert actual['volume_level']==expected['volume_level']
            count=len(commands);start=len(writes)
            await hass.services.async_call(request['domain'],request['service'],copy.deepcopy(request['data']),target=copy.deepcopy(request['target']),blocking=True)
            await hass.async_block_till_done()
            label=request['label']
            expected_commands={
                'outside-destroy-unrelated':['audio/cfg/dgroup/update/outside'],
                'overview-remove-one':['audio/cfg/dgroup/update/one'],
                'overview-remove-outside':['audio/cfg/dgroup/update/outside'],
                'grey-remove-outside':['audio/cfg/dgroup/update/outside'],
                'group-volume-handover':[],
                'group-play-handover':['audio/grouped/play/2,5,1'],
                'add-picker-moved-leader':['audio/cfg/dgroup/update/one/2,5,6'],
            }
            assert commands[count:]==expected_commands[label]
            if label=='outside-destroy-unrelated':
                assert hass.states.get(ids[1]).attributes['group_members']==[ids[1],ids[2]]
                assert hass.states.get(ids[2]).attributes['group_members']==[ids[1],ids[2]]
                for p in (3,4):assert hass.states.get(ids[p]).attributes['group_members']==[ids[p]]
            if label=='add-picker-moved-leader':
                assert hass.states.get(ids[2]).attributes['group_members']==[ids[2],ids[5],ids[6]]
                assert hass.states.get(ids[1]).attributes['group_members']==[ids[1],ids[3],ids[4]]
            if label=='group-volume-handover':
                assert len(writes[start:])==3
                assert {w['uuid'] for w in writes[start:]}=={action(p) for p in (2,5,1)}
                assert all(hass.states.get(ids[p]).attributes['volume_level']==request['data']['volume_level'] for p in (2,5,1))
            assert not co.audio_grouping.native._scope and not co.audio_grouping.native._requests and not co.audio_grouping.native._tasks
            outcomes.append({'label':label,'commands':commands[count:],'volume_writes':writes[start:],'members':{i:hass.states.get(i).attributes['group_members'] for i in ids.values()}})
        if request_index==4:assert sockets==[],'Group volume uses the existing Miniserver bus, not an audio command socket'
        else:assert sockets and all(s.closed and any(m.startswith('secure/authenticate/') for m in s.sent) for s in sockets)
        dest=output_path('GM03_FOCUS_WIRES');dest.with_name(dest.stem+'-'+str(request_index)+dest.suffix).write_text(json.dumps({'status':'PASS','request_index':request_index,'outcomes':outcomes,'transport':'existing Miniserver bus' if request_index==4 else 'authenticated synthetic audio socket','sockets_closed':True},indent=2)+'\n')
    finally:
        remove();await co.audio_commands.async_close()
