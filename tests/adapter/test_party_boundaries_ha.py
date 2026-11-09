"""Party-scale fail-closed boundaries, synthetic current-Core owning services."""
import asyncio
import json
import pytest
from homeassistant.exceptions import HomeAssistantError
from custom_components.loxone.pyloxone_api import audioserver as wire
from test_audio_grouping_ha import grouped_setup, audio_setup, structure, row, payload
from test_audioserver_playback import SyntheticAudioSocket, rsa_key
from test_precommand_parent_qualification_v2_ha import native_row


@pytest.mark.parametrize('phase,change',[
 ('status-auth','token-aba'),('status-reply','content'),('status-close','membership-aba'),
 ('status-auth','cancel'),('status-reply','cancel'),('status-close','cancel'),
 ('group-auth','token-aba'),('group-reply','content'),('group-close','membership-aba'),
 ('group-auth','cancel'),('group-reply','cancel'),('group-close','cancel'),
 ('status-reply','stall'),('status-reply','removed'),('status-reply','intent'),
])
async def test_party_revocation_is_latched_across_preparation_send_and_cleanup(
 hass,grouped_setup,audio_setup,monkeypatch,rsa_key,phase,change
):
 g=grouped_setup;g.source.clear();g.source.update(structure(count=12))
 entry,co,_=await g.setup();ids={e._audio_player_id:i for i,e in g.entities.items()}
 await g.feed(entry,row('party',tuple(range(1,13))))
 await g.callbacks[entry.entry_id]['callback']({f'play-{p}':1 for p in ids})
 for p in ids:
  done=asyncio.get_running_loop().create_future()
  remove=co.audio_metadata.async_add_listener(p,lambda:done.done() or done.set_result(None))
  try:
   audio_setup.queues[0].put_nowait(json.dumps({'audio_event':[native_row(p,None if p==12 else 'parent-A')]}))
   await asyncio.wait_for(done,2)
  finally:remove()
 co.audio_commands._credentials=lambda:('synthetic-user','synthetic-active-token')
 routes=[];sockets=[];triggered=False
 async def perturb():
  nonlocal triggered
  if triggered:return
  triggered=True
  if change=='token-aba':
   getter=co.api.get_token_dict
   co.api.get_token_dict=lambda:{**getter(),'token':'synthetic-other'};co.audio_grouping.notify()
   co.api.get_token_dict=getter;co.audio_grouping.notify()
  elif change=='membership-aba':
   co.audio_grouping.native.observe(payload(row('party',tuple(range(1,12)))))
   co.audio_grouping.native.observe(payload(row('party',tuple(range(1,13)))))
  elif change=='content':
   done=asyncio.get_running_loop().create_future()
   remove=co.audio_metadata.async_add_listener(12,lambda:done.done() or done.set_result(None))
   try:
    audio_setup.queues[0].put_nowait(json.dumps({'audio_event':[native_row(12,'changed-parent')]}))
    await asyncio.wait_for(done,2)
   finally:remove()
  elif change=='removed':g.entities[ids[12]]._audio_removed=True
  elif change=='intent':g.entities[ids[12]]._source_generation+=1
  elif change=='cancel':
   asyncio.current_task().cancel();await asyncio.sleep(0)
  elif change=='stall':
   # A single stalled status must expire at its own bound, not12 times it.
   await asyncio.Future()
 class Socket(SyntheticAudioSocket):
  kind='status'
  async def send(self,message):
   if message.startswith('secure/authenticate/'):
    self.kind='group' if len(sockets)>1 else 'status'
    await super().send(message)
    if phase==self.kind+'-auth':await perturb()
    return
   if message.startswith('audio/') and message!='audio/cfg/getkey/full':
    self.sent.append(message);routes.append(message)
    if message.endswith('/status'):
     if phase=='status-reply':await perturb()
     self.queue.put_nowait(json.dumps({'status_result':[native_row(12,'parent-A')]}))
    else:
     assert message=='audio/grouped/play/'+','.join(map(str,range(1,13)))
     if phase=='group-reply':await perturb()
     self.queue.put_nowait(json.dumps({'grouped_play_result':{'players':[{'playerid':p,'mode':'play'} for p in range(1,13)]}}))
    return
   await super().send(message)
  async def __aexit__(self,*args):
   try:
    if phase==self.kind+'-close':await perturb()
   finally:await super().__aexit__(*args)
 def connect(*a,**kw):s=Socket(rsa_key);sockets.append(s);return s
 monkeypatch.setattr(wire,'connect',connect)
 if change=='stall':co.audio_grouping.native.timeout=.15
 try:
  with pytest.raises((HomeAssistantError,asyncio.CancelledError)):
   await asyncio.wait_for(hass.services.async_call('media_player','media_play',{'entity_id':ids[1]},blocking=True),3)
  assert triggered
  grouped=[r for r in routes if r.startswith('audio/grouped/')]
  assert grouped==(['audio/grouped/play/'+','.join(map(str,range(1,13)))] if phase in ('group-reply','group-close') else [])
  assert routes.count('audio/12/status')<=1
  assert all(s.closed for s in sockets) and co.audio_commands._socket is None
  assert not co.audio_grouping.native._scope and not co.audio_grouping.native._requests
  assert not co.audio_grouping.native._lock.locked() and not co.audio_commands._lock.locked()
  assert all(not e._transport_tasks for e in g.entities.values())
  assert not co.audio_grouping.native.uncertain
  co.api.send_websocket_command.assert_not_awaited()
 finally:
  # Restore only synthetic fixture eligibility for ordinary HA teardown.
  g.entities[ids[12]]._audio_removed=False
