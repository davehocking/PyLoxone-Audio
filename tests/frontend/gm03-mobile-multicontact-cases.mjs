// Strict cancellation policy; trusted Chromium input only, no gesture substitutes.
export async function run({page,browser,manager,dialog,publishNative,snapshot,services,nativeCalls,out,fs,path,assert,results}){
 const cdp=await browser.newCDPSession(page),records=[];
 const group=()=>manager.locator('[data-group-id=one] [data-master] input');
 const room=()=>manager.locator('[data-entity="media_player.synthetic_speaker_1"] input');
 const baseline=await manager.evaluate(m=>({user:m.hass.user,entities:m.hass.entities,config:m.hass.config}));
 const reset=async()=>{publishNative(snapshot.states);await manager.evaluate((m,h)=>{m.hass={...m.hass,...h,connected:true};},baseline);await dialog.evaluate(d=>{if(!d._open)d.showDialog({entity:'media_player.synthetic_speaker_1'});});await page.waitForTimeout(100);};
 const point=async(range,p,id)=>{await range.scrollIntoViewIfNeeded();const b=await range.boundingBox();return {x:b.x+8+(b.width-16)*p/100,y:b.y+b.height/2,id};};
 const send=async(type,points)=>{await cdp.send('Input.dispatchTouchEvent',{type,touchPoints:points});await page.waitForTimeout(65);};
 const scalar=c=>({domain:c.domain,service:c.service,data:c.data,target:c.target});
 const trace=async()=>page.evaluate(()=>window.__strictEvents);
 for(const kind of ['primary-first','secondary-first','secondary-move','benign-four','auth-revoked','raw-revoked','cancel-all','lost-primary','lost-secondary','cross-room','third-while-secondary','blur-after-ambiguity']){
  await reset();const n=services.length,a=await point(group(),25,11),b=await point(group(),65,11),s=kind==='cross-room'?await point(room(),80,22):await point(group(),80,22);
  await group().evaluate(e=>{window.__strictAbort?.abort();window.__strictAbort=new AbortController();window.__strictRange=e;window.__strictEvents=[];for(const t of ['pointerdown','pointerup','pointercancel','lostpointercapture','input','change','touchstart','touchend','touchcancel'])window.addEventListener(t,v=>window.__strictEvents.push({type:t,trusted:v.isTrusted,pointer:v.pointerId,primary:v.isPrimary,value:e.value,connected:e.isConnected,touches:v.touches?.length}),{capture:true,signal:window.__strictAbort.signal});});
  // Event observers are test-only; the product has no global listeners.
  await send('touchStart',[a]);await send('touchMove',[b]);assert.equal(services.length,n,kind+' no primary pre-release');
  await send('touchStart',[b,s]);assert.equal(services.length,n,kind+' no secondary pre-release');
  if(kind==='secondary-move'){s.x=(await point(group(),90,22)).x;await send('touchMove',[b,s]);}
  if(kind==='benign-four')for(let i=0;i<4;i++){const next=structuredClone(snapshot.states);next['media_player.synthetic_speaker_2'].attributes.media_title='Harmless '+i;publishNative(next);await page.waitForTimeout(70);}
  if(kind==='auth-revoked')await manager.evaluate(m=>{const h=m.hass;m.hass={...h,user:{...h.user,id:'synthetic-revoked'}};m.hass=h;});
  if(kind==='raw-revoked'){const next=structuredClone(snapshot.states);next['media_player.synthetic_speaker_2'].attributes.loxone_room_volume_level=.41;publishNative(next);await page.waitForTimeout(70);}
  if(kind.startsWith('lost-'))await manager.evaluate((m,kind)=>{const ids=window.__strictEvents.filter(e=>e.type==='pointerdown').map(e=>e.pointer);const id=ids[kind==='lost-primary'?0:1];const e=window.__strictRange;if(e.hasPointerCapture(id))e.releasePointerCapture(id);},kind);
  if(kind==='blur-after-ambiguity'){await group().focus();await manager.locator('[data-action=create]').focus();}
  assert.equal(services.length,n,kind+' no held dispatch');
  if(kind==='cancel-all')await send('touchCancel',[]);
  else if(kind==='secondary-first'){await send('touchEnd',[s]);assert.equal(services.length,n,kind+' first release zero');await send('touchEnd',[]);}
  else {await send('touchEnd',[b]);assert.equal(services.length,n,kind+' primary release zero');
   if(kind==='third-while-secondary'){const third=await point(group(),90,33);await send('touchStart',[s,third]);await send('touchEnd',[third]);assert.equal(services.length,n,'third nonprimary cannot acquire');}
   await send('touchEnd',[]);
  }
  await page.waitForTimeout(120);const events=await trace();records.push({kind,phase:'both-ended',calls:nativeCalls.slice(n).map(scalar),events});fs.writeFileSync(path.join(out,'strict-multicontact.json'),JSON.stringify(records,null,2));
  assert.ok(events.filter(e=>e.type==='pointerdown'&&e.trusted).length>=2,kind+' trusted contacts');
  assert.equal(services.length,n,kind+' STRICT zero total after BOTH releases/cancel and stale native change');
  // Do not reset/reopen before reacquisition: prove this same component can recover.
  const start=await point(group(),25,44),finish=await point(group(),65,44);await send('touchStart',[start]);await send('touchMove',[finish]);assert.equal(services.length,n,kind+' recovery pre-release zero');await send('touchEnd',[]);
  assert.equal(services.length,n+1,kind+' deliberate single-pointer works once');const call=nativeCalls.at(-1);assert.equal(Math.round(call.data.volume_level*100),65);assert.equal(call.target.entity_id,'media_player.synthetic_speaker_1');
  const next=structuredClone(snapshot.states);for(const [i,p] of [[1,50],[2,80]]){next['media_player.synthetic_speaker_'+i].attributes.loxone_room_volume_level=p/100;next['media_player.synthetic_speaker_'+i].attributes.volume_level=.65;}publishNative(next);await page.waitForFunction(()=>!document.querySelector('home-assistant').shadowRoot.querySelector('loxone-group-manager-dialog')._manager._pending);
  await page.waitForTimeout(80);assert.equal(services.length,n+1,kind+' no ghost duplicate');records.push({kind,phase:'recovery',call:scalar(call)});fs.writeFileSync(path.join(out,'strict-multicontact.json'),JSON.stringify(records,null,2));
 }
 await cdp.detach();results.push('strict twelve multi-contact cancellation and same-component trusted recovery cases');
}
