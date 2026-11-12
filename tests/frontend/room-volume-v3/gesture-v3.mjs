// Actual browser mouse/touch gestures; never set range values or dispatch input/change.
export async function run({page,browser,manager,publishNative,snapshot,services,nativeCalls,out,fs,path,assert,results}){
 const traces=[];const slider=manager.locator('[data-group-id=one] [data-master] input');
 for(const touch of [false,true])for(const refresh of [false,true]){
  publishNative(snapshot.states);await page.waitForTimeout(130);
  await slider.scrollIntoViewIfNeeded();
  await slider.evaluate(e=>{window.__range=e;window.__events=[];for(const t of ['pointerdown','pointermove','pointerup','pointercancel','input','change','lostpointercapture'])e.addEventListener(t,v=>window.__events.push({type:t,trusted:v.isTrusted,pointerType:v.pointerType,value:e.value,connected:e.isConnected}));});
  const box=await slider.boundingBox(),before=services.length,start=Number(await slider.inputValue()),x=p=>box.x+8+(box.width-16)*p/100,y=box.y+box.height/2;
  const cdp=await browser.newCDPSession(page);
  const send=async(type,pos)=>touch?cdp.send('Input.dispatchTouchEvent',{type,touchPoints:type==='touchEnd'?[]:[{x:x(pos),y}],modifiers:0}):type==='touchStart'?page.mouse.move(x(pos),y).then(()=>page.mouse.down()):type==='touchEnd'?page.mouse.up():page.mouse.move(x(pos),y);
  await send('touchStart',start);
  for(const p of [35,45,55,65]){await send('touchMove',p);if(refresh){const next=structuredClone(snapshot.states);next['media_player.synthetic_speaker_6'].attributes.media_title='Synthetic benign refresh '+p;publishNative(next);}await page.waitForTimeout(65);}
  const held=await page.evaluate(()=>({originalConnected:window.__range.isConnected,value:window.__range.value,events:window.__events}));
  await send('touchEnd',65);await page.waitForTimeout(150);
  const data={touch,refresh,held,after:await page.evaluate(()=>({connected:window.__range.isConnected,events:window.__events})),calls:nativeCalls.slice(before)};traces.push(data);
  // Confirm through the synthetic native channel, using additive delta/clamps.
  if(services.length===before+1){const request=nativeCalls.at(-1),wanted=request.data.volume_percent,next=structuredClone(snapshot.states),members=next[snapshot.target].attributes.group_members,values=members.map(id=>Math.round(next[id].attributes.loxone_room_volume_level*100)),mean=Math.round(values.reduce((a,b)=>a+b,0)/values.length),newValues=values.map(v=>Math.min(100,Math.max(0,v+wanted-mean))),actual=Math.round(newValues.reduce((a,b)=>a+b,0)/values.length);
   members.forEach((id,i)=>{next[id].attributes.loxone_room_volume_level=newValues[i]/100;next[id].attributes.volume_level=newValues[i]/100;next[id].attributes.loxone_group_volume_level=actual/100;});publishNative(next);await page.waitForTimeout(120);
  }
  await cdp.detach();
 }
 fs.writeFileSync(path.join(out,'gesture-traces.json'),JSON.stringify(traces,null,2));
 assert.ok(traces.every(t=>t.held.originalConnected),'benign refresh must retain actual range node throughout real held mouse/touch drag');
 assert.ok(traces.every(t=>t.calls.length===1&&t.calls[0].domain==='loxone'&&t.calls[0].service==='audio_group_volume'),'exactly one intended group volume service per genuine release');
 assert.ok(traces.every(t=>t.calls[0].data.volume_percent===65),'release value follows actual drag endpoint');
 assert.ok(traces.every(t=>t.after.events.some(e=>e.type==='input'&&e.trusted)&&t.after.events.some(e=>e.type==='change'&&e.trusted)),'real trusted browser input/change evidence, not synthetic value assignment');
 results.push('real mouse and CDP mobile touch drags with/without benign HA refresh');
}
