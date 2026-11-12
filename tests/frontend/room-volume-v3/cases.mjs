// Real compiled native HA app, fresh direct entry and separate volume contract.
import {dialogState,waitGrouping,closeGrouping} from '../r13/native-utils.mjs';
export async function run(ctx){
 const {page,assert,results,services,nativeCalls,publishNative,snapshot,snapshots,mode}=ctx;
 const states=structuredClone(snapshot.states),follower=snapshot.target,leader=states[follower].attributes.group_members[0];
 const entity=mode.includes('follower')||mode==='shortcut'?follower:leader;
 const cross=mode.startsWith('cross'),expectedCustom=!cross;
 await publishNative(states);
 const open=async id=>{
  await page.evaluate(id=>document.querySelector('home-assistant').dispatchEvent(new CustomEvent('hass-more-info',{detail:{entityId:id},bubbles:true,composed:true})),id);
  await page.waitForFunction(id=>{function walk(r){for(const e of r.querySelectorAll('*')){if(e.localName==='more-info-media_player'&&e.stateObj?.entity_id===id&&e.shadowRoot?.querySelector('#grouping-button'))return true;if(e.shadowRoot&&walk(e.shadowRoot))return true;}return false;}return walk(document);},id);
 };
 await open(entity);
 const more=page.locator('more-info-media_player');
 if(mode.startsWith('native-volume')){
  const slider=more.locator('ha-slider.volume-slider');
  assert.equal(await slider.evaluate(s=>s.value),Math.round(states[entity].attributes.loxone_room_volume_level*100));
  await slider.evaluate(s=>{s.value=65;s.dispatchEvent(new Event('change',{bubbles:true,composed:true}));});
  for(let i=0;i<200&&services.length!==1;i++)await new Promise(r=>setTimeout(r,10));
  assert.equal(services.length,1);const call=nativeCalls[0];
  assert.equal(call.domain,'media_player');assert.equal(call.service,'volume_set');
  assert.deepEqual(call.data,{entity_id:entity,volume_level:.65});
  results.push({id:mode,raw:states[entity].attributes.loxone_room_volume_level,call});return;
 }
 if(mode==='direct-follower'){
  for(const action of ['shuffle_set','repeat_set'])assert.equal(await more.locator(`[action=${action}]`).isVisible(),true,action);
  assert.equal(await more.locator('[data-loxone-media-leader]').isVisible(),true);
  results.push({id:'idle-follower-rendered-leader-shuffle-repeat',shuffle:states[entity].attributes.shuffle,repeat:states[entity].attributes.repeat});
 }
 if(mode==='shortcut'){
  const link=page.locator('more-info-media_player').locator('[data-loxone-media-leader]');
  await link.waitFor({state:'visible'});assert.match(await link.textContent(),/Media controls on/);
  await link.click();await page.waitForFunction(leader=>{function walk(r){for(const e of r.querySelectorAll('*')){if(e.localName==='more-info-media_player'&&e.stateObj?.entity_id===leader)return true;if(e.shadowRoot&&walk(e.shadowRoot))return true;}return false;}return walk(document);},leader);
  results.push({id:'idle-follower-shortcut-to-playing-leader',services:services.length});
 }
 await page.locator('more-info-media_player').locator('#grouping-button').click();
 await waitGrouping(page);const dialogs=await dialogState(page);
 const visible=tag=>dialogs.filter(d=>d.tag===tag&&d.open&&d.visible).length;
 assert.equal(visible('loxone-group-manager-dialog'),expectedCustom?1:0,JSON.stringify(dialogs));
 assert.equal(visible('dialog-join-media-players'),expectedCustom?0:1,JSON.stringify(dialogs));
 assert.equal(services.length,0);
 results.push({id:'fresh-native-group-'+mode,dialogs,services:services.length});
 if(cross){
  await closeGrouping(page);
  const card=page.locator('loxone-group-control-card');
  assert.equal(await card.locator('[data-action=create]').evaluate(e=>e.disabled),true);
  assert.equal(await card.locator('[data-action=open]').isVisible(),false);
  assert.equal(services.length,0);return;
 }
 if(mode==='gestures'){
  const groupId=states[entity].attributes.loxone_group_control.group_id;
  const manager={locator:selector=>page.locator('loxone-group-manager').locator(selector.replace('[data-group-id=one]',`[data-group-id=${JSON.stringify(groupId)}]`))};
  await (await import('./gesture-v3.mjs')).run({...ctx,manager});return;
 }
 if(mode!=='volume')return;
 const manager=page.locator('loxone-group-manager'),group=manager.locator('[data-master] input'),room=manager.locator(`[data-entity="${leader}"] input`);
 const raw=Math.round(states[leader].attributes.loxone_room_volume_level*100),mean=Math.round(states[leader].attributes.loxone_group_volume_level*100);
 assert.notEqual(raw,mean);assert.equal(Number(await group.inputValue()),mean);assert.equal(Number(await room.inputValue()),raw);
 const before=services.length;await group.focus();await group.press('ArrowRight');
 await page.waitForTimeout(100);
 assert.equal(services.length,before+1);const call=nativeCalls.at(-1);
 assert.equal(call.domain,'loxone');assert.equal(call.service,'audio_group_volume');assert.equal(call.data.volume_percent,mean+1);assert.equal(call.target.entity_id,leader);
 const next=structuredClone(states),members=next[leader].attributes.group_members,values=members.map(i=>Math.round(next[i].attributes.loxone_room_volume_level*100)),updated=values.map(v=>Math.min(100,Math.max(0,v+1))),actual=Math.round(updated.reduce((a,b)=>a+b)/updated.length);
 members.forEach((id,i)=>Object.assign(next[id].attributes,{volume_level:updated[i]/100,loxone_room_volume_level:updated[i]/100,loxone_group_volume_level:actual/100}));publishNative(next);
 await page.waitForFunction(()=>!document.querySelector('home-assistant').shadowRoot.querySelector('loxone-group-manager-dialog')._manager._pending);
 assert.equal(Number(await group.inputValue()),actual);results.push({id:'explicit-group-mean-not-native-room',raw,mean,call:{domain:call.domain,service:call.service,data:call.data,target:call.target}});
 await room.focus();await room.press('ArrowRight');
 for(let i=0;i<200&&services.length!==2;i++)await new Promise(r=>setTimeout(r,10));
 const roomCall=nativeCalls.at(-1);assert.equal(services.length,2);
 assert.equal(roomCall.domain,'loxone');assert.equal(roomCall.service,'audio_room_volume');assert.deepEqual(roomCall.data,{volume_percent:raw+2});assert.deepEqual(roomCall.target,{entity_id:leader});
 Object.assign(next[leader].attributes,{volume_level:(raw+2)/100,loxone_room_volume_level:(raw+2)/100});publishNative(next);
 await page.waitForFunction(()=>!document.querySelector('home-assistant').shadowRoot.querySelector('loxone-group-manager-dialog')._manager._pending);
 assert.equal(Number(await room.inputValue()),raw+2);assert.equal(Number(await group.inputValue()),actual);
 results.push({id:'explicit-room-control-after-group',call:roomCall});
}
