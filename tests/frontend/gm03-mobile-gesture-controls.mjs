// Explicit stale-intent and ordinary control preservation; real held input pipeline.
export async function run(ctx){
 const {page,browser,manager,dialog,publishNative,snapshot,services,nativeCalls,out,fs,path,assert,results}=ctx;
 const baselineHass=await manager.evaluate(m=>({user:m.hass.user,entities:m.hass.entities,config:m.hass.config}));
 const trace=[],requests=[];const id='media_player.synthetic_speaker_1',follower='media_player.synthetic_speaker_2',free='media_player.synthetic_speaker_6';
 const reset=async()=>{publishNative(snapshot.states);await manager.evaluate((m,h)=>{m.hass={...m.hass,...h,connected:true};},baselineHass);await dialog.evaluate(d=>{if(!d._open)d.showDialog({entity:'media_player.synthetic_speaker_1'});});await page.waitForTimeout(140);};
 const cdp=await browser.newCDPSession(page);
 const range=room=>manager.locator(room?`[data-entity="${id}"] input`:'[data-group-id=one] [data-master] input');
 const point=async(room,p)=>{const e=range(room);await e.scrollIntoViewIfNeeded();const b=await e.boundingBox();return {x:b.x+8+(b.width-16)*p/100,y:b.y+b.height/2};};
 const begin=async(room=false)=>{const e=range(room),p=Number(await e.inputValue()),xy=await point(room,p);await e.evaluate(e=>{window.__guardRange=e;window.__guardEvents=[];for(const t of ['pointerdown','pointerup','pointercancel','input','change'])e.addEventListener(t,v=>window.__guardEvents.push({type:t,trusted:v.isTrusted,value:e.value,connected:e.isConnected}));});await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[xy]});await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[await point(room,60)]});};
 const end=async(cancel=false)=>{await cdp.send('Input.dispatchTouchEvent',{type:cancel?'touchCancel':'touchEnd',touchPoints:[]});await page.waitForTimeout(100);};
 for(const kind of ['relevant-raw-volume','relevant-mean','membership','revision','owner','unavailable','feature','busy','registry','auth-aba','disconnect-aba','host-version','pointercancel','lost-capture','blur','close-reopen','detach-reconnect']){
  await reset();const count=services.length;if(kind==='blur')await range(false).focus();await begin();
  if(kind==='auth-aba'||kind==='disconnect-aba'||kind==='host-version'||kind==='registry')await manager.evaluate((m,kind)=>{const h=m.hass;m.hass=kind==='auth-aba'?{...h,user:{...h.user,id:'synthetic-revoked'}}:kind==='disconnect-aba'?{...h,connected:false}:kind==='host-version'?{...h,config:{...h.config,version:'unsupported'}}:{...h,entities:{...h.entities,'media_player.synthetic_speaker_2':{platform:'foreign'}}};if(kind.endsWith('aba'))m.hass=h;},kind);
  else if(kind==='close-reopen')await dialog.evaluate(d=>{d.closeDialog();d.showDialog({entity:'media_player.synthetic_speaker_1'});});
  else if(kind==='detach-reconnect')await manager.evaluate(m=>{const p=m.parentElement;m.remove();p.append(m);});
  else if(kind==='lost-capture')await manager.evaluate(m=>window.__guardRange.releasePointerCapture(m._gesture.pointer));
  else if(kind==='blur')await manager.locator('[data-action=create]').focus();
  else if(kind!=='pointercancel'){
   const states=structuredClone(snapshot.states);
   if(kind==='relevant-raw-volume')states[follower].attributes.loxone_room_volume_level+=.001;
   if(kind==='relevant-mean')for(const i of [id,follower])states[i].attributes.volume_level=.26;
   if(kind==='membership')for(const i of [id,follower]){states[i].attributes.group_members=[i];states[i].attributes.loxone_group_control.members=[i];states[i].attributes.loxone_group_control.group_id=null;}
   if(kind==='revision'||kind==='owner'||kind==='busy')for(const s of Object.values(states))s.attributes.loxone_group_control[kind==='revision'?'revision':kind==='owner'?'owner':'busy']=kind==='busy'?true:'synthetic-changed';
   if(kind==='unavailable')states[follower].state='unavailable';if(kind==='feature')states[id].attributes.supported_features=524288;
   publishNative(states);await page.waitForTimeout(90);
  }
  await end(kind==='pointercancel');
  trace.push({kind,count:services.length-count,events:await page.evaluate(()=>window.__guardEvents)});
  fs.writeFileSync(path.join(out,'guard-traces.json'),JSON.stringify(trace,null,2));
  assert.equal(services.length,count,kind+' must revoke stale intent without dispatch');
 }
 // Metadata/sorting and unrelated room actual volume are not this group's intent.
 await reset();const count=services.length;await begin();
 const benign=structuredClone(snapshot.states);benign[free].attributes.volume_level=.87;benign[free].attributes.loxone_room_volume_level=.87;benign[id].attributes.friendly_name='ZZZ renamed synthetic room';benign[follower].attributes.media_title='Unrelated display refresh';publishNative(benign);await page.waitForTimeout(120);
 assert.ok(await page.evaluate(()=>window.__guardRange.isConnected),'metadata/sorting must retain range');await end();assert.equal(services.length,count+1);requests.push({...nativeCalls.at(-1),label:'metadata-drag'});
 const confirm=async(request,states)=>{
  const next=structuredClone(states),room=request.service==='audio_room_volume',members=next[id].attributes.group_members,values=members.map(i=>Math.round(next[i].attributes.loxone_room_volume_level*100)),mean=Math.round(values.reduce((a,b)=>a+b,0)/values.length),wanted=room?request.data.volume_percent:Math.round(request.data.volume_level*100),updated=room?values.map((v,n)=>members[n]===request.target.entity_id?wanted:v):values.map(v=>Math.max(0,Math.min(100,v+wanted-mean))),actual=Math.round(updated.reduce((a,b)=>a+b,0)/updated.length);
  members.forEach((i,n)=>{next[i].attributes.loxone_room_volume_level=updated[n]/100;next[i].attributes.volume_level=actual/100;});publishNative(next);await page.waitForFunction(()=>!document.querySelector('home-assistant').shadowRoot.querySelector('loxone-group-manager-dialog')._manager._pending);return {next,updated,actual};
 };
 await confirm(nativeCalls.at(-1),benign);
 for(const [kind,room,wanted] of [['clamp-high',false,100],['clamp-low',false,0],['own-room',true,60],['tap',false,45],['stationary',false,25],['plus',false,26],['minus',false,24],['keyboard',false,26]]){
  await reset();const n=services.length;
  if(kind==='plus'||kind==='minus')await manager.locator(`[data-master] [data-action=volume-${kind}]`).first().click();
  else if(kind==='keyboard'){await range(false).focus();await page.keyboard.press('ArrowRight');}
  else {const start=Number(await range(room).inputValue());await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[await point(room,kind==='tap'?wanted:start)]});if(kind!=='tap'&&kind!=='stationary')await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[await point(room,wanted)]});await end();}
  await page.waitForTimeout(80);
  if(kind==='stationary'){assert.equal(services.length,n,'stationary no-change tap sends nothing');continue;}
  assert.equal(services.length,n+1,kind+' one request');const request=nativeCalls.at(-1);requests.push({...request,label:kind});
  assert.equal(room?request.data.volume_percent:Math.round(request.data.volume_level*100),wanted,kind+' intended value');
  assert.equal(await range(room).inputValue(),room?'10':'25','confirmed display stays at original value before feedback');
  const after=await confirm(request,snapshot.states);assert.equal(Number(await range(false).inputValue()),after.actual,'actual clamped mean, not requested preview');
  if(room)assert.equal(after.updated[1],40,'own-room leaves follower raw volume unchanged');
  trace.push({kind,requested:wanted,actual:after.actual,rooms:after.updated});
 }
 await cdp.detach();fs.writeFileSync(path.join(out,'guard-traces.json'),JSON.stringify(trace,null,2));fs.writeFileSync(path.join(out,'gesture-owning-requests.json'),JSON.stringify(requests,null,2));results.push('17 stale-intent/cancellation fences, benign sort/unrelated volume, clamp extremes, own-room, tap, stepper and real keyboard');
}
