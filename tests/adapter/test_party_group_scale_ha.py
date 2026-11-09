"""Party scale: real owning HA service + native crypto, synthetic timing only."""
import asyncio
import json
import time
import pytest
from homeassistant.exceptions import HomeAssistantError
from custom_components.loxone.pyloxone_api import audioserver as wire
from test_audio_grouping_ha import grouped_setup, audio_setup, structure, row
from test_audioserver_playback import SyntheticAudioSocket, rsa_key
from test_precommand_parent_qualification_v2_ha import native_row


@pytest.mark.parametrize('count,reply_delay,close_delay', [(2,.001,0),(5,.001,0),(2,1,2),(4,1,2),(5,1,2),(12,1,2)])
async def test_party_group_play_qualifies_every_sparse_member_before_one_send(
    hass, grouped_setup, audio_setup, monkeypatch, rsa_key, count, reply_delay, close_delay, metadata_shape='sparse'
):
    g=grouped_setup;g.source.clear();g.source.update(structure(count=12))
    entry,co,_=await g.setup()
    ids={e._audio_player_id:i for i,e in g.entities.items()}
    assert len(ids)==12 and co.audio_grouping is not None
    players=tuple(range(count,0,-1))
    await g.feed(entry,row('party',players))
    callback=g.callbacks[entry.entry_id]['callback']
    await callback({**{f'play-{p}':1 for p in ids},**{f'volume-{p}':p*3 for p in ids}})
    def media(p,parent):
        return native_row(p,parent,**({'audiopath':f'tunein:station:synthetic-{p}','sourceName':'Synthetic radio account'} if metadata_shape=='mixed' and p%2 else {}))
    originals={p:('known-parent-'+str(p) if metadata_shape=='mixed' and p%3 else None) for p in players}
    needs_status=[p for p in players if originals[p] is None]
    for p in players:
        done=asyncio.get_running_loop().create_future()
        remove=co.audio_metadata.async_add_listener(p,lambda: done.done() or done.set_result(None))
        try:
            audio_setup.queues[0].put_nowait(json.dumps({'audio_event':[media(p,originals[p])]}))
            await asyncio.wait_for(done,2)
        finally:remove()
    before={p:hass.states.get(i).as_dict() for p,i in ids.items()}
    if count==12:
        import os
        from pathlib import Path
        output=os.environ.get('GM03_BROWSER_STATES')
        if output:Path(output+'.party-'+metadata_shape+'.json').write_text(json.dumps({'states':{i:hass.states.get(i).as_dict() for i in ids.values()},'target':ids[1]},default=str))
    co.audio_commands._credentials=lambda:('synthetic-user','synthetic-active-token')
    routes=[];sockets=[];authenticated=[]
    class Socket(SyntheticAudioSocket):
        async def send(self,message):
            if message.startswith('audio/') and message!='audio/cfg/getkey/full':
                self.sent.append(message);routes.append(message)
                if message.endswith('/status'):
                    p=int(message.split('/')[1]);await asyncio.sleep(reply_delay)
                    self.queue.put_nowait(json.dumps({'status_result':[media(p,'parent-'+str(p))]}))
                else:
                    assert message=='audio/grouped/play/'+','.join(map(str,players))
                    self.queue.put_nowait(json.dumps({'grouped_play_result':{'players':[{'playerid':p,'mode':'play'} for p in players]}}))
                return
            await super().send(message)
            if message.startswith('secure/authenticate/'):authenticated.append(self)
        async def __aexit__(self,*args):
            try:
                if any(m.endswith('/status') for m in self.sent):await asyncio.sleep(close_delay)
            finally:await super().__aexit__(*args)
    def connect(*a,**kw):
        s=Socket(rsa_key);sockets.append(s);return s
    monkeypatch.setattr(wire,'connect',connect)
    start=time.monotonic()
    try:
        await hass.services.async_call('media_player','media_play',{'entity_id':ids[1]},blocking=True)
    finally:
        print(json.dumps({'members':count,'elapsed':time.monotonic()-start,'routes':routes,'authenticated':len(authenticated),'closed':[s.closed for s in sockets]}))
    assert routes==[f'audio/{p}/status' for p in needs_status]+['audio/grouped/play/'+','.join(map(str,players))]
    assert len(authenticated)==len(needs_status)+1 and all(s.closed for s in sockets)
    assert co.audio_commands._socket is None and not co.audio_commands._lock.locked()
    assert not co.audio_grouping.native._scope and not co.audio_grouping.native._requests
    assert all(not e._transport_tasks for e in g.entities.values())
    assert co.audio_grouping.native.snapshot.groups[0].players==players
    co.api.send_websocket_command.assert_not_awaited()
    # No optimistic feedback or invented content enrichment.
    assert {p:hass.states.get(i).state for p,i in ids.items()}=={p:s['state'] for p,s in before.items()}
    assert all(co.audio_metadata.get(p).parent_id == originals[p] for p in players)
    await callback({f'play-{p}':2 for p in players});await hass.async_block_till_done()
    assert all(hass.states.get(ids[p]).state=='playing' for p in players)
    assert all(hass.states.get(ids[p]).state==before[p]['state'] for p in ids if p not in players)


async def test_party_heterogeneous_known_and_sparse_parent_metadata(hass,grouped_setup,audio_setup,monkeypatch,rsa_key):
    await test_party_group_play_qualifies_every_sparse_member_before_one_send(hass,grouped_setup,audio_setup,monkeypatch,rsa_key,12,.001,0,metadata_shape="mixed")
