// Corrective R229-1: trusted action START, not eventual click, owns cancellation.
import {waitGrouping} from '../r13/native-utils.mjs';
export async function run(ctx){
 const {page,assert,results,services,nativeCalls,snapshot,pendingReplies,mode}=ctx;
 const states=structuredClone(snapshot.states),leader=states[snapshot.target].attributes.group_members[0];
 await page.evaluate(id=>document.querySelector('home-assistant').dispatchEvent(new CustomEvent('hass-more-info',{detail:{entityId:id},bubbles:true,composed:true})),leader);
 await page.locator('more-info-media_player').locator('#grouping-button').click();await waitGrouping(page);
 const manager=page.locator('loxone-group-manager');
 const room=id=>manager.locator(`[data-entity="${id}"] [data-volume=room]`),group=manager.locator('[data-master] [data-volume=group]');
 const scopes={leader:{wrap:room(leader),id:leader,scope:'room'},follower:{wrap:room(snapshot.target),id:snapshot.target,scope:'room'},group:{wrap:group,id:leader,scope:'group'}};
 await manager.evaluate(m=>{window.stepEvents=[];for(const type of ['click','pointerdown','pointerup','keydown','keyup','input','change'])m.shadowRoot.addEventListener(type,e=>window.stepEvents.push({type,trusted:e.isTrusted,key:e.key,repeat:e.repeat,pointerType:e.pointerType,action:e.composedPath().find(n=>n?.dataset?.action)?.dataset.action,at:Date.now()}),true);});
 await page.clock.install();await page.clock.pauseAt(new Date(Date.now()+100));
 const tick=async ms=>{await page.clock.runFor(ms);await new Promise(r=>setTimeout(r,25));};
 const button=(s,sign)=>s.wrap.locator('[data-action=volume-'+(sign>0?'plus':'minus')+']');
 const value=s=>Math.round(states[s.id].attributes[s.scope==='room'?'loxone_room_volume_level':'loxone_group_volume_level']*100);
 const tap=async(s,sign)=>button(s,sign).click({force:true});
 const start=async(s,sign,input)=>{
  const b=button(s,sign);await b.scrollIntoViewIfNeeded();
  if(input==='Space'){await b.focus();await page.keyboard.down(' ');}
  else{const box=await b.boundingBox();await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();}
 };
 const release=async input=>input==='Space'?page.keyboard.up(' '):page.mouse.up();
 const reject=async()=>{assert.equal(pendingReplies.length,1);pendingReplies.shift().failure();await tick(100);await tick(100);assert.equal(await manager.evaluate(m=>!!m._pending),false);};
 const request=(s,percent)=>{assert.equal(nativeCalls.at(-1).domain,'loxone');assert.equal(nativeCalls.at(-1).service,'audio_'+s.scope+'_volume');assert.deepEqual(nativeCalls.at(-1).target,{entity_id:s.id});assert.deepEqual(nativeCalls.at(-1).data,{volume_percent:percent});};
 if(mode==='scope-pointer'||mode==='scope-space'){
  const input=mode==='scope-space'?'Space':'pointer';
  for(const [from,to]of [['leader','group'],['group','follower'],['leader','follower'],['follower','leader']]){
   const old=scopes[from],next=scopes[to],before=services.length;
   await tap(old,1);await tick(100);await start(next,-1,input);
   try{
    assert.equal(await manager.evaluate(m=>!!m._step),false,'Different exact logical key revokes draft at action start');
    assert.equal(await old.wrap.locator('output').textContent(),value(old)+'%','Cancelled old preview resets immediately');
    await tick(400);assert.equal(services.length,before,'No old send while different press held beyond deadline');
    assert.equal(await manager.evaluate(m=>!!m._pending),false,'No premature real pending');
   }finally{await release(input);}
   await tick(299);assert.equal(services.length,before);assert.equal(await next.wrap.locator('output').textContent(),(value(next)-1)+'%');
   await tick(1);assert.equal(services.length,before+1);request(next,value(next)-1);await reject();await tick(400);assert.equal(services.length,before+1,'No ghost old timer after settlement');
   await tap(old,1);await tick(300);assert.equal(services.length,before+2);request(old,value(old)+1);await reject();
   results.push({id:`${input}-${from}-to-${to}-start-cancellation-and-fresh-recovery`,before});
  }
  return;
 }
 if(mode==='scope-aba'){
  for(const input of ['pointer','Space'])for(const boundary of ['benign','registry-ABA','auth-ABA']){
   const old=scopes.leader,next=scopes.group,before=services.length;
   await tap(old,1);await tick(100);await start(next,-1,input);
   await manager.evaluate((m,boundary)=>{const h=m.hass;if(boundary==='benign'){m.hass={...h,states:structuredClone(h.states)};return;}if(boundary==='registry-ABA'){const id=m._dialogEntity;m.hass={...h,entities:{...h.entities,[id]:{...h.entities[id],unique_id:'synthetic-changed'}}};}else m.hass={...h,user:{...h.user,id:'synthetic-changed'}};m.hass=h;},boundary);
   await tick(400);assert.equal(services.length,before);assert.equal(await manager.evaluate(m=>!!m._step),false);
   await release(input);await tick(300);
   const count=boundary==='benign'?1:0;assert.equal(services.length,before+count,'Held press cannot regain ABA authority');
   if(count){request(next,value(next)-1);await reject();}
   await tick(400);assert.equal(services.length,before+count);
   await tap(next,-1);await tick(300);assert.equal(services.length,before+count+1);request(next,value(next)-1);await reject();
   results.push({id:`${input}-different-scope-${boundary}-and-fresh-recovery`,before});
  }
  return;
 }
 if(mode==='same-control'){
  for(const scope of ['leader','group'])for(const input of ['pointer','Space'])for(const sign of [1,-1]){
   const s=scopes[scope],before=services.length;await tap(s,1);await tick(100);await start(s,sign,input);await tick(100);
   assert.equal(await s.wrap.locator('output').textContent(),(value(s)+1)+'%','Same logical key retains draft before click');
   assert.equal(await manager.evaluate(m=>!!m._step),true);assert.equal(services.length,before);
   await release(input);await tick(299);assert.equal(services.length,before);assert.equal(await s.wrap.locator('output').textContent(),(value(s)+1+sign)+'%');
   await tick(1);assert.equal(services.length,before+(sign===1?1:0));if(sign===1){request(s,value(s)+2);await reject();}await tick(400);assert.equal(services.length,before+(sign===1?1:0));
   results.push({id:`${input}-${scope}-same-logical-control-sign-${sign}-retained`,before});
  }
  // A held same-control press is not yet another accepted tap; do not invent a
  // new press-start debounce or cancel the previously accepted tap's timer.
  const s=scopes.leader,before=services.length;await tap(s,1);await tick(100);await start(s,1,'pointer');await tick(400);
  assert.equal(services.length,before+1);request(s,value(s)+1);assert.equal(await manager.evaluate(m=>!!m._pending),true);await release('pointer');await tick(400);assert.equal(services.length,before+1);await reject();
  results.push({id:'same-control-long-hold-preserves-accepted-timer-and-real-pending',before});return;
 }
 throw new Error('Unknown corrective scope-start mode '+mode);
}
