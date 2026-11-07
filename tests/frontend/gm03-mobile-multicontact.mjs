// V4: establish and release capture with actual nonstationary trusted movement.
import {run as strict} from './gm03-mobile-multicontact-cases.mjs';
export async function run(ctx){
 await strict(ctx);
 const {page,browser,manager,dialog,publishNative,snapshot,services,nativeCalls,out,fs,path,assert,results}=ctx;
 await page.setViewportSize({width:900,height:1800});
 const cdp=await browser.newCDPSession(page),records=[];
 const baseline=await manager.evaluate(m=>({user:m.hass.user,entities:m.hass.entities,config:m.hass.config}));
 const range=room=>manager.locator(room?'[data-entity="media_player.synthetic_speaker_1"] input':'[data-group-id=one] [data-master] input');
 const point=async(loc,p,id)=>{await loc.scrollIntoViewIfNeeded();const b=await loc.boundingBox();return {x:b.x+(p===null?b.width/2:8+(b.width-16)*p/100),y:b.y+b.height/2,id};};
 const send=async(type,points)=>{await cdp.send('Input.dispatchTouchEvent',{type,touchPoints:points});await page.waitForTimeout(80);};
 const scalar=c=>({domain:c.domain,service:c.service,data:c.data,target:c.target});
 const reset=async()=>{publishNative(snapshot.states);await manager.evaluate((m,h)=>{m.hass={...m.hass,...h,connected:true};m._mode='overview';m.render();},baseline);await dialog.evaluate(d=>{if(!d._open)d.showDialog({entity:'media_player.synthetic_speaker_1'});});await page.waitForTimeout(120);};
 for(const kind of ['own-room-primary','cross-group','secondary-button','secondary-lostcapture','primary-lostcapture','cancel-both','nonprimary-only','nonprimary-cancel']){
  await reset();const room=kind==='own-room-primary',n=services.length;
  // Revoke/restore focus never promotes a detached range's stale native change.
  await range(room).evaluate(e=>{window.__extraAbort?.abort();window.__extraAbort=new AbortController();window.__extraRange=e;window.__extraEvents=[];window.__secondaryTarget=null;for(const t of ['pointerdown','pointermove','pointerup','pointercancel','gotpointercapture','lostpointercapture','input','change','touchend','touchcancel'])window.addEventListener(t,v=>{if(t==='pointerdown'&&v.isPrimary===false)window.__secondaryTarget=v.composedPath()[0];window.__extraEvents.push({type:t,trusted:v.isTrusted,pointer:v.pointerId,primary:v.isPrimary,value:e.value,connected:e.isConnected,touches:v.touches?.length});},{capture:true,signal:window.__extraAbort.signal});e.addEventListener('change',v=>window.__extraEvents.push({type:'node-change',trusted:v.isTrusted,value:e.value,connected:e.isConnected}));});
  let a=await point(range(room),room?10:25,51),b=await point(range(room),65,51),s=await point(range(room),80,52);
  if(kind==='cross-group')s=await point(manager.locator('[data-group-id=outside] [data-master] input'),80,52);
  if(kind==='secondary-button')s=await point(manager.locator('[data-action=create]'),null,52);
  if(kind.startsWith('nonprimary')){a=await point(manager.locator('[data-action=create]'),null,51);b=a;}
  await send('touchStart',[a]);if(!kind.startsWith('nonprimary')){await send('touchMove',[b]);assert.equal(await range(room).inputValue(),'65',kind+' primary actually moved65');}
  await send('touchStart',[b,s]);assert.equal(services.length,n,kind+' no held dispatch');
  const pre=await page.evaluate(()=>window.__extraEvents);assert.ok(pre.some(e=>e.type==='pointerdown'&&e.primary&&e.trusted)&&pre.some(e=>e.type==='pointerdown'&&!e.primary&&e.trusted),kind+' two trusted pointerdown precondition');
  let capture=null;
  if(kind.endsWith('lostcapture')){
   // Establish pending capture with trusted movement. Secondary default capture
   // is not guaranteed yet; use the real DOM capture API, not a fake event.
   capture=await page.evaluate(kind=>{const id=window.__extraEvents.find(e=>e.type==='pointerdown'&&e.primary===(kind==='primary-lostcapture')).pointer;const target=kind==='primary-lostcapture'?window.__extraRange:window.__secondaryTarget;target.setPointerCapture(id);return {id,has:target.hasPointerCapture(id)};},kind);
   const moving=kind==='primary-lostcapture'?b:s;moving.x+=2;await send('touchMove',[b,s]);
   await page.evaluate(({id,primary})=>(primary?window.__extraRange:window.__secondaryTarget).releasePointerCapture(id),{id:capture.id,primary:kind==='primary-lostcapture'});
   moving.x+=2;await send('touchMove',[b,s]);
  }
  if(kind==='cancel-both'||kind==='nonprimary-cancel')await send('touchCancel',[]);
  else {await send('touchEnd',[b]);assert.equal(services.length,n,kind+' first release zero');await send('touchEnd',[]);}
  await page.waitForTimeout(100);const events=await page.evaluate(()=>window.__extraEvents);
  records.push({kind,capture,calls:nativeCalls.slice(n).map(scalar),events});fs.writeFileSync(path.join(out,'strict-supplements-v2.json'),JSON.stringify(records,null,2));
  assert.equal(services.length,n,kind+' zero total after both releases');
  if(capture){assert.ok(capture.has);assert.ok(events.some(e=>e.type==='lostpointercapture'&&e.pointer===capture.id&&e.trusted),kind+' actual trusted lostcapture required');}
  if(kind==='cancel-both')assert.ok(events.some(e=>e.type==='pointercancel'&&e.primary&&e.trusted)&&events.some(e=>e.type==='pointercancel'&&!e.primary&&e.trusted),'both actual native cancellation paths observed');
  // Supplemental stale callback injection, NOT gesture acceptance: no value
  // assignment/dispatchEvent. Trusted contact assertions above stand alone.
  await page.evaluate(()=>window.__extraRange.onchange());await page.waitForTimeout(70);assert.equal(services.length,n,kind+' retained stale change callback cannot resurrect');
  await range(room).focus();await page.keyboard.press('ArrowRight');await page.waitForTimeout(80);assert.equal(services.length,n+1,kind+' keyboard recovers without another pointer');
  const call=nativeCalls.at(-1);assert.equal(room?call.data.volume_percent:Math.round(call.data.volume_level*100),room?11:26);assert.equal(call.service,room?'audio_room_volume':'volume_set');assert.equal(call.target.entity_id,'media_player.synthetic_speaker_1');
  const next=structuredClone(snapshot.states);const values=room?[11,40]:[11,41],mean=26;for(const [j,i]of [1,2].entries()){next['media_player.synthetic_speaker_'+i].attributes.loxone_room_volume_level=values[j]/100;next['media_player.synthetic_speaker_'+i].attributes.volume_level=mean/100;}publishNative(next);await page.waitForFunction(()=>!document.querySelector('home-assistant').shadowRoot.querySelector('loxone-group-manager-dialog')._manager._pending);
  records.push({kind,phase:'keyboard-recovery',call:scalar(call)});fs.writeFileSync(path.join(out,'strict-supplements-v2.json'),JSON.stringify(records,null,2));
 }
 await cdp.detach();results.push('eight scoped native capture/cancel/own-room/cross-control and keyboard recovery supplements; stale callback separately injected');
}
