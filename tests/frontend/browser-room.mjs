// Version 2 oracle: the agreed interaction update supersedes disabled rows.
// Original browser.mjs and its dev3 trace remain immutable historical oracles.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import http from 'node:http';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const require=process.env.FRONTEND_NODE_MODULES?createRequire(path.resolve(process.env.FRONTEND_NODE_MODULES,'esbuild/package.json')):createRequire(path.join(root,'adapters/pyloxone/frontend/package.json'));
const {build}=require('esbuild'); const {chromium}=require('playwright-core');
const out=path.resolve(process.argv[2]);fs.mkdirSync(out,{recursive:false});
const statesPath=path.resolve(process.argv[3]);const snapshots=JSON.parse(fs.readFileSync(statesPath,'utf8'));
const source=path.join(root,'adapters/pyloxone/frontend/src/group-control-card.js');
const sha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const results=[];let browser;let server;let profile;
try {
  if(process.argv[4])fs.copyFileSync(path.resolve(process.argv[4]),path.join(out,'card.js'));
  else if(fs.existsSync(source)) await build({entryPoints:[source],outfile:path.join(out,'card.js'),bundle:true,format:'esm',target:'es2022',minify:false});
  else fs.writeFileSync(path.join(out,'card.js'),'// New optional card not implemented yet.');
  fs.writeFileSync(path.join(out,'index.html'),'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><script type="module" src="/card.js"></script>');
  server=http.createServer((req,res)=>{const file=req.url==='/'?'index.html':req.url.slice(1);if(!['index.html','card.js'].includes(file)){res.writeHead(404).end();return;}res.setHeader('Content-Type',file.endsWith('.js')?'application/javascript':'text/html');res.end(fs.readFileSync(path.join(out,file)));});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  profile=path.join(out,'browser-profile');
  browser=await chromium.launchPersistentContext(profile,{executablePath:process.env.CHROMIUM_EXECUTABLE||'/snap/bin/chromium',headless:true,args:['--no-sandbox','--disable-gpu','--disable-dev-shm-usage']});
  const context=browser; const origin=`http://127.0.0.1:${server.address().port}`;
  await context.route('**/*',r=>r.request().url().startsWith(origin+'/')?r.continue():r.abort());
  const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  await page.goto(origin);await page.waitForLoadState('networkidle');
  assert.equal(await page.evaluate(()=>!!customElements.get('loxone-group-control-card')),true,'Optional combined card must be registered');
  const snapshot=snapshots.find(s=>s.scenario==='confirmed'); const ids=Object.keys(snapshot.states); const [a,b,c,d,e,f]=ids;
  await page.evaluate(s=>{
    window.calls=[];window.allCalls=[];window.mode='immediate';window.release=null;
    const card=document.createElement('loxone-group-control-card');
    card.setConfig({type:'custom:loxone-group-control-card',entity:s.target});
    document.body.append(card);window.card=card;
    window.setHass=snapshot=>{window.snapshot=structuredClone(snapshot);card.hass={states:snapshot.states,entities:snapshot.entities,user:{id:'synthetic'},callService:(domain,service,data,target)=>{
      const request={domain,service,data:structuredClone(data),target:structuredClone(target)};window.calls.push(request);
      const groups=[...new Map(Object.values(snapshot.states).map(s=>s.attributes.loxone_group_control).filter(d=>d&&d.members.length>1).map(d=>[d.group_id,{id:d.group_id,members:[...d.members]}])).values()];
      const staticEntities=Object.values(snapshot.states).filter(s=>!s.attributes.loxone_group_control).map(s=>s.entity_id);
      window.allCalls.push({...request,groups,staticEntities,mode:window.mode,states:structuredClone(snapshot.states)});
      if(window.mode==='reject')return Promise.reject(new Error('Synthetic native rejection'));if(window.mode==='defer')return new Promise(resolve=>window.release=resolve);return Promise.resolve();
    }};};window.setHass(s);
  },snapshot);
  await page.locator('loxone-group-control-card').locator('[data-action=open]').click();
  const card=page.locator('loxone-group-control-card');
  await card.locator('dialog[open]').waitFor();
  await page.evaluate(s=>window.setHass(s),snapshots.find(s=>s.scenario==='two-members'));
  assert.deepEqual(await card.locator('[data-section=members] .speaker-name').allTextContents(),['BRAVO','Zulu']);
  assert.deepEqual(await card.locator('[data-section=others] .speaker-name').allTextContents(),['alpha','Alpine']);
  await page.evaluate(s=>window.setHass(s),snapshot);
  assert.deepEqual(await card.locator('[data-section=members] .speaker-name').allTextContents(),['alpha','BRAVO','Zulu']);
  assert.deepEqual(await card.locator('[data-section=others] .speaker-name').allTextContents(),['Alpine']);
  assert.equal(await card.locator('.speaker-name').count(),4);
  assert.ok(!(await card.locator('dialog').innerText()).includes('DUPLICATE-AREA'));
  for(const id of [a,b,c,d]){
    const row=card.locator(`[data-entity="${id}"]`);
    assert.equal(await row.locator('input[type=range]').count(),1);assert.equal(await row.locator('[data-action=row-play]').count(),1);
    assert.equal(await row.locator('[data-action=row-play]').isDisabled(),false,'Owner decided: all eligible rows have room-only transport');
    const checked=await row.locator('input[type=checkbox]').isChecked();
    await page.evaluate(()=>{window.calls=[];});
    await row.locator('[data-action=row-play]').click();
    await page.waitForFunction(()=>window.calls.length===1&&!window.card._pending);
    assert.deepEqual(await page.evaluate(()=>window.calls[0]),{domain:'loxone',service:'audio_room_transport',data:{action:'play'},target:{entity_id:id}});
    assert.equal(await row.locator('input[type=checkbox]').isChecked(),checked);
  }
  // Own-state pause in both partitions, including the anchor and native leader.
  for(const id of [a,b,c,d]){
    await page.evaluate(({s,id})=>{s=structuredClone(s);s.states[id].state='playing';window.calls=[];window.setHass(s);},{s:snapshot,id});
    const row=card.locator(`[data-entity="${id}"]`),button=row.locator('[data-action=row-play]');
    assert.equal(await button.innerText(),'⏸');
    assert.equal(await button.getAttribute('aria-label'),`Pause ${snapshot.states[id].attributes.friendly_name} only`);
    const checked=await row.locator('input[type=checkbox]').isChecked();
    await button.click();await page.waitForFunction(()=>window.calls.length===1&&!window.card._pending);
    assert.deepEqual(await page.evaluate(()=>window.calls[0]),{domain:'loxone',service:'audio_room_transport',data:{action:'pause'},target:{entity_id:id}});
    assert.equal(await row.locator('input[type=checkbox]').isChecked(),checked);
    assert.equal(await page.evaluate(id=>window.card.hass.states[id].state,id),'playing','ACK is not fabricated paused feedback');
  }
  // Other speakers may belong to another native group: neither row redirects.
  const otherGroup=snapshots.find(s=>s.scenario==='other-group');assert.ok(otherGroup);
  await page.evaluate(s=>{window.calls=[];window.setHass(s);},otherGroup);
  assert.deepEqual(await card.locator('[data-section=others] .speaker-name').allTextContents(),['Alpine','charlie']);
  for(const id of [d,e]){
    await page.evaluate(()=>{window.calls=[];});
    await card.locator(`[data-entity="${id}"] [data-action=row-play]`).click();
    await page.waitForFunction(()=>window.calls.length===1&&!window.card._pending);
    assert.deepEqual(await page.evaluate(()=>window.calls[0]),{domain:'loxone',service:'audio_room_transport',data:{action:'play'},target:{entity_id:id}});
  }
  await page.evaluate(s=>window.setHass(s),snapshot);
  // Staged membership is never playback scope. Pending cannot spam rows/top.
  await card.locator(`[data-entity="${d}"] input[type=checkbox]`).check();
  await page.evaluate(()=>{window.calls=[];window.mode='defer';window.release=null;});
  await card.locator(`[data-entity="${d}"] [data-action=row-play]`).click();
  await page.waitForFunction(()=>!!window.release);
  assert.equal(await card.locator('[data-action=row-play]:not(:disabled)').count(),0);
  assert.equal(await card.locator('[data-action=group-play]').isDisabled(),true);
  await card.locator(`[data-entity="${d}"] [data-action=row-play]`).evaluate(el=>el.onclick());
  await card.locator('[data-action=group-play]').evaluate(el=>el.onclick());
  assert.equal(await page.evaluate(()=>window.calls.length),1);
  assert.deepEqual(await page.evaluate(()=>window.calls[0]),{domain:'loxone',service:'audio_room_transport',data:{action:'play'},target:{entity_id:d}});
  await page.evaluate(()=>window.release());await page.waitForFunction(()=>!window.card._pending);
  assert.equal(await card.locator(`[data-entity="${d}"] input[type=checkbox]`).isChecked(),true);
  assert.equal(await card.locator(`[data-entity="${d}"] [data-action=row-play]`).innerText(),'▶');
  await card.locator('[data-action=reset]').click();
  await page.evaluate(()=>{window.calls=[];window.mode='reject';});
  await card.locator(`[data-entity="${b}"] [data-action=row-play]`).click();
  await card.locator('[role=alert]').filter({hasText:'Synthetic native rejection'}).waitFor();
  assert.equal(await page.evaluate(()=>window.calls.length),1);
  assert.equal(await card.locator(`[data-entity="${b}"] [data-action=row-play]`).innerText(),'▶');
  // A detached old row cannot dispatch its old play button or slider.
  const stale=await card.locator(`[data-entity="${d}"]`).elementHandle();
  await page.evaluate(({s,id})=>{s=structuredClone(s);s.states[id].state='unavailable';window.calls=[];window.mode='immediate';window.setHass(s);},{s:snapshot,id:d});
  assert.equal(await card.locator(`[data-entity="${d}"]`).count(),0);
  await stale.evaluate(row=>{row.querySelector('[data-action=row-play]').onclick();const v=row.querySelector('input[type=range]');v.value='71';v.onchange();});
  assert.equal(await page.evaluate(()=>window.calls.length),0);
  for(const state of ['unknown','unavailable']){
    await page.evaluate(({s,id,state})=>{s=structuredClone(s);s.states[id].state=state;window.calls=[];window.setHass(s);},{s:snapshot,id:d,state});
    assert.equal(await card.locator(`[data-entity="${d}"]`).count(),0);
  }
  await page.evaluate(({s,id})=>{s=structuredClone(s);s.states[id].attributes.supported_features&=~16384;window.setHass(s);},{s:snapshot,id:d});
  assert.equal(await card.locator(`[data-entity="${d}"] [data-action=row-play]`).isDisabled(),true);
  await page.evaluate(s=>{window.calls=[];window.setHass(s);},structuredClone(snapshot));
  // Recheck even without a render since own state changed. Keyboard activation.
  await page.evaluate(id=>window.card.hass.states[id].state='playing',b);
  await card.locator(`[data-entity="${b}"] [data-action=row-play]`).focus();
  await page.keyboard.press('Enter');await page.waitForFunction(()=>window.calls.length===1&&!window.card._pending);
  assert.deepEqual(await page.evaluate(()=>window.calls[0]),{domain:'loxone',service:'audio_room_transport',data:{action:'pause'},target:{entity_id:b}});
  await page.evaluate(s=>window.setHass(s),snapshot);
  results.push('both partitions own-state play/pause; independent, leader/follower and other-group rows; checkbox isolation; ACK truth; pending duplicate suppression; row error; detached/unavailable/unknown/capability guards; keyboard');
  await page.evaluate(()=>{window.calls=[];});
  assert.equal(await card.locator(`[data-entity="${a}"] [data-role=leader]`).innerText(),'Leader');
  await card.locator(`[data-entity="${b}"] input[type=range]`).evaluate(el=>{el.value='17';el.dispatchEvent(new Event('change',{bubbles:true}));});
  await page.waitForFunction(()=>window.calls.length===1);
  assert.deepEqual(await page.evaluate(()=>window.calls[0]),{domain:'media_player',service:'volume_set',data:{volume_level:.17},target:{entity_id:b}});
  assert.deepEqual(await card.locator('[data-section=members] .speaker-name').allTextContents(),['alpha','BRAVO','Zulu']);
  assert.deepEqual(await page.evaluate(()=>window.card.hass.states[window.snapshot.target].attributes.group_members),[a,c,b]);
  results.push('real owning-HA exports; two alphabetical sections; entity-name-only labels; inline sliders and buttons; pure one-room volume; native order preserved');
  await page.evaluate(()=>{
    window.revision=0;
    window.membership=members=>{
      const s=structuredClone(window.snapshot);window.revision++;
      for(const [id,state] of Object.entries(s.states)){
        const d=state.attributes.loxone_group_control;if(!d)continue;
        d.revision='synthetic-ui-'+window.revision;
        d.members=members.includes(id)?[...members]:[id];
        d.group_id=members.includes(id)?'native':null;state.attributes.group_members=[...d.members];
      }
      window.setHass(s);
    };
    window.calls=[];
  });
  // A staged candidate stays in Other speakers and never becomes group scope.
  await card.locator(`[data-entity="${d}"] input[type=checkbox]`).check();
  assert.deepEqual(await card.locator('[data-section=others] .speaker-name').allTextContents(),['Alpine']);
  await card.locator('[data-action=group-play]').click();
  await page.waitForFunction(()=>window.calls.length===1&&!window.card._pending);
  assert.deepEqual(await page.evaluate(()=>window.calls[0]),{domain:'media_player',service:'media_play',data:{},target:{entity_id:a}});
  await page.evaluate(()=>{window.calls=[];window.mode='defer';});
  await card.locator('[data-action=apply]').click();
  await page.waitForFunction(()=>!!window.release);
  await card.locator('[data-action=apply]').evaluate(el=>el.click());
  assert.equal(await page.evaluate(()=>window.calls.length),1);
  assert.deepEqual(await page.evaluate(()=>window.calls[0]),{domain:'media_player',service:'join',data:{group_members:[d]},target:{entity_id:c}});
  assert.deepEqual(await card.locator('[data-section=members] .speaker-name').allTextContents(),['alpha','BRAVO','Zulu']);
  await page.evaluate(members=>{window.membership(members);window.release();},[a,c,b,d]);
  await page.waitForFunction(()=>!window.card._pending);
  assert.deepEqual(await card.locator('[data-section=members] .speaker-name').allTextContents(),['alpha','Alpine','BRAVO','Zulu']);
  assert.equal(await card.locator('dialog[open]').count(),1);
  // External native leave moves an existing keyed row, retaining focus and target.
  const oldRow=await card.locator(`[data-entity="${b}"]`).elementHandle();
  await card.locator(`[data-entity="${b}"] input[type=range]`).focus();
  await page.evaluate(members=>window.membership(members),[a,c,d]);
  assert.deepEqual(await card.locator('[data-section=members] .speaker-name').allTextContents(),['Alpine','BRAVO','Zulu']);
  assert.deepEqual(await card.locator('[data-section=others] .speaker-name').allTextContents(),['alpha']);
  assert.equal(await oldRow.evaluate(el=>el===window.card.shadowRoot.querySelector('[data-section=others] .speaker')),true);
  assert.equal(await card.locator(`[data-entity="${b}"] input[type=range]`).evaluate(el=>el===window.card.shadowRoot.activeElement),true);
  await page.evaluate(()=>{window.calls=[];window.mode='immediate';});
  await card.locator(`[data-entity="${b}"] input[type=range]`).evaluate(el=>{el.value='23';el.dispatchEvent(new Event('change',{bubbles:true}));});
  await page.waitForFunction(()=>window.calls.length===1&&!window.card._pending);
  assert.deepEqual(await page.evaluate(()=>window.calls[0]),{domain:'media_player',service:'volume_set',data:{volume_level:.23},target:{entity_id:b}});
  assert.equal(await card.locator('[data-action=apply]').isDisabled(),true);
  await page.evaluate(()=>{window.calls=[];});
  await card.locator(`[data-entity="${b}"] [data-action=row-play]`).click();
  await page.waitForFunction(()=>window.calls.length===1&&!window.card._pending);
  assert.deepEqual(await page.evaluate(()=>window.calls[0]),{domain:'loxone',service:'audio_room_transport',data:{action:'play'},target:{entity_id:b}});
  // Rejected membership preserves confirmed partitions, visible error, and the user's names.
  await card.locator(`[data-entity="${b}"] input[type=checkbox]`).check();
  await page.evaluate(()=>{window.calls=[];window.mode='reject';});
  await card.locator('[data-action=apply]').click();
  await card.locator('[role=alert]').filter({hasText:'Synthetic native rejection'}).waitFor();
  assert.deepEqual(await card.locator('[data-section=others] .speaker-name').allTextContents(),['alpha']);
  assert.equal(await page.evaluate(()=>window.calls.length),1);
  await card.locator('[data-action=reset]').click();
  await card.locator(`[data-entity="${d}"] input[type=checkbox]`).uncheck();
  await page.evaluate(()=>{window.calls=[];window.mode='defer';window.release=null;});
  await card.locator('[data-action=apply]').click();
  await page.waitForFunction(()=>!!window.release);
  assert.deepEqual(await page.evaluate(()=>window.calls[0]),{domain:'media_player',service:'unjoin',data:{},target:{entity_id:d}});
  assert.deepEqual(await card.locator('[data-section=members] .speaker-name').allTextContents(),['Alpine','BRAVO','Zulu']);
  await page.evaluate(members=>{window.membership(members);window.release();},[a,c]);
  await page.waitForFunction(()=>!window.card._pending);
  assert.deepEqual(await card.locator('[data-section=members] .speaker-name').allTextContents(),['BRAVO','Zulu']);
  assert.deepEqual(await card.locator('[data-section=others] .speaker-name').allTextContents(),['alpha','Alpine']);
  await page.evaluate(id=>{window.calls=[];window.mode='immediate';const s=structuredClone(window.snapshot);s.states[id].state='playing';window.setHass(s);},a);
  assert.equal(await card.locator('[data-action=group-play]').innerText(),'Pause group');
  await card.locator('[data-action=group-play]').click();
  await page.waitForFunction(()=>window.calls.length===1&&!window.card._pending);
  assert.deepEqual(await page.evaluate(()=>window.calls[0]),{domain:'media_player',service:'media_pause',data:{},target:{entity_id:a}});
  // Unknown/unavailable and refreshed cross-owner permissions cannot keep stale controls.
  await page.evaluate(()=>{const s=structuredClone(window.snapshot);s.states[s.target].state='unavailable';window.setHass(s);});
  assert.equal(await card.locator('input[type=range]').count(),0);
  assert.equal(await card.locator('[data-action=group-play]').isDisabled(),true);
  await page.evaluate(s=>window.setHass(s),snapshot);
  await page.evaluate(id=>{const s=structuredClone(window.snapshot);s.states[id].attributes.loxone_group_control.owner='foreign-owner';window.setHass(s);},b);
  assert.equal(await card.locator('input[type=range]').count(),0);
  await page.evaluate(s=>window.setHass(s),snapshot);
  // Responsive/touch layout and normal HA dark/light variables, real bounding boxes.
  const discovery=await page.evaluate(()=>{
    const C=customElements.get('loxone-group-control-card');
    const editor=C.getConfigElement();editor.setConfig({entity:window.snapshot.target});editor.hass=window.card.hass;
    return {registered:!!customElements.get('loxone-group-control-editor'),stub:C.getStubConfig(window.card.hass),options:[...editor.shadowRoot.querySelectorAll('option')].map(o=>o.value),discovery:window.customCards.filter(x=>x.type==='loxone-group-control-card').length};
  });
  assert.equal(discovery.registered,true);assert.equal(discovery.discovery,1);assert.ok(discovery.options.includes(c));assert.ok(discovery.stub.entity);
  await page.evaluate(()=>{document.documentElement.style.setProperty('--card-background-color','#ffffff');document.documentElement.style.setProperty('--primary-text-color','#212121');});
  assert.equal(await card.locator('dialog').evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(255, 255, 255)');
  for(const width of [320,768]){
    await page.setViewportSize({width,height:720});
    await page.evaluate(()=>{document.documentElement.style.setProperty('--card-background-color','#202020');document.documentElement.style.setProperty('--primary-text-color','#eeeeee');});
    const geometry=await card.locator('dialog').evaluate(el=>({scroll:el.scrollWidth,width:el.clientWidth,rect:el.getBoundingClientRect().width}));
    assert.ok(geometry.scroll<=geometry.width+1,JSON.stringify(geometry));assert.ok(geometry.rect<=width);
    for(const id of [a,b,c,d]){
      const row=card.locator(`[data-entity="${id}"]`);const boxes=await row.locator('input[type=range], [data-action=row-play], .speaker-name').evaluateAll(elements=>elements.map(el=>{const b=el.getBoundingClientRect();return {x:b.x,y:b.y,w:b.width,h:b.height};}));
      assert.ok(boxes.every(b=>b.w>0&&b.h>0));
      const centres=boxes.map(b=>b.y+b.h/2);assert.ok(Math.max(...centres)-Math.min(...centres)<24,'Name, volume and transport must share the same row (including leader badge)');
    }
  }
  await page.keyboard.press('Escape');assert.equal(await card.locator('dialog[open]').count(),0);
  results.push('rendered native-confirmed join/leave moves, stable keyed row/focus and volume target, staged selection isolation, duplicate Apply prevention, rejected membership, unavailable/cross-owner stale-control removal, responsive dark-theme geometry and Escape');
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(out,'browser-service-calls.json'),JSON.stringify({provenance:'Actual complete compiled card Chromium calls; invented owning-HA exported states; service sink, replay separately through owning HA',source_sha256:sha(source),asset_sha256:sha(path.join(out,'card.js')),states_sha256:sha(statesPath),calls:await page.evaluate(()=>window.allCalls)},null,2)+'\n');
  await card.locator('[data-action=open]').click();
  fs.writeFileSync(path.join(out,'rendered.html'),await card.evaluate(el=>el.shadowRoot.innerHTML));
  await page.screenshot({path:path.join(out,'popup.png'),fullPage:true});
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({status:'PASS',chromium:browser.browser().version(),inputs:{source:sha(source),states:sha(statesPath)},results,limits:['Synthetic owning-HA states/service sink, not installed HA UI or physical sound']},null,2)+'\n');
  console.log(JSON.stringify({status:'PASS',results}));
} catch(error) {
  fs.writeFileSync(path.join(out,'failure.json'),JSON.stringify({status:'FAIL',message:String(error),stack:error.stack,results},null,2)+'\n');
  throw error;
} finally {if(browser)await browser.close();if(server)await new Promise(resolve=>server.close(resolve));if(profile)fs.rmSync(profile,{recursive:true,force:true});}
