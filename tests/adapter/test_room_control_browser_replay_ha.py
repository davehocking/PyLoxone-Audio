"""Exact new compiled-browser requests -> owning HA -> authenticated native peer.

All inputs are invented. Original dev3 oracle/trace/replay stay independent.
"""
import copy
import hashlib
import json
import os
from pathlib import Path

import pytest
from homeassistant.exceptions import HomeAssistantError
from custom_components.loxone.pyloxone_api import audioserver as wire
from test_audio_grouping_ha import STATE, action, row, payload
from test_audio_grouping_ha import grouped_setup as grouped_setup
from test_audio_grouping_ha import audio_setup as audio_setup
from test_audioserver_playback import SyntheticAudioSocket
from test_audioserver_playback import rsa_key as rsa_key
from test_room_transport_ha import catalogue_state
from gm03_trace_support import historical_source, VolumeFeedback


async def test_exact_new_compiled_browser_calls_replay_through_owning_ha(hass,grouped_setup,monkeypatch,rsa_key,tmp_path):
    root=Path(__file__).resolve().parents[2]
    trace=json.loads((root/'tests/frontend/browser-room-service-calls.json').read_text())
    for key,name in (('asset_sha256','adapters/pyloxone/frontend/dist/group-control-card-0.1.3.dev6.js'),
                     ('source_sha256',historical_source(root,trace)),
                     ('states_sha256','tests/frontend/room-ui-states.json')):
        assert hashlib.sha256((root/name).read_bytes()).hexdigest()==trace[key]
    g=grouped_setup
    entry,co,ids=await g.setup()
    numbers={entity_id:p for p,entity_id in ids.items()}
    co.audio_commands._credentials=lambda:('synthetic-user','synthetic-active-token')
    sockets=[];rows=[];reject=False
    class Socket(SyntheticAudioSocket):
        async def send(self,message):
            nonlocal rows
            if message.startswith('audio/grouped/'):
                self.sent.append(message)
                _,_,mode,participants=message.split('/')
                self.queue.put_nowait(json.dumps({f'grouped_{mode}_result':{'players':[{'playerid':int(p),'mode':mode} for p in participants.split(',')]}}))
                return
            if message.startswith('audio/cfg/dgroup/update/'):
                self.sent.append(message);parts=message.split('/');name=parts[4]
                if reject:self.queue.put_nowait(json.dumps({'dgroup_update_result':False}));return
                members=tuple(map(int,parts[5].split(','))) if len(parts)>5 else ()
                rows=[r for r in rows if r['group']!=name]
                if members:rows.append(row(name,members))
                await g.callbacks[entry.entry_id]['callback']({STATE:payload(*rows)})
                self.queue.put_nowait(json.dumps({'dgroup_update_result':{'id':name}}));return
            if message.startswith('audio/') and message!='audio/cfg/getkey/full':
                self.sent.append(message);_,player,mode=message.split('/')
                assert player.isdecimal() and mode in ('play','pause')
                self.queue.put_nowait(json.dumps({mode+'_result':False if reject else True}));return
            await super().send(message)
    def connect(*a,**k):
        s=Socket(rsa_key);sockets.append(s);return s
    monkeypatch.setattr(wire,'connect',connect)
    feedback=VolumeFeedback(hass,g,entry,ids)
    records=[]
    for index,request in enumerate(trace['calls']):
        assert request['domain'] in ('loxone','media_player')
        target=request['target']['entity_id'];assert target in numbers
        rows=[row(group['id'],tuple(numbers[i] for i in group['members'])) for group in request['groups']]
        static=tuple(numbers[i] for i in request['staticEntities'])
        rows.append(row('fixed',static,'static'))
        await g.feed(entry,*rows)
        await g.callbacks[entry.entry_id]['callback']({**{f'play-{numbers[i]}':0 if s['state']=='playing' else 1 for i,s in request['states'].items()},
                                                     **{f'volume-{numbers[i]}':round(s['attributes']['volume_level']*100) for i,s in request['states'].items()}})
        await hass.async_block_till_done()
        before=co.audio_grouping.native.snapshot.groups
        expected_volume=feedback.expected(g,co,target,request['data']['volume_level']) if request['service']=='volume_set' else None
        sources={i:(e._source_generation,e._source_feedback,e._source_target,e._source_return_rejection,copy.deepcopy(catalogue_state(e))) for i,e in g.entities.items()}
        playback={i:hass.states.get(i).state for i in ids.values()}
        co.api.send_websocket_command.reset_mock();count=len(sockets)
        reject=request['mode']=='reject'
        call=hass.services.async_call(request['domain'],request['service'],request['data'],target=request['target'],blocking=True)
        if reject:
            with pytest.raises(HomeAssistantError):await call
        else:await call
        await hass.async_block_till_done()
        messages=[m for s in sockets[count:] for m in s.sent if m.startswith('audio/') and m!='audio/cfg/getkey/full']
        service=request['service']
        if service=='volume_set':
            assert messages==[]
            assert [tuple(c.args) for c in co.api.send_websocket_command.await_args_list]==expected_volume
        else:
            co.api.send_websocket_command.assert_not_awaited()
            assert len(messages)==1
            if service=='audio_room_transport':
                assert request['domain']=='loxone' and request['data']['action'] in ('play','pause')
                assert messages==[f"audio/{numbers[target]}/{request['data']['action']}"]
            elif service in ('media_play','media_pause'):
                group=next(group for group in before if numbers[target] in group.players)
                assert messages==['audio/grouped/'+('play' if service=='media_play' else 'pause')+'/'+','.join(map(str,group.players))]
            else:
                assert service in ('join','unjoin')
                if not reject:
                    expected=tuple(numbers[i] for i in request['groups'][0]['members'])
                    expected=expected+tuple(numbers[i] for i in request['data']['group_members']) if service=='join' else tuple(p for p in expected if p!=numbers[target])
                    assert next(group for group in co.audio_grouping.native.snapshot.groups if group.group_id==request['groups'][0]['id']).players==expected
        if service in ('audio_room_transport','media_play','media_pause','volume_set'):
            assert co.audio_grouping.native.snapshot.groups==before
            for i,e in g.entities.items():
                assert (e._source_generation,e._source_feedback,e._source_target,e._source_return_rejection,catalogue_state(e))==sources[i]
                assert hass.states.get(i).state==playback[i]
        if reject:assert co.audio_grouping.native.uncertain == (service in ('join','unjoin'))
        assert any(group.group_id=='fixed' and group.players==static for group in co.audio_grouping.native.snapshot.groups)
        assert all(s.closed for s in sockets) and co.audio_commands._socket is None
        assert not co.audio_grouping.native._scope and not co.audio_grouping.native._requests and not co.audio_grouping.native._tasks
        assert all(not e._transport_tasks for e in g.entities.values())
        records.append({'index':index,'domain':request['domain'],'service':service,'target':target,'wire':messages,'expected_rejection':reject})
    assert len(records)==21
    assert sum(r['service']=='audio_room_transport' for r in records)==14
    feedback.remove()
    Path(os.environ.get('ROOM_REPLAY_RECEIPT',tmp_path/'room-replay.json')).write_text(json.dumps({'status':'PASS','asset_sha256':trace['asset_sha256'],'requests':records,'cleanup':True},indent=2)+'\n')
