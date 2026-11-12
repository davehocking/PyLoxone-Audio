// Trusted input through the complete pinned native application, synthetic transport only.
import {waitGrouping} from '../r13/native-utils.mjs';
export async function run(ctx){
 const {page,assert,results,services,nativeCalls,snapshot,publishNative,pendingReplies,mode}=ctx;
 const states=structuredClone(snapshot.states),leader=states[snapshot.target].attributes.group_members[0];
 await page.evaluate(id=>document.querySelector('home-assistant').dispatchEvent(new CustomEvent('hass-more-info',{detail:{entityId:id},bubbles:true,composed:true})),leader);
 await page.locator('more-info-media_player').locator('#grouping-button').click();await waitGrouping(page);
 const manager=page.locator('loxone-group-manager'),volume=manager.locator(`[data-entity="${leader}"] [data-volume=room]`),plus=volume.locator('[data-action=volume-plus]');
 await page.evaluate(id=>window.stepLeader=id,leader);
 const initial=Math.round(states[leader].attributes.loxone_room_volume_level*100);
 await manager.evaluate(m=>{window.stepEvents=[];for(const type of ['click','pointerdown','pointerup','keydown','keyup','input','change'])m.shadowRoot.addEventListener(type,e=>window.stepEvents.push({type,trusted:e.isTrusted,key:e.key,repeat:e.repeat,pointerType:e.pointerType,action:e.composedPath().find(n=>n?.dataset?.action)?.dataset.action,at:Date.now()}),true);});
 await page.clock.install();await page.clock.pauseAt(new Date(Date.now()+100));
 await plus.click({force:true});
 await page.clock.runFor(100);await new Promise(r=>setTimeout(r,30));
 assert.equal(services.length,0,'No request before 300ms trailing quiet window');
 assert.equal(await manager.evaluate(m=>!!m._pending),false,'Unsent draft must not acquire real pending');
 assert.equal(await plus.isDisabled(),false,'Stepper remains responsive before dispatch');
 assert.equal(await volume.locator('output').textContent(),`${initial+1}%`);
 await page.clock.runFor(199);assert.equal(services.length,0);
 await page.clock.runFor(1);
 for(let i=0;i<100&&services.length===0;i++)await new Promise(r=>setTimeout(r,10));
 assert.equal(services.length,1);assert.equal(nativeCalls[0].service,'audio_room_volume');assert.deepEqual(nativeCalls[0].data,{volume_percent:initial+1});assert.deepEqual(nativeCalls[0].target,{entity_id:leader});
 results.push({id:'single-tap-trailing-300ms',initial,requested:initial+1});
 pendingReplies.shift()?.failure();await page.clock.runFor(80);await new Promise(r=>setTimeout(r,30));await page.clock.runFor(80);
 if(mode==='single')return;
 const step=async (wrap,sign)=>wrap.locator('[data-action=volume-'+(sign>0?'plus':'minus')+']').click({force:true});
 const tick=async ms=>{await page.clock.runFor(ms);await new Promise(r=>setTimeout(r,25));};
 const publish=async s=>{publishNative(s);await new Promise(r=>setTimeout(r,30));await tick(80);};
 const reject=async()=>{pendingReplies.shift().failure();await tick(80);await tick(80);assert.equal(await manager.evaluate(m=>!!m._pending),false);};
 if(mode==='positive'){
  for(const scope of ['room','group'])for(const sequence of [[1,1,1],[1,-1,1],[1,-1]]){
   const wrap=scope==='room'?volume:manager.locator('[data-master] [data-volume=group]'),start=Number(await wrap.locator('input').inputValue()),before=services.length;
   for(const sign of sequence){await step(wrap,sign);await tick(180);assert.equal(services.length,before,'quiet window restarts at last tap');}
   const requested=start+sequence.reduce((a,b)=>a+b,0);assert.equal(Number(await wrap.locator('input').inputValue()),requested);assert.equal(await wrap.locator('output').textContent(),requested+'%');
   await tick(119);assert.equal(services.length,before);await tick(1);
   assert.equal(services.length,before+(requested!==start?1:0));
   if(requested!==start){assert.equal(nativeCalls.at(-1).service,'audio_'+scope+'_volume');assert.deepEqual(nativeCalls.at(-1).data,{volume_percent:requested});await reject();}
   results.push({id:scope+'-burst-'+sequence.join(','),before,start,requested});
  }
  await step(volume,1);await tick(100);
  const renamed=structuredClone(states);renamed[leader].attributes.friendly_name+=' renamed';await publish(renamed);
  assert.equal(await volume.locator('output').textContent(),`${initial+1}%`,'Benign name reconciliation retains requested draft');
  await tick(100);await step(volume,1);await tick(299);const before=services.length;assert.equal(await volume.locator('output').textContent(),`${initial+2}%`);await tick(1);assert.equal(services.length,before+1);assert.equal(nativeCalls.at(-1).data.volume_percent,initial+2);await reject();
  results.push({id:'benign-redraw-keeps-draft-and-last-tap'});return;
 }
 if(mode==='cancellation'){
  for(const boundary of ['auth','connection','registry','unique','core','capability','volume','mean','busy','revision','owner','group','membership','mode','dialog-entity']){
   const before=services.length;await step(boundary==='mean'?manager.locator('[data-master] [data-volume=group]'):volume,1);await tick(100);
   await manager.evaluate((m,boundary)=>{const h=m.hass;window.stepSavedHass=h;const n={...h,user:{...h.user},entities:{...h.entities},states:structuredClone(h.states)};const id=window.stepLeader;const s=n.states[id];
    if(boundary==='auth')n.user.id='other';if(boundary==='connection')n.connected=false;
    if(boundary==='registry')n.entities[id]={...n.entities[id],platform:'other'};
    if(boundary==='unique')n.entities[id]={...n.entities[id],unique_id:'other'};
    if(boundary==='core')n.config={...h.config,version:'2099.1.0'};
    if(boundary==='capability')s.attributes.supported_features&=~4;
    if(boundary==='volume')s.attributes.loxone_room_volume_level=.51;
    if(boundary==='mean')s.attributes.loxone_group_volume_level=.51;
    if(boundary==='busy')s.attributes.loxone_group_control.busy=true;
    if(boundary==='revision')s.attributes.loxone_group_control.revision+='changed';
    if(boundary==='owner')s.attributes.loxone_group_control.owner+='changed';
    if(boundary==='group')s.attributes.loxone_group_control.group_id+='changed';
    if(boundary==='membership')s.attributes.group_members=[id];
    if(boundary==='mode')m._mode='create';if(boundary==='dialog-entity')m._dialogEntity='media_player.synthetic_speaker_6';m.hass=n;
   },boundary);
   assert.equal(await manager.evaluate(m=>!!m._step),false,boundary+' revokes unsent immediately');
   await manager.evaluate(m=>{m._mode='overview';m._dialogEntity=window.stepLeader;m.hass=window.stepSavedHass;});await tick(400);
   assert.equal(services.length,before,boundary+' ABA no dispatch');assert.equal(await volume.locator('output').textContent(),initial+'%');
   results.push({id:'cancel-observed-'+boundary+'-ABA',services:before});
  }
  for(const boundary of ['close-reopen','detach','stop']){
   const before=services.length;await step(volume,1);await tick(100);
   await manager.evaluate((m,b)=>{window.staleStep=m.shadowRoot.querySelector('[data-entity="'+window.stepLeader+'"] [data-action=volume-plus]').onclick;
    const d=m.getRootNode().host;if(b==='close-reopen'){d.closeDialog();d.showDialog({entity:window.stepLeader});}
    if(b==='detach'){const p=m.parentNode;m.remove();p.append(m);}
    if(b==='stop'){const a=window[Symbol.for('pyloxone-audio.gm03.more-info')];a.stop();a.start();}
   },boundary);await tick(400);assert.equal(services.length,before,boundary+' no postponed dispatch');
   await page.evaluate(()=>window.staleStep?.(new MouseEvent('click')));await tick(400);assert.equal(services.length,before,boundary+' stale callback');
   await step(volume,1);await tick(300);assert.equal(services.length,before+1);await reject();results.push({id:'cancel-'+boundary+'-fresh-recovery'});
  }
  const before=services.length;await step(volume,1);await tick(100);await page.evaluate(()=>window[Symbol.for('pyloxone-audio.gm03.more-info')].dispose());await tick(400);assert.equal(services.length,before);results.push({id:'dispose-revokes-unsent'});return;
 }
 if(mode==='limits-inputs'){
  for(const scope of ['room','group'])for(const start of [0,1,99,100]){
   const s=structuredClone(states);for(const id of s[leader].attributes.group_members)Object.assign(s[id].attributes,{loxone_room_volume_level:start/100,loxone_group_volume_level:start/100,volume_level:start/100});await publish(s);
   const wrap=scope==='room'?volume:manager.locator('[data-master] [data-volume=group]'),sign=start<2?1:-1,before=services.length;
   const disabled=wrap.locator('[data-action=volume-'+(start===0?'minus':'plus')+']');if(start===0||start===100)assert.equal(await disabled.isDisabled(),true);
   for(let n=0;n<3;n++){await step(wrap,sign);await tick(80);}
   await tick(220);assert.equal(services.length,before+1);assert.equal(nativeCalls.at(-1).data.volume_percent,start+sign*3);assert.equal(nativeCalls.at(-1).service,'audio_'+scope+'_volume');await reject();
   const edge=start<2?0:100,edgeSign=start<2?-1:1;
   await step(wrap,edgeSign);if(start===1||start===99){assert.equal(Number(await wrap.locator('input').inputValue()),edge);assert.equal(await wrap.locator('[data-action=volume-'+(edge===0?'minus':'plus')+']').isDisabled(),true);await tick(300);assert.equal(nativeCalls.at(-1).data.volume_percent,edge);await reject();}
   else{await tick(400);assert.equal(services.length,before+1);}
   results.push({id:scope+'-clamps-'+start});
  }
  await publish(states);
  for(const input of ['touch','Space','Enter']){
   const before=services.length;
   if(input==='touch')await plus.tap({force:true});else{await plus.focus();await page.keyboard.press(input==='Space'?' ':input);}
   await tick(299);assert.equal(services.length,before);await tick(1);assert.equal(services.length,before+1);assert.equal(nativeCalls.at(-1).data.volume_percent,initial+1);await reject();results.push({id:'trusted-'+input+'-stepper'});
  }
  const group=manager.locator('[data-master] [data-volume=group]'),other=manager.locator(`[data-entity="${snapshot.target}"] [data-volume=room]`);
  for(const next of [group,other]){const before=services.length;await step(volume,1);await tick(100);await step(next,-1);assert.equal(await volume.locator('output').textContent(),initial+'%','different scope cancels old preview');await tick(300);assert.equal(services.length,before+1);assert.equal(nativeCalls.at(-1).service,next===group?'audio_group_volume':'audio_room_volume');assert.equal(nativeCalls.at(-1).target.entity_id,next===group?leader:snapshot.target);await reject();await tick(400);assert.equal(services.length,before+1);}
  results.push({id:'distinct-group-room-and-follower-scopes-no-background-queue'});return;
 }
 if(mode==='settlement'){
  for(const settlement of ['failure','success']){
   const before=services.length;await step(volume,1);await tick(300);assert.equal(services.length,before+1);assert.equal(await plus.isDisabled(),true);assert.match(await manager.locator('[role=status]').textContent(),/Please wait/);
   assert.equal(await manager.evaluate(m=>m.getRootNode().host.closeDialog()),false,'cannot dismiss actual submitted work');
   await tick(8001);assert.equal(await manager.evaluate(m=>!!m._pending),true,'UI deadline retains actual outstanding request');assert.equal(await plus.isDisabled(),true);assert.match(await manager.locator('[role=alert]').textContent(),/outstanding/);
   pendingReplies.shift()[settlement]();await tick(100);await tick(100);assert.equal(await manager.evaluate(m=>!!m._pending),false);assert.equal(await volume.locator('output').textContent(),initial+'%','late settlement does not publish requested level');
   assert.match(await manager.locator('[role=alert]').textContent(),settlement==='failure'?/Synthetic service refusal/:/completed successfully, but feedback was not verified/);
   await tick(400);assert.equal(services.length,before+1);results.push({id:'timeout-late-'+settlement+'-pending-no-replay'});
  }
  const before=services.length;await step(volume,1);await tick(300);const changed=structuredClone(states);Object.assign(changed[leader].attributes,{volume_level:(initial+1)/100,loxone_room_volume_level:(initial+1)/100});pendingReplies.shift().success();await publish(changed);await tick(100);assert.equal(await manager.evaluate(m=>!!m._pending),false);assert.equal(await volume.locator('output').textContent(),(initial+1)+'%');assert.equal(await manager.locator('[role=alert]').textContent(),'');assert.equal(services.length,before+1);
  const group=manager.locator('[data-master] [data-volume=group]');await publish(states);await step(group,1);await tick(300);
  const confirmed=structuredClone(states),members=confirmed[leader].attributes.group_members,values=members.map(i=>Math.round(confirmed[i].attributes.loxone_room_volume_level*100)),mean=Math.round(values.reduce((a,b)=>a+b,0)/values.length),wanted=nativeCalls.at(-1).data.volume_percent,newValues=values.map(v=>Math.max(0,Math.min(100,v+wanted-mean))),actual=Math.round(newValues.reduce((a,b)=>a+b,0)/newValues.length);members.forEach((id,i)=>Object.assign(confirmed[id].attributes,{volume_level:newValues[i]/100,loxone_room_volume_level:newValues[i]/100,loxone_group_volume_level:actual/100}));pendingReplies.shift().success();await publish(confirmed);await tick(100);assert.equal(await manager.evaluate(m=>!!m._pending),false);assert.equal(await group.locator('output').textContent(),actual+'%');results.push({id:'fresh-room-and-group-feedback-confirmed-success',actual});return;
 }
 if(mode==='held'){
  for(const key of [' ','Enter']){
   const before=services.length;await plus.focus();await page.keyboard.down(key);await tick(50);
   await manager.evaluate(m=>{const h=m.hass,id=window.stepLeader;const entities={...h.entities,[id]:{...h.entities[id],unique_id:'changed-synthetic'}};m.hass={...h,entities};m.hass=h;});
   await page.keyboard.down(key);await page.keyboard.up(key);await tick(400);
   assert.equal(services.length,before,'held '+key+' cannot regain registry ABA authority');
   await plus.focus();await page.keyboard.press(key);await tick(300);assert.equal(services.length,before+1);await reject();results.push({id:'held-'+key+'-registry-ABA-and-fresh-recovery'});
  }
  return;
 }
 if(mode==='stale-timer'){
  await page.evaluate(()=>{window.stepTimeouts=[];const original=window.setTimeout;window.setTimeout=(callback,ms,...args)=>{const id=original(callback,ms,...args);if(ms===300)window.stepTimeouts.push({id,callback});return id;};});
  const before=services.length;await step(volume,1);await tick(100);await manager.evaluate(m=>{window.oldDraftTimer=window.stepTimeouts.find(t=>t.id===m._step.timer).callback;const h=m.hass;m.hass={...h,user:{...h.user,id:'other'}};m.hass=h;});
  await page.evaluate(()=>window.oldDraftTimer());await tick(400);assert.equal(services.length,before);
  await step(volume,1);await page.evaluate(()=>window.oldDraftTimer());await tick(299);assert.equal(services.length,before);await tick(1);assert.equal(services.length,before+1);await reject();results.push({id:'saved-revoked-timeout-callback-does-not-revive-or-destroy-fresh-draft'});return;
 }
 if(mode==='dismissal'){
  const before=services.length;await step(volume,1);await tick(250);await page.keyboard.press('Escape');await tick(400);assert.equal(services.length,before,'native Escape cancels unsent draft before closing animation');results.push({id:'trusted-native-Escape-revokes-unsent'});return;
 }
 if(mode==='root'){
  const before=services.length;await step(volume,1);await tick(100);await manager.evaluate(m=>window.oldStep=m.shadowRoot.querySelector('[data-action=volume-plus]').onclick);
  await page.clock.resume();await page.evaluate(()=>{window.oldStepApp=document.querySelector('home-assistant');window.oldStepApp.remove();document.body.append(document.createElement('home-assistant'));});await page.waitForTimeout(400);assert.equal(services.length,before,'detached app cannot dispatch timer');await page.evaluate(()=>window.oldStep?.(new MouseEvent('click')));await page.waitForTimeout(400);assert.equal(services.length,before);
  await page.waitForFunction(()=>!!document.querySelector('home-assistant')?.hass?.states?.['media_player.synthetic_speaker_1']);
  await page.evaluate(id=>document.querySelector('home-assistant').dispatchEvent(new CustomEvent('hass-more-info',{detail:{entityId:id},bubbles:true,composed:true})),leader);await page.locator('more-info-media_player').locator('#grouping-button').click();await waitGrouping(page);await plus.click();
  for(let i=0;i<100&&services.length===before;i++)await new Promise(r=>setTimeout(r,10));assert.equal(services.length,before+1);pendingReplies.shift().failure();results.push({id:'actual-compiled-root-replacement-revokes-timer-and-stale-callback-fresh-native-recovery'});return;
 }
 if(mode==='competition'){
  const before=services.length;await step(volume,1);await tick(100);
  const play=manager.locator(`[data-entity="${leader}"] [data-action=row-play]`);await play.scrollIntoViewIfNeeded();const box=await play.boundingBox();await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();await tick(400);
  assert.equal(services.length,before,'beginning competing transport cancels unsent volume before release');await page.mouse.up();await tick(10);assert.equal(services.length,before+1);assert.equal(nativeCalls.at(-1).service,'audio_room_transport');await reject();await tick(400);assert.equal(services.length,before+1);results.push({id:'competing-held-transport-revokes-before-release'});return;
 }
 if(mode==='range'){
  await step(volume,1);await tick(100);const before=services.length;
  const range=volume.locator('input');await range.focus();await page.keyboard.press('ArrowRight');await tick(1);
  assert.equal(services.length,before+1,'range keyboard stays immediate');assert.equal(nativeCalls.at(-1).data.volume_percent,initial+1,'range begins at actual level, not abandoned step preview');
  await reject();await tick(400);assert.equal(services.length,before+1,'abandoned step never dispatches after range settles');
  await step(volume,1);await tick(100);
  const box=await range.boundingBox();await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();
  assert.equal(await manager.evaluate(m=>!!m._step),false,'pointer range start revokes unsent step');
  await page.mouse.move(box.x+box.width*.65,box.y+box.height/2);await tick(400);assert.equal(services.length,before+1,'no service while range held');await page.mouse.up();await tick(20);
  assert.equal(services.length,before+2);assert.equal(nativeCalls.at(-1).service,'audio_room_volume');await reject();await tick(400);assert.equal(services.length,before+2);
  results.push({id:'range-keyboard-and-trusted-pointer-cancel-old-step-no-delay-no-extra-send'});return;
 }
 throw new Error('Unknown stepper case '+mode);
}
