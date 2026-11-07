// Additive owner-UI oracle. Old browser.mjs/browser-room.mjs remain immutable.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import http from 'node:http';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const require=createRequire(path.resolve(process.env.FRONTEND_NODE_MODULES,'esbuild/package.json'));
const {build}=require('esbuild'),{chromium}=require('playwright-core');
const out=path.resolve(process.argv[2]),slice=process.argv[3]||'immediate';fs.mkdirSync(out,{recursive:false});
const source=path.join(root,'adapters/pyloxone/frontend/src/group-control-card.js');
const statesPath=path.join(root,'tests/frontend/room-ui-states.json');
const sha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const snapshots=JSON.parse(fs.readFileSync(statesPath)),snapshot=snapshots.find(s=>s.scenario==='confirmed');
const [a,b,c,d,e,f]=Object.keys(snapshot.states);const results=[],errors=[];let browser,server,page;
try{
 await build({entryPoints:[source],outfile:path.join(out,'card.js'),bundle:true,format:'esm',target:'es2022',legalComments:'inline'});
 server=http.createServer((req,res)=>{if(req.url==='/card.js'){res.setHeader('Content-Type','application/javascript');res.end(fs.readFileSync(path.join(out,'card.js')));}else if(req.url==='/')res.end('<!doctype html><meta name="viewport" content="width=device-width, initial-scale=1"><script type="module" src="/card.js"></script>');else res.writeHead(404).end();});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin=`http://127.0.0.1:${server.address().port}`;
 browser=await chromium.launchPersistentContext(path.join(out,'browser-profile'),{executablePath:process.env.CHROMIUM_EXECUTABLE||'/snap/bin/chromium',headless:true,serviceWorkers:'block',args:['--no-sandbox','--disable-dev-shm-usage']});
 const context=browser;
 await context.route('**/*',r=>r.request().url().startsWith(origin+'/')?r.continue():r.abort());
 page=await context.newPage();page.on('pageerror',e=>errors.push(String(e)));await page.goto(origin);
 await page.waitForFunction(()=>!!customElements.get('loxone-group-control-card'));
 await page.evaluate(s=>{
  window.calls=[];window.allCalls=[];window.mode='immediate';window.release=null;
  const card=document.createElement('loxone-group-control-card');card.setConfig({entity:s.target});document.body.append(card);window.card=card;
  window.setHass=s=>{window.snapshot=structuredClone(s);card.hass={states:s.states,entities:s.entities,user:{id:'synthetic'},connected:true,callService:(domain,service,data,target)=>{
   const request={domain,service,data:structuredClone(data),target:structuredClone(target)};window.calls.push(request);
   const groups=[...new Map(Object.values(s.states).map(s=>s.attributes.loxone_group_control).filter(d=>d&&d.members.length>1).map(d=>[d.group_id,{id:d.group_id,members:[...d.members]}])).values()];
   window.allCalls.push({...request,groups,staticEntities:Object.values(s.states).filter(s=>!s.attributes.loxone_group_control).map(s=>s.entity_id),mode:window.mode,states:structuredClone(s.states)});
   if(window.mode==='reject')return Promise.reject(new Error('Synthetic native rejection'));
   if(window.mode==='defer')return new Promise(resolve=>window.release=resolve);return Promise.resolve();
  }};};
  window.membership=groups=>{
   const s=structuredClone(window.snapshot);
   for(const [id,state] of Object.entries(s.states)){
    const d=state.attributes.loxone_group_control;if(!d)continue;
    const group=groups.find(g=>g.members.includes(id));d.members=group?[...group.members]:[id];d.group_id=group?.id||null;
    d.revision+='-feedback';state.attributes.group_members=[...d.members];
   }window.setHass(s);
  };window.setHass(s);
 },snapshot);
 const card=page.locator('loxone-group-control-card'),row=id=>card.locator(`[data-entity="${id}"]`),check=id=>row(id).locator('input[type=checkbox]');
 const reset=async(s=snapshot)=>page.evaluate(s=>{window.mode='immediate';window.calls=[];window.card.setConfig({entity:s.target});window.setHass(structuredClone(s));window.card.open();},s);
 const settled=async()=>page.waitForFunction(()=>!window.card._pending);
 await card.locator('[data-action=open]').click();await card.locator('dialog[open]').waitFor();
 assert.equal(await page.evaluate(()=>window.calls.length),0,'render/open never dispatches');
 assert.equal(await card.locator('[data-action=apply],[data-action=reset]').count(),0,'Immediate UI must have no Apply or Reset');
 await page.evaluate(()=>window.mode='defer');
 await check(d).click();await page.waitForFunction(()=>!!window.release);
 assert.deepEqual(await page.evaluate(()=>window.calls[0]),{domain:'media_player',service:'join',data:{group_members:[d]},target:{entity_id:c}});
 assert.equal(await check(d).isChecked(),false,'No optimistic membership while service pending');
 assert.equal(await card.locator('input:not(:disabled),[data-action=row-play]:not(:disabled)').count(),0);
 assert.match(await card.locator('[role=status]').innerText(),/Updating group.*Please wait/i);
 assert.equal(await card.locator('dialog').getAttribute('aria-busy'),'true');
 assert.equal(await card.locator('[role=status]').evaluate(el=>getComputedStyle(el).position),'sticky');
 assert.ok(Number(await row(d).locator('input[type=range]').evaluate(el=>getComputedStyle(el).opacity))<=.25,'genuine pending controls substantially dimmed');
 assert.equal(await card.locator('[role=status]').evaluate(el=>getComputedStyle(el).opacity),'1','banner must not inherit dimming');
 await page.keyboard.press('Escape');assert.equal(await card.locator('dialog[open]').count(),1,'pending keyboard dismissal blocked');
 await check(d).evaluate(el=>{el.checked=true;el.onchange(new Event('change'));});
 assert.equal(await page.evaluate(()=>window.calls.length),1,'duplicate events cannot queue');
 await page.evaluate(()=>window.release());await page.waitForTimeout(150);
 assert.equal(await page.evaluate(()=>window.card._pending),true,'ACK alone is not membership confirmation');
 assert.equal(await check(d).isChecked(),false);
 await page.evaluate(members=>window.membership([{id:'native',members}]),[a,c,b,d]);await settled();
 assert.equal(await check(d).isChecked(),true);
 assert.deepEqual(await card.locator('[data-section=members] .speaker-name').allTextContents(),['alpha','Alpine','BRAVO','Zulu']);
 await page.evaluate(()=>{window.calls=[];window.mode='defer';window.release=null;});await check(d).click();
 assert.deepEqual(await page.evaluate(()=>window.calls[0]),{domain:'media_player',service:'unjoin',data:{},target:{entity_id:d}});
 assert.equal(await check(d).isChecked(),true);
 await page.evaluate(members=>{window.membership([{id:'native',members}]);window.release();},[a,c,b]);await settled();
 assert.equal(await check(d).isChecked(),false);
 await page.evaluate(()=>{window.calls=[];window.mode='reject';});await check(d).click();await settled();
 assert.match(await card.locator('[role=alert]').innerText(),/Synthetic native rejection/);assert.equal(await check(d).isChecked(),false);
 assert.equal(await page.evaluate(()=>window.calls.length),1,'rejection sends no rollback/retry');
 await reset();await check(d).click();await settled();
 assert.match(await card.locator('[role=alert]').innerText(),/not confirmed/);assert.equal(await check(d).isChecked(),false);
 assert.equal(await page.evaluate(()=>window.calls.length),1,'timeout sends no rollback/retry');
 results.push('immediate one-event join/unjoin; no Apply/Reset; no optimistic ACK membership; pending duplicate suppression; rejection and native-confirmation timeout without retry/rollback');
 if(slice!=='immediate'){
  await reset();
  await check(d).evaluate(el=>{window.oldCheck=el.onchange;window.oldInput=el;});
  await page.evaluate(()=>{window.card.hass.user={id:'replacement-user'};window.oldInput.checked=true;window.oldCheck(new Event('change'));});
  assert.equal(await page.evaluate(()=>window.calls.length),0,'unrendered auth change must invalidate checkbox binding');
  await reset();await check(d).evaluate(el=>{window.oldCheck=el.onchange;window.oldInput=el;});
  await page.evaluate(()=>{window.membership([]);window.oldInput.checked=true;window.oldCheck(new Event('change'));});
  assert.equal(await page.evaluate(()=>window.calls.length),0,'saved stale callback cannot act on changed topology');
  await reset();const stale=await row(d).elementHandle();
  await page.evaluate(id=>{const s=structuredClone(window.snapshot);s.states[id].state='unavailable';window.setHass(s);},d);
  await reset();await stale.evaluate(el=>{const c=el.querySelector('input[type=checkbox]');c.checked=true;c.onchange(new Event('change'));el.querySelector('[data-action=row-play]').onclick();const v=el.querySelector('input[type=range]');v.value='71';v.onchange();});
  assert.equal(await page.evaluate(()=>window.calls.length),0,'detached control cannot act even after same entity returns');
  for(const change of ['auth','owner','capability','external','connection']){
   await reset();await page.evaluate(()=>{window.mode='defer';window.release=null;});await check(d).click();
   await page.evaluate(({change,a,c,d})=>{
    window.lateRelease=window.release;
    if(change==='auth')window.card.hass={...window.card.hass,user:{id:'new-auth'}};
    if(change==='connection')window.card.hass={...window.card.hass,connected:false};
    if(change==='external')window.membership([{id:'new-topology',members:[c,d]}]);
    if(change==='owner'||change==='capability'){
     const s=structuredClone(window.snapshot);
     if(change==='owner')s.states[c].attributes.loxone_group_control.owner='foreign-owner';
     else s.states[d].attributes.supported_features&=~524288;
     window.setHass(s);
    }
   },{change,a,c,d});
   await page.waitForFunction(()=>!window.card._pending,{timeout:2000});
   assert.match(await card.locator('[role=alert]').innerText(),/changed|unavailable|disconnected/i);
   assert.equal(await page.evaluate(()=>window.calls.length),1,'revocation/external change never sends compensation');
   await reset();await page.evaluate(()=>window.lateRelease());await page.waitForTimeout(100);
   assert.equal(await page.evaluate(()=>window.calls.length),0,'late old completion cannot replay');
   assert.equal(await card.locator('[role=alert]').innerText(),'','late old completion cannot poison new context');
  }
  // Never-settling HA promise is also bounded, with no native membership invented.
  await reset();await page.evaluate(()=>{window.mode='defer';window.release=null;});await check(d).click();await settled();
  assert.match(await card.locator('[role=alert]').innerText(),/not confirmed|timed out/);
  assert.equal(await check(d).isChecked(),false);assert.equal(await page.evaluate(()=>window.calls.length),1);
  await page.evaluate(()=>window.release());await reset();
  // Detach while awaiting; its eventual callback cannot affect a reattached card.
  await page.evaluate(()=>{window.mode='defer';window.release=null;});await check(d).click();
  await page.evaluate(()=>{window.card.remove();document.body.append(window.card);window.setHass(window.snapshot);window.release();});
  await settled();assert.equal(await check(d).isChecked(),false);
  assert.equal(await page.evaluate(()=>window.calls.length),1);
  await reset();
  results.push('auth/owner/capability/connection/external topology invalidation during pending service; detached and saved stale handlers; bounded never-settling service; late completion isolation');
 }
 if(['icons','selector','all'].includes(slice)){
  for(const id of [a,b,c,d])for(const playing of [false,true]){
   const s=structuredClone(snapshot);s.states[id].state=playing?'playing':'paused';await reset(s);
   const button=row(id).locator('[data-action=row-play]'),icon=button.locator('ha-svg-icon');
   assert.equal(await icon.count(),1,'room transport uses native HA SVG icon component, not emoji');
   assert.equal(await icon.evaluate(el=>el.path),playing?'M14,19H18V5H14M6,19H10V5H6V19Z':'M8,5.14V19.14L19,12.14L8,5.14Z');
   assert.equal(await button.innerText(),'');
   assert.equal(await button.getAttribute('aria-label'),`${playing?'Pause':'Play'} ${s.states[id].attributes.friendly_name} only`);
   await button.focus();await page.keyboard.press('Enter');await settled();
   assert.deepEqual(await page.evaluate(()=>window.calls[0]),{domain:'loxone',service:'audio_room_transport',data:{action:playing?'pause':'play'},target:{entity_id:id}});
   assert.equal(await page.evaluate(id=>window.card.hass.states[id].state,id),s.states[id].state,'No playback fabricated on ACK');
  }
  for(const playing of [false,true]){
   const s=structuredClone(snapshot);s.states[a].state=playing?'playing':'paused';await reset(s);
   assert.equal(await card.locator('[data-action=group-play] ha-svg-icon').count(),1);
   await card.locator('[data-action=group-play]').click();await settled();
   assert.deepEqual(await page.evaluate(()=>window.calls[0]),{domain:'media_player',service:playing?'media_pause':'media_play',data:{},target:{entity_id:a}});
  }
  await reset();results.push('native HA SVG component and exact standard MDI play/pause paths; room-only leader/follower/independent semantics and whole-group top transport; keyboard and ACK truth (native rendering proven separately)');
 }
 if(['selector','all'].includes(slice)){
  const select=card.locator('[data-action=context]');
  assert.equal(await select.count(),1,'Obvious runtime room/group selector is required');
  assert.deepEqual(await select.locator('option').evaluateAll(els=>els.map(e=>e.value)),[b,d,c,a]);
  assert.equal(await select.inputValue(),c);
  await check(b).evaluate(el=>{window.oldInput=el;window.oldCheck=el.onchange;});
  await select.selectOption(d);
  assert.equal(await page.evaluate(()=>window.calls.length),0,'context choice is read-only');
  assert.equal(await check(d).isChecked(),true);assert.equal(await check(d).isDisabled(),true);
  assert.equal(await check(c).isChecked(),false);assert.equal(await check(c).isDisabled(),false);
  await page.evaluate(()=>{window.oldInput.checked=false;window.oldCheck(new Event('change'));});
  assert.equal(await page.evaluate(()=>window.calls.length),0,'old checkbox cannot apply in a newly selected context');
  // Two independent rooms form a fresh group without the configured initial anchor.
  await page.evaluate(({a,c})=>window.membership([{id:'anchor',members:[a,c]}]),{a,c});
  await page.evaluate(()=>{window.calls=[];window.mode='defer';window.release=null;});await check(b).click();
  assert.equal(await select.isDisabled(),true);
  await select.evaluate((el,c)=>{el.value=c;el.onchange(new Event('change'));},c);
  assert.equal(await select.inputValue(),d,'pending switch rejected, not queued');
  assert.deepEqual(await page.evaluate(()=>window.calls[0]),{domain:'media_player',service:'join',data:{group_members:[b]},target:{entity_id:d}});
  await page.evaluate(({a,b,c,d})=>{window.membership([{id:'anchor',members:[a,c]},{id:'new-without-anchor',members:[d,b]}]);window.release();},{a,b,c,d});await settled();
  assert.deepEqual(await card.locator('[data-section=members] .speaker-name').allTextContents(),['alpha','Alpine']);
  assert.equal(await check(c).isChecked(),false);
  await page.evaluate(()=>window.calls=[]);await select.selectOption(b);
  assert.equal(await page.evaluate(()=>window.calls.length),0);
  assert.match(await card.locator('[data-role=group]').innerText(),/Leader: Alpine/,'selecting follower preserves native leader');
  await page.evaluate(()=>{window.mode='defer';window.release=null;});await check(d).click();
  assert.deepEqual(await page.evaluate(()=>window.calls[0]),{domain:'media_player',service:'unjoin',data:{},target:{entity_id:d}});
  await page.evaluate(({a,c})=>{window.membership([{id:'anchor',members:[a,c]}]);window.release();},{a,c});await settled();
  assert.deepEqual(await card.locator('[data-section=members] .speaker-name').allTextContents(),['alpha']);
  // A different already-existing native group, not just a new independent group.
  await reset(snapshots.find(s=>s.scenario==='other-group'));await select.selectOption(d);
  assert.equal(await page.evaluate(()=>window.calls.length),0);
  assert.deepEqual(await card.locator('[data-section=members] .speaker-name').allTextContents(),['Alpine','charlie']);
  assert.match(await card.locator('[data-role=group]').innerText(),/Leader: charlie/);
  await page.evaluate(id=>{const s=structuredClone(window.snapshot);s.states[id].state='unavailable';window.setHass(s);},d);
  assert.equal(await select.inputValue(),d,'unavailable selection does not silently switch');
  assert.equal(await card.locator('input[type=range]').count(),0);
  await select.selectOption(c);assert.equal(await page.evaluate(()=>window.calls.length),0);
  assert.deepEqual(await card.locator('[data-section=members] .speaker-name').allTextContents(),['alpha','BRAVO','Zulu']);
  assert.equal(await page.evaluate(()=>window.card._config.entity),c,'transient selection never writes config');
  assert.match(await card.locator('[data-role=context-help]').innerText(),/selected room.*remain|selected room.*included/i);
  await reset();await select.selectOption(c);
  results.push('read-only runtime eligible room selection; no stale context replay; pending switch rejected; fresh group excluding initial anchor; existing other group and follower native leader preservation; leader removal from another context; unavailable context recovery; no config writes');
 }
 if(['volume','all'].includes(slice)){
  await reset();const plus=row(b).locator('[data-action=volume-plus]'),minus=row(b).locator('[data-action=volume-minus]');
  assert.equal(await plus.count(),1,'one room-only plus button at slider end');assert.equal(await minus.count(),1);
  await page.evaluate(()=>{window.mode='defer';window.release=null;});
  const before=await page.evaluate(id=>Math.round(window.card.hass.states[id].attributes.volume_level*100),b);
  await plus.click();await page.waitForFunction(()=>!!window.release);
  assert.deepEqual(await page.evaluate(()=>window.calls[0]),{domain:'media_player',service:'volume_set',data:{volume_level:(before+1)/100},target:{entity_id:b}});
  assert.equal(await row(b).locator('output').innerText(),before+'%','nudge never invents reported volume');
  await plus.evaluate(el=>el.onclick());assert.equal(await page.evaluate(()=>window.calls.length),1);
  await page.evaluate(()=>window.release());await page.waitForTimeout(160);
  assert.equal(await page.evaluate(()=>window.card._pending),true,'service ACK is not native nudge feedback');
  await page.evaluate(({id,percent})=>{const s=structuredClone(window.snapshot);s.states[id].attributes.volume_level=percent/100;window.setHass(s);},{id:b,percent:before+1});await settled();
  assert.equal(await row(b).locator('output').innerText(),(before+1)+'%');
  results.push('stepper actual click one percentage point exact row target, no optimistic value, repeat blocked through ACK until matching native percent');
  // Immediate completion in the same event turn as authority revocation must
  // not beat the periodic guard and report success.
  await reset();await page.evaluate(()=>window.mode='defer');await plus.click();
  await page.evaluate(id=>{const s=structuredClone(window.snapshot);s.states[id].attributes.volume_level=.01+window.snapshot.states[id].attributes.volume_level;window.setHass(s);window.card.hass={...window.card.hass,user:{id:'revoked-now'}};window.release();},b);
  await settled();assert.match(await card.locator('[role=alert]').innerText(),/authentication|changed/i,'same-turn ACK/native feedback cannot outrun revocation');
  const feedback=async(id,percent)=>page.evaluate(({id,percent})=>{const s=structuredClone(window.snapshot);s.states[id].attributes.volume_level=percent/100;window.setHass(s);},{id,percent});
  // All row positions and both directions, including valid numeric zero and
  // exact bounds. Native order/group membership and other volumes stay intact.
  for(const scenario of ['confirmed','other-group'])for(const id of scenario==='confirmed'?[a,b,c,d]:[d,e])for(const direction of [-1,1]){
   const s=structuredClone(snapshots.find(s=>s.scenario===scenario));s.states[id].attributes.volume_level=direction===1?0:.999;
   await reset(s);const p=direction===1?1:99;
   await row(id).locator(`[data-action=volume-${direction===1?'plus':'minus'}]`).click();
   assert.deepEqual(await page.evaluate(()=>window.calls[0]),{domain:'media_player',service:'volume_set',data:{volume_level:p/100},target:{entity_id:id}});
   assert.equal(await page.evaluate(()=>window.card._pending),true);await feedback(id,p);await settled();
   assert.equal(await card.locator('dialog').getAttribute('aria-busy'),'false');
  }
  for(const bound of [0,100]){
   const s=structuredClone(snapshot);s.states[b].attributes.volume_level=bound/100;await reset(s);
   const outward=row(b).locator(`[data-action=volume-${bound?'plus':'minus'}]`);assert.equal(await outward.isDisabled(),true);await outward.evaluate(el=>el.onclick());
   assert.equal(await page.evaluate(()=>window.calls.length),0,'outward bound step cannot dispatch even with saved callback');
  }
  for(const bad of ['missing',null,'0.5',-0.01,1.01,NaN,Infinity]){
   await reset();await page.evaluate(({id,bad})=>{const s=structuredClone(window.snapshot);if(bad==='missing')delete s.states[id].attributes.volume_level;else s.states[id].attributes.volume_level=bad;window.setHass(s);},{id:b,bad});
   assert.equal(await plus.isDisabled(),true);assert.equal(await minus.isDisabled(),true);assert.equal(await row(b).locator('output').innerText(),'—');
   await plus.evaluate(el=>el.onclick());assert.equal(await page.evaluate(()=>window.calls.length),0);
  }
  const unsupported=structuredClone(snapshot);unsupported.states[b].attributes.supported_features&=~4;await reset(unsupported);assert.equal(await plus.isDisabled(),true);
  await plus.evaluate(el=>el.onclick());assert.equal(await page.evaluate(()=>window.calls.length),0);
  // Reported value is read at actual click time, not captured at last render.
  await reset();await page.evaluate(id=>window.card.hass.states[id].attributes.volume_level=.374,b);await plus.click();
  assert.equal(await page.evaluate(()=>window.calls[0].data.volume_level),.38);await feedback(b,38);await settled();
  // Native confirmation before ACK is insufficient; a later external value
  // wins, and must match again after ACK, not an earlier transient echo.
  await reset();await page.evaluate(()=>window.mode='defer');await plus.click();const requested=await page.evaluate(()=>Math.round(window.calls[0].data.volume_level*100));
  await feedback(b,requested);await page.waitForTimeout(120);assert.equal(await page.evaluate(()=>window.card._pending),true);
  await feedback(b,requested+7);await page.evaluate(()=>window.release());await page.waitForTimeout(120);assert.equal(await page.evaluate(()=>window.card._pending),true);
  await feedback(b,requested);await settled();
  // No confirmation, wrong-room confirmation, rejection and never-settling
  // service all clear truthfully without retry or reported-value rollback.
  for(const mode of ['immediate','reject','defer']){
   await reset();await page.evaluate(mode=>window.mode=mode,mode);await plus.click();await feedback(a,requested);await settled();
   assert.match(await card.locator('[role=alert]').innerText(),/not confirmed|Synthetic native rejection/);
   assert.equal(await page.evaluate(()=>window.calls.length),1);assert.equal(await card.locator('dialog').getAttribute('aria-busy'),'false');
   assert.equal(await row(b).locator('output').innerText(),Math.round(snapshot.states[b].attributes.volume_level*100)+'%');
   if(mode==='defer')await page.evaluate(()=>window.release());
  }
  for(const change of ['auth','connection','owner','capability','membership','context','row-detach','detach']){
   await reset();await page.evaluate(()=>window.mode='defer');await plus.click();
   await page.evaluate(({change,b,d})=>{
    window.lateRelease=window.release;
    if(change==='auth')window.card.hass={...window.card.hass,user:{id:'different'}};
    if(change==='connection')window.card.hass={...window.card.hass,connected:false};
    if(change==='owner'){const s=structuredClone(window.snapshot);s.states[b].attributes.loxone_group_control.owner='foreign';window.setHass(s);}
    if(change==='capability'){const s=structuredClone(window.snapshot);s.states[b].attributes.supported_features&=~4;window.setHass(s);}
    if(change==='membership')window.membership([]);
    if(change==='context'){window.card._selected=d;window.card._render();}
    if(change==='row-detach')window.card._rows.get(b).remove();
    if(change==='detach'){window.card.remove();if(window.card._dialog.getAttribute('aria-busy')!=='false'||window.card.shadowRoot.querySelector('[role=status]').textContent.includes('Please wait'))throw new Error('detached pending banner was not cleared');}
   },{change,b,d});await settled();
   assert.equal(await page.evaluate(()=>window.calls.length),1);await page.evaluate(()=>{if(!window.card.isConnected)document.body.append(window.card);});
   await reset();await page.evaluate(()=>window.lateRelease());await page.waitForTimeout(80);assert.equal(await page.evaluate(()=>window.calls.length),0);
  }
  // Saved handler closures are invalid across auth and read-only context
  // switches, detached same-ID rows, and all pending keyboard/repeat attempts.
  for(const change of ['auth','context','detach','unknown','foreign','busy']){
   await reset();await plus.evaluate(el=>window.savedPlus=el.onclick);
   await page.evaluate(({change,b,d})=>{
    if(change==='auth')window.card.hass.user={id:'changed-without-render'};
    if(change==='context')window.card._choose(d,window.card._contextStamp());
    if(change==='detach')window.card._rows.get(b).remove();
    if(change==='unknown')window.card.hass.states[b].attributes.volume_level='0.4';
    if(change==='foreign')window.card.hass.states[b].attributes.loxone_group_control.owner='foreign';
    if(change==='busy')window.card.hass.states[window.card._entity].attributes.loxone_group_control.busy=true;
    window.savedPlus();
   },{change,b,d});assert.equal(await page.evaluate(()=>window.calls.length),0);
  }
  await reset();await plus.focus();await page.keyboard.press('Enter');
  const keyboardPercent=await page.evaluate(()=>Math.round(window.calls[0].data.volume_level*100));await feedback(b,keyboardPercent);await settled();
  await reset();await plus.focus();await page.keyboard.down('Enter');
  const heldPercent=await page.evaluate(()=>Math.round(window.calls[0].data.volume_level*100));await feedback(b,heldPercent);await settled();
  await page.keyboard.down('Enter');await page.waitForTimeout(80);assert.equal(await page.evaluate(()=>window.calls.length),1,'held key must not autorepeat even after native confirmation');await page.keyboard.up('Enter');
  await plus.click();await feedback(b,heldPercent+1);await settled();assert.equal(await page.evaluate(()=>window.calls.length),2,'a fresh click after release still works');
  results.push('stepper bounds/zero/rounding/latest actual state, all leader/follower/context/independent/other-group row targets; missing/string/nonfinite/out-of-range/unsupported rejection; native-before-ACK and changed-native races; timeout/rejection/never-settling service; authority/context/row/card detach and stale closures; keyboard');
 }
 if(['busy','all'].includes(slice)){
  const geometry=[];
  for(const [theme,background,color] of [['light','#ffffff','#212121'],['dark','#202020','#eeeeee']])for(const width of [320,768]){
   await reset();await page.setViewportSize({width,height:480});
   await page.evaluate(({background,color})=>{document.documentElement.style.setProperty('--card-background-color',background);document.documentElement.style.setProperty('--primary-text-color',color);const s=structuredClone(window.snapshot);s.states[s.target].attributes.loxone_group_control.busy=true;window.setHass(s);},{background,color});
   assert.match(await card.locator('[role=status]').innerText(),/busy.*Please wait/i);assert.equal(await card.locator('dialog').getAttribute('aria-busy'),'true');
   for(const position of [0,.5,1]){
    const g=await card.evaluate((el,position)=>{const dialog=el._dialog,banner=el.shadowRoot.querySelector('[role=status]');dialog.scrollTop=(dialog.scrollHeight-dialog.clientHeight)*position;const r=banner.getBoundingClientRect(),d=dialog.getBoundingClientRect(),s=getComputedStyle(banner);const lum=value=>{const c=value.match(/\d+/g).slice(0,3).map(n=>Number(n)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);return c[0]*.2126+c[1]*.7152+c[2]*.0722;};const a=lum(s.color),b=lum(s.backgroundColor);return {top:r.top,bottom:r.bottom,dialogTop:d.top,dialogBottom:d.bottom,height:r.height,position:s.position,opacity:s.opacity,contrast:(Math.max(a,b)+.05)/(Math.min(a,b)+.05),controls:[...el.shadowRoot.querySelectorAll('input,select,[data-action=row-play],[data-action=group-play]')].map(e=>getComputedStyle(e).opacity),labelOpacity:getComputedStyle(el.shadowRoot.querySelector('.speaker-name')).opacity,scroll:dialog.scrollTop};},position);
    assert.ok(g.top>=g.dialogTop&&g.bottom<=g.dialogBottom+1&&g.height>=44,'banner fully visible at every scroll position');
    assert.equal(g.opacity,'1');assert.equal(g.labelOpacity,'1');assert.ok(g.controls.every(v=>Number(v)<=.25));assert.ok(g.contrast>=4.5);
    geometry.push({theme,width,position,...g});
   }
   await page.screenshot({path:path.join(out,`busy-${theme}-${width}.png`),fullPage:true});
   assert.equal(await page.evaluate(()=>window.calls.length),0,'external busy presentation never sends a command');
  }
  await page.emulateMedia({reducedMotion:'reduce'});assert.equal(await card.locator('[role=status]').evaluate(el=>getComputedStyle(el,'::before').animationName),'none');
  await page.emulateMedia({reducedMotion:'no-preference'});await reset();
  assert.equal(await card.locator('dialog').getAttribute('aria-busy'),'false');assert.ok(!(await card.locator('[role=status]').innerText()).includes('Please wait'));
  fs.writeFileSync(path.join(out,'busy-geometry.json'),JSON.stringify(geometry,null,2)+'\n');await page.setViewportSize({width:768,height:900});
  results.push('320/768 light/dark genuine external-busy banner visible at top/middle/bottom; opacity .25 controls/1 labels and status; contrast >=4.5; reduced motion; aria-busy truthful clearing; no external-busy service');
 }
 if(slice==='all'){
  // Unchanged room/top/volume/focus/eligibility/editor/layout oracles from dev6.
  await reset(snapshots.find(s=>s.scenario==='two-members'));
  assert.deepEqual(await card.locator('[data-section=members] .speaker-name').allTextContents(),['BRAVO','Zulu']);
  assert.deepEqual(await card.locator('[data-section=others] .speaker-name').allTextContents(),['alpha','Alpine']);
  await reset();
  assert.deepEqual(await card.locator('[data-section=members] .speaker-name').allTextContents(),['alpha','BRAVO','Zulu']);
  assert.equal(await card.locator('.speaker-name').count(),4);assert.ok(!(await card.locator('dialog').innerText()).includes('DUPLICATE-AREA'));
  assert.equal(await row(a).locator('[data-role=leader]').innerText(),'Leader');
  for(const id of [a,b,c,d]){
   assert.equal(await row(id).locator('input[type=range]').count(),1);assert.equal(await row(id).locator('[data-action=row-play]').count(),1);
  }
  await row(b).locator('input[type=range]').evaluate(el=>{el.value='17';el.dispatchEvent(new Event('change',{bubbles:true}));});await settled();
  assert.deepEqual(await page.evaluate(()=>window.calls[0]),{domain:'media_player',service:'volume_set',data:{volume_level:.17},target:{entity_id:b}});
  assert.deepEqual(await page.evaluate(id=>window.card.hass.states[id].attributes.group_members,c),[a,c,b]);
  const oldRow=await row(b).elementHandle();await row(b).locator('input[type=range]').focus();
  await page.evaluate(({a,c,d})=>window.membership([{id:'native',members:[a,c,d]}]),{a,c,d});
  assert.deepEqual(await card.locator('[data-section=members] .speaker-name').allTextContents(),['Alpine','BRAVO','Zulu']);
  assert.deepEqual(await card.locator('[data-section=others] .speaker-name').allTextContents(),['alpha']);
  assert.equal(await oldRow.evaluate(el=>el===window.card.shadowRoot.querySelector('[data-section=others] .speaker')),true);
  assert.equal(await row(b).locator('input[type=range]').evaluate(el=>el===window.card.shadowRoot.activeElement),true);
  await page.evaluate(()=>window.calls=[]);await row(b).locator('input[type=range]').evaluate(el=>{el.value='23';el.dispatchEvent(new Event('change',{bubbles:true}));});await settled();
  assert.deepEqual(await page.evaluate(()=>window.calls[0]),{domain:'media_player',service:'volume_set',data:{volume_level:.23},target:{entity_id:b}});
  await reset(snapshots.find(s=>s.scenario==='other-group'));
  assert.deepEqual(await card.locator('[data-section=others] .speaker-name').allTextContents(),['Alpine','charlie']);
  for(const id of [d,e])for(const playing of [false,true]){
   const s=structuredClone(snapshots.find(s=>s.scenario==='other-group'));s.states[id].state=playing?'playing':'paused';await reset(s);
   const checked=await check(id).isChecked();await row(id).locator('[data-action=row-play]').click();await settled();
   assert.deepEqual(await page.evaluate(()=>window.calls[0]),{domain:'loxone',service:'audio_room_transport',data:{action:playing?'pause':'play'},target:{entity_id:id}});
   assert.equal(await check(id).isChecked(),checked);
  }
  await reset();await page.evaluate(()=>window.mode='defer');await row(d).locator('[data-action=row-play]').click();
  await page.waitForFunction(()=>!!window.release);
  assert.equal(await card.locator('[data-action=row-play]:not(:disabled)').count(),0);assert.equal(await card.locator('[data-action=group-play]').isDisabled(),true);
  await row(d).locator('[data-action=row-play]').evaluate(el=>el.onclick());await card.locator('[data-action=group-play]').evaluate(el=>el.onclick());
  assert.equal(await page.evaluate(()=>window.calls.length),1);await page.evaluate(()=>window.release());await settled();
  await reset();await page.evaluate(()=>window.mode='reject');await row(b).locator('[data-action=row-play]').click();await settled();
  assert.match(await card.locator('[role=alert]').innerText(),/Synthetic native rejection/);assert.equal(await page.evaluate(()=>window.calls.length),1);
  for(const state of ['unknown','unavailable']){
   const s=structuredClone(snapshot);s.states[d].state=state;await reset(s);assert.equal(await row(d).count(),0);
  }
  const unsupported=structuredClone(snapshot);unsupported.states[d].attributes.supported_features&=~16384;await reset(unsupported);
  assert.equal(await row(d).locator('[data-action=row-play]').isDisabled(),true);
  await reset();await page.evaluate(id=>window.card.hass.states[id].state='playing',b);await row(b).locator('[data-action=row-play]').focus();await page.keyboard.press('Enter');await settled();
  assert.deepEqual(await page.evaluate(()=>window.calls[0]),{domain:'loxone',service:'audio_room_transport',data:{action:'pause'},target:{entity_id:b}});
  const unavailable=structuredClone(snapshot);unavailable.states[c].state='unavailable';await reset(unavailable);
  assert.equal(await card.locator('input[type=range]').count(),0);assert.equal(await card.locator('[data-action=group-play]').isDisabled(),true);
  const foreign=structuredClone(snapshot);foreign.states[b].attributes.loxone_group_control.owner='foreign-owner';await reset(foreign);assert.equal(await card.locator('input[type=range]').count(),0);
  await reset();
  const discovery=await page.evaluate(()=>{
   const C=customElements.get('loxone-group-control-card'),editor=C.getConfigElement();editor.setConfig({entity:window.snapshot.target});editor.hass=window.card.hass;window.editor=editor;
   const presentation=editor.shadowRoot.querySelector('[aria-label=Presentation]');
   const result={registered:!!customElements.get('loxone-group-control-editor'),discovery:window.customCards.filter(x=>x.type==='loxone-group-control-card').length,stub:C.getStubConfig(window.card.hass),options:[...editor.shadowRoot.querySelector('[aria-label="Loxone speaker"]').options].map(o=>o.value),presentations:[...presentation.options].map(o=>o.value)};
   editor.addEventListener('config-changed',e=>window.editorConfig=e.detail.config);presentation.value='player';presentation.onchange();return result;
  });
  assert.equal(discovery.registered,true);assert.equal(discovery.discovery,1);assert.ok(discovery.stub.entity);assert.ok(discovery.options.includes(c));assert.deepEqual(discovery.presentations,['button','player']);
  assert.deepEqual(await page.evaluate(()=>window.editorConfig),{entity:c,presentation:'player'});
  for(const theme of [['#ffffff','#212121','rgb(255, 255, 255)'],['#202020','#eeeeee','rgb(32, 32, 32)']]){
   await page.evaluate(([background,color])=>{document.documentElement.style.setProperty('--card-background-color',background);document.documentElement.style.setProperty('--primary-text-color',color);},theme);
   assert.equal(await card.locator('dialog').evaluate(el=>getComputedStyle(el).backgroundColor),theme[2]);
   for(const width of [320,768]){
    await page.setViewportSize({width,height:720});
    const g=await card.locator('dialog').evaluate(el=>({scroll:el.scrollWidth,width:el.clientWidth,rect:el.getBoundingClientRect().width}));assert.ok(g.scroll<=g.width+1);assert.ok(g.rect<=width);
    for(const id of [a,b,c,d]){
     const boxes=await row(id).locator('input[type=range],[data-action=row-play],.speaker-name,[data-action=volume-minus],[data-action=volume-plus]').evaluateAll(els=>els.map(el=>{const r=el.getBoundingClientRect();return {w:r.width,h:r.height,y:r.y+r.height/2};}));assert.ok(boxes.every(b=>b.w>0&&b.h>0));
     assert.ok((await row(id).locator('input[type=range]').boundingBox()).width>=72,'slider never collapses');
     for(const action of ['volume-minus','volume-plus']){const b=await row(id).locator(`[data-action=${action}]`).boundingBox();assert.ok(b.width>=44&&b.height>=44);}
     const inside=await row(id).evaluate(el=>{const r=el.getBoundingClientRect();return [...el.querySelectorAll('input,button,output')].every(e=>{const b=e.getBoundingClientRect();return b.x>=r.x-1&&b.right<=r.right+1&&b.y>=r.y-1&&b.bottom<=r.bottom+1;});});assert.ok(inside,'responsive controls remain within same keyed room row');
    }
   }
  }
  await page.keyboard.press('Escape');await card.locator('dialog[open]').waitFor({state:'detached'});assert.equal(await card.locator('dialog[open]').count(),0);
  await card.locator('[data-action=open]').focus();await page.keyboard.press('Enter');await card.locator('dialog[open]').waitFor();
  results.push('preserved dev6 alphabetical partitions, entity-only labels, one-row volume/native-order isolation, keyed row/focus after external move, other-group own-room transport, row/top pending/error guards, unrendered current action, eligibility, editor/discovery, keyboard, 320/768 light/dark geometry and Escape');
 }
 assert.deepEqual(errors,[]);
 fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({status:'PASS',slice,results,chromium:browser.browser().version()},null,2)+'\n');
 console.log(JSON.stringify({status:'PASS',slice,results}));
}catch(error){fs.writeFileSync(path.join(out,'failure.json'),JSON.stringify({status:'FAIL',slice,message:String(error),stack:error.stack,results,errors},null,2)+'\n');throw error;}
finally{
 if(page){
  const calls=await page.evaluate(()=>window.allCalls||[]).catch(()=>[]);
  fs.writeFileSync(path.join(out,'browser-service-calls.json'),JSON.stringify({provenance:'Compiled UI2 in Chromium; synthetic owning HA state exports; sink then separately replayed through registered owning HA/authenticated peer',source_sha256:sha(source),asset_sha256:sha(path.join(out,'card.js')),states_sha256:sha(statesPath),calls},null,2)+'\n');
  fs.writeFileSync(path.join(out,'rendered.html'),await page.locator('loxone-group-control-card').evaluate(el=>el.shadowRoot.innerHTML).catch(()=>''));
 }
 if(browser)await browser.close();if(server)await new Promise(r=>server.close(r));fs.rmSync(path.join(out,'browser-profile'),{recursive:true,force:true});
}
