// Party-sized real native modal; all state originates from owning HA synthetic export.
export async function run(ctx){
 const {page,browser,manager,dialog,publishNative,snapshot,snapshots,services,nativeCalls,out,fs,path,assert,results}=ctx;
 const party=snapshots.find(s=>s.scenario==='party12');assert.ok(party,'Require owning HA12-room export');
 const ids=Object.keys(party.states),leader=party.states[party.target].attributes.group_members[0],group=party.states[leader].attributes.loxone_group_control.group_id;
 const initialHass=await manager.evaluate(m=>({user:m.hass.user,config:m.hass.config,entities:m.hass.entities}));
 let states=structuredClone(party.states);const calls=[],geometry=[],events=[];
 const reset=async()=>{states=structuredClone(party.states);publishNative(states);await manager.evaluate((m,h)=>{m.hass={...m.hass,...h,connected:true};m._mode='overview';m.render();},initialHass);await page.waitForTimeout(150);};
 const cdp=await browser.newCDPSession(page),touch=async(type,points)=>cdp.send('Input.dispatchTouchEvent',{type,touchPoints:points});
 const control=room=>manager.locator(room?`[data-entity="${ids[0]}"] input`:`[data-group-id="${group}"] [data-master] input`);
 const confirm=async call=>{
  const room=call.service==='audio_room_volume',members=states[leader].attributes.group_members;
  const values=members.map(i=>Math.round(states[i].attributes.loxone_room_volume_level*100)),mean=Math.floor((2*values.reduce((a,b)=>a+b,0)+values.length)/(2*values.length));
  const wanted=room?call.data.volume_percent:Math.round(call.data.volume_level*100),updated=values.map((v,n)=>room?(members[n]===call.target.entity_id?wanted:v):Math.max(0,Math.min(100,v+wanted-mean))),actual=Math.floor((2*updated.reduce((a,b)=>a+b,0)+updated.length)/(2*updated.length));
  members.forEach((i,n)=>{states[i].attributes.loxone_room_volume_level=updated[n]/100;states[i].attributes.volume_level=actual/100;});publishNative(states);
  await page.waitForFunction(()=>!document.querySelector('home-assistant').shadowRoot.querySelector('loxone-group-manager-dialog')._manager._pending);
 };
 for(const [width,height]of [[390,844],[844,390],[1280,900]])for(const dark of[false,true]){
  await page.setViewportSize({width,height});await reset();
  for(const [n,s]of Object.entries(states))s.attributes.friendly_name=`Long synthetic room ${n.split('_').at(-1)} – listening and entertainment area`;
  publishNative(states);await manager.evaluate((m,dark)=>{m.style.setProperty('--primary-text-color',dark?'#eee':'#212121');m.style.setProperty('--card-background-color',dark?'#202020':'#fff');m.style.fontSize='125%';},dark);await page.waitForTimeout(150);
  const measured=await manager.evaluate(m=>[...m.shadowRoot.querySelectorAll('[data-master],.members>.row')].map(r=>{const v=r.querySelector('.vol'),i=v.querySelector('input'),q=e=>e.getBoundingClientRect().toJSON();return {row:q(r),volume:q(v),input:q(i),steps:[...v.querySelectorAll('button')].map(q),identity:[...r.children].filter(e=>e!==v).map(q)};}));
  assert.equal(measured.length,13);for(const r of measured){assert.ok(r.volume.width>=r.row.width-2);assert.ok(r.input.width>=r.volume.width-2);assert.ok(r.identity.every(i=>i.bottom<=r.volume.y+1));assert.ok(r.steps.every(b=>b.width>=44&&b.height>=44));assert.ok(r.row.x>=0&&r.row.right<=width);}
  geometry.push({width,height,dark,rows:measured});await page.screenshot({path:path.join(out,`party-${width}-${dark}.png`)});
 }
 await page.setViewportSize({width:390,height:844});await reset();
 for(const room of[false,true])for(const kind of['mouse','touch']){
  await reset();const slider=control(room);await slider.scrollIntoViewIfNeeded();const b=await slider.boundingBox(),start=Number(await slider.inputValue()),x=p=>b.x+8+(b.width-16)*p/100,y=b.y+b.height/2,before=services.length;
  await slider.evaluate(e=>{window.__partyRange=e;window.__partyEvents=[];for(const t of['pointerdown','pointerup','input','change'])e.addEventListener(t,v=>window.__partyEvents.push({type:t,trusted:v.isTrusted,value:e.value}));});
  if(kind==='touch')await touch('touchStart',[{x:x(start),y,id:1}]);else{await page.mouse.move(x(start),y);await page.mouse.down();}
  for(const p of[35,45,55,65]){if(kind==='touch')await touch('touchMove',[{x:x(p),y,id:1}]);else await page.mouse.move(x(p),y);states[ids[11]].attributes.media_title='Benign party feedback '+p;publishNative(states);await page.waitForTimeout(45);}
  assert.ok(await page.evaluate(()=>window.__partyRange.isConnected));assert.equal(services.length,before);
  if(kind==='touch')await touch('touchEnd',[]);else await page.mouse.up();await page.waitForTimeout(120);
  assert.equal(services.length,before+1);const call=nativeCalls.at(-1);assert.equal(call.service,room?'audio_room_volume':'volume_set');assert.equal(call.target.entity_id,room?ids[0]:leader);assert.equal(room?call.data.volume_percent:Math.round(call.data.volume_level*100),65);
  const trace=await page.evaluate(()=>window.__partyEvents);assert.ok(trace.some(e=>e.type==='input'&&e.trusted)&&trace.some(e=>e.type==='change'&&e.trusted));events.push({room,kind,trace});calls.push(call);await confirm(call);
 }
 for(const room of[false,true])for(const kind of['keyboard','stepper']){
  await reset();const slider=control(room),before=services.length,start=Number(await slider.inputValue());
  if(kind==='keyboard'){await slider.focus();await page.keyboard.press('ArrowRight');}else await slider.locator('..').locator('[data-action=volume-plus]').click();
  await page.waitForTimeout(100);assert.equal(services.length,before+1);const call=nativeCalls.at(-1);assert.equal(room?call.data.volume_percent:Math.round(call.data.volume_level*100),start+1);calls.push(call);await confirm(call);
 }
 // Real A-B-A and two-contact release revoke whole gestures with no stale writes.
 for(const kind of['auth-aba','multitouch']){
  await reset();const slider=control(false);await slider.scrollIntoViewIfNeeded();const b=await slider.boundingBox(),y=b.y+b.height/2,before=services.length,x=b.x+b.width*.3;
  await touch('touchStart',[{x,y,id:1}]);await touch('touchMove',[{x:b.x+b.width*.6,y,id:1}]);
  if(kind==='auth-aba')await manager.evaluate(m=>{const h=m.hass;m.hass={...h,user:{...h.user,id:'synthetic-revoked'}};m.hass=h;});
  else {await touch('touchStart',[{x:b.x+b.width*.6,y,id:1},{x:b.x+b.width*.8,y,id:2}]);await touch('touchEnd',[{x:b.x+b.width*.8,y,id:2}]);}
  await touch('touchEnd',[]);await page.waitForTimeout(140);assert.equal(services.length,before,kind+' no stale dispatch');
 }
 // All12 are reachable through trusted touch, while meaningful presentation churn continues.
 await reset();const content=manager.locator('.content');
 for(let n=0;n<14;n++){
  const b=await content.boundingBox(),x=b.x+30,bottom=b.bottom||b.y+b.height-12,top=b.y+12;
  await touch('touchStart',[{x,y:bottom-12,id:1}]);for(let i=1;i<=7;i++){await touch('touchMove',[{x,y:bottom-12-(bottom-top-12)*i/7,id:1}]);states[ids[11]].attributes.friendly_name='Last synthetic room '+n+'-'+i;publishNative(states);await page.waitForTimeout(30);}await touch('touchEnd',[]);await page.waitForTimeout(90);
 }
 const end=await content.evaluate(e=>({top:e.scrollTop,extent:e.scrollHeight-e.clientHeight}));assert.ok(end.top>=end.extent-4,'Real touch must reach the last party member/actions');
 for(const action of['add','destroy']){const b=manager.locator(`[data-group-id="${group}"] [data-action=${action}]`);assert.ok(await b.isVisible());const r=await b.boundingBox(),c=await content.boundingBox();assert.ok(r.y>=c.y&&r.y+r.height<=c.y+c.height);}
 await cdp.detach();fs.writeFileSync(path.join(out,'party-geometry.json'),JSON.stringify(geometry,null,2));fs.writeFileSync(path.join(out,'party-events.json'),JSON.stringify(events,null,2));fs.writeFileSync(path.join(out,'party-owning-requests.json'),JSON.stringify(calls,null,2));
 results.push('All12/fullwidth/longnames/lightdark/125% at3viewports; trusted mouse/touch+feedback, keyboard/steppers, authABA/multitouch cancellation, scrolling, exact8volume calls');
}
