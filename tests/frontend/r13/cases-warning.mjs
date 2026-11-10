export async function run({page,assert,results,services,snapshot,publishNative,pendingReplies,out,fs,path,mode}){
 const id=snapshot.target,leader=snapshot.states[id].attributes.group_members[0];
 const states=structuredClone(snapshot.states);states[id].state='paused';states[leader].state='playing';
 publishNative(states);
 await page.locator('hui-media-control-card .more-info').click();
 const more=page.locator('ha-more-info-dialog more-info-media_player');await more.locator('#grouping-button').click();
 const dialog=page.locator('loxone-group-manager-dialog'),manager=dialog.locator('loxone-group-manager');
 await dialog.locator('[data-action=close]').waitFor({state:'visible'});
 const row=manager.locator(`[data-entity="${id}"] [data-action=row-play]`);await row.click();
 await page.waitForFunction(()=>!!document.querySelector('home-assistant').shadowRoot.querySelector('loxone-group-manager-dialog')._manager._pending);
 assert.equal(services.length,1);assert.equal(pendingReplies.length,1);
 assert.deepEqual({domain:services[0].domain,service:services[0].service,data:services[0].service_data,target:services[0].target},{domain:'loxone',service:'audio_room_transport',data:{action:'play'},target:{entity_id:id}});
 if(mode.includes('early-failure')){
  pendingReplies.shift().failure();await page.waitForFunction(()=>!document.querySelector('home-assistant').shadowRoot.querySelector('loxone-group-manager-dialog')._manager._pending);
  assert.match(await manager.evaluate(m=>m._error),/Synthetic service refusal/);assert.equal(services.length,1);results.push('Early service refusal retained, pending released after actual rejection, no retry');return;
 }
 const state=async()=>manager.evaluate(m=>({pending:!!m._pending,error:m._error,busy:m.shadowRoot.querySelector('.manager-layout').getAttribute('aria-busy'),status:m.shadowRoot.querySelector('[role=status]').textContent,disabled:[...m.shadowRoot.querySelectorAll('button,input,ha-button')].filter(n=>!n.disabled).length}));
 const busy=structuredClone(states);for(const s of Object.values(busy))s.attributes.loxone_group_control.busy=true;
 busy[id].state='playing';publishNative(busy);await page.waitForTimeout(150);
 const normal=await state();assert.equal(normal.pending,true);assert.equal(normal.error,'','Ordinary own room playing/busy feedback must not be called invalid');
 results.push({normal});
 if(mode.includes('timeout'))await page.waitForTimeout(8300);
 else if(mode.includes('detach'))await manager.evaluate(m=>{const p=m.parentElement;m.remove();p.append(m);});
 else if(!mode.includes('stable')){
  if(mode.includes('auth')||mode.includes('disconnect')){
     await manager.evaluate((m,kind)=>{const h=m.hass;m.hass=kind.includes('auth')?{...h,user:{...h.user,id:'synthetic-other'}}:{...h,connected:false};m.hass=h;},mode);
  }else{
   const revoked=structuredClone(busy),other=Object.keys(states).find(i=>!states[id].attributes.group_members.includes(i));
   if(mode.includes('context'))for(const s of Object.values(revoked))s.attributes.loxone_group_control.revision='changed-native-context';
   else if(mode.includes('owner'))for(const s of Object.values(revoked))s.attributes.loxone_group_control.owner='changed-owner';
   else if(mode.includes('group'))for(const i of states[id].attributes.group_members)revoked[i].attributes.loxone_group_control.group_id='changed-group';
   else if(mode.includes('membership'))for(const i of states[id].attributes.group_members){revoked[i].attributes.group_members=[i];revoked[i].attributes.loxone_group_control.members=[i];revoked[i].attributes.loxone_group_control.group_id=null;}
   else if(mode.includes('target'))delete revoked[id].attributes.loxone_group_control;
   else delete revoked[other].attributes.loxone_group_control;
   publishNative(revoked);await page.waitForTimeout(160);
   if(mode.includes('aba')){publishNative(busy);await page.waitForTimeout(160);}
  }
 }
 if(mode.includes('slow'))await page.waitForTimeout(6200);
 const held=await state();fs.writeFileSync(path.join(out,'held.json'),JSON.stringify({normal,held,services},null,2));
 assert.equal(held.pending,true,'An already-submitted HA service is still outstanding: guard race must NOT clear pending');
 assert.equal(held.busy,'true');assert.match(held.status,/Please wait/);assert.equal(held.disabled,0);
 if(!mode.includes('stable')||mode.includes('timeout'))assert.notEqual(held.error,'','A real revocation or deadline must be latched, including ABA');
 await dialog.locator('[data-action=close]').click({force:true});assert.equal(await dialog.evaluate(d=>d._open),true,'Cannot dismiss while the submitted service is outstanding');
 const failed=mode.includes('failure');const reply=pendingReplies.shift();failed?reply.failure():reply.success();
 await page.waitForFunction(()=>!document.querySelector('home-assistant').shadowRoot.querySelector('loxone-group-manager-dialog')._manager._pending);
 const settled=await state();fs.writeFileSync(path.join(out,'settled.json'),JSON.stringify(settled,null,2));
 if(failed)assert.match(settled.error,/Synthetic service refusal/,'Retain actual service failure');
 else if(mode.includes('stable')&&!mode.includes('timeout'))assert.equal(settled.error,'');
 else assert.match(settled.error,/completed successfully/i,'Successful HA service return must not be reported as failed playback');
 assert.equal(services.length,1,'No retry, rollback, compensation or other command');
 results.push({held,settled,serviceReturned:failed?'failure':'success',acousticProof:false});
 await page.screenshot({path:path.join(out,'settled.png')});
 if(mode.includes('recovery')){
  publishNative(states);await page.waitForTimeout(150);await row.click();assert.equal(services.length,2,'One genuinely new click starts one new service after prior settlement');assert.equal(pendingReplies.length,1);pendingReplies.shift().success();await page.waitForFunction(()=>!document.querySelector('home-assistant').shadowRoot.querySelector('loxone-group-manager-dialog')._manager._pending);assert.equal(await manager.evaluate(m=>m._error),'');results.push('After settlement and eligibility restoration one fresh physical click succeeds; no retained guard or stale operation');
 }
}
