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
   window.allCalls.push({...request,groups,staticEntities:Object.values(s.states).filter(s=>!s.attributes.loxone_group_control).map(s=>s.entity_id),mode:window.mode,states:structuredClone(s.states),semantic:structuredClone(window.semantic)});
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
 const probes=[];
 const feedback=async(id,p)=>page.evaluate(({id,p})=>{const s=structuredClone(window.snapshot);s.states[id].attributes.volume_level=p/100;window.setHass(s);},{id,p});
 const exercise=async(from,direction,kind)=>{
  const s=structuredClone(snapshot);s.states[b].attributes.volume_level=from/100;await reset(s);
  const requested=from+direction;
  await page.evaluate(semantic=>{window.semantic=semantic;window.mode='defer';window.release=null;},{beforePercent:from,direction,expectedPercent:requested,kind});
  const action=row(b).locator(`[data-action=volume-${direction===1?'plus':'minus'}]`);
  await action.click();await page.waitForFunction(()=>!!window.release);
  const request=await page.evaluate(()=>structuredClone(window.calls[0]));
  assert.equal(request.domain,'media_player');assert.equal(request.service,'volume_set');assert.deepEqual(request.target,{entity_id:b});
  assert.equal(await row(b).locator('output').innerText(),from+'%','no optimistic reported value');
  await action.evaluate(el=>el.onclick());assert.equal(await page.evaluate(()=>window.calls.length),1,'no duplicate/pending retry');
  if(kind==='control'){
   await feedback(a,requested);await page.evaluate(()=>window.release());await page.waitForTimeout(100);
   assert.equal(await page.evaluate(()=>window.card._pending),true,'wrong room is not confirmation');
   await feedback(b,requested===100?99:requested+1);await page.waitForTimeout(100);
   assert.equal(await page.evaluate(()=>window.card._pending),true,'wrong integer is not confirmation');
   await feedback(b,requested);
  }else{
   await feedback(b,requested);assert.equal(await page.evaluate(()=>window.card._pending),true,'native feedback alone is not service completion');
   await page.evaluate(()=>window.release());
  }
  await settled();assert.equal(await card.locator('[role=alert]').innerText(),'');
  assert.equal(await row(b).locator('output').innerText(),requested+'%');
  assert.equal(await page.evaluate(()=>window.calls.length),1,'no retry');
  probes.push({from,direction,requested,kind,request,wirePercent:Math.trunc(request.data.volume_level*100)});
 };
 // Eight separately reported boundary/ordinary controls, then exactly 200 matrix requests.
 for(const [from,direction] of [[28,1],[29,1],[31,-1],[30,-1],[56,1],[58,-1],[57,1],[59,-1]])await exercise(from,direction,'control');
 for(let from=0;from<=100;from++)for(const direction of [-1,1])if(from+direction>=0&&from+direction<=100)await exercise(from,direction,'matrix');
 for(const from of [0,100]){
  const s=structuredClone(snapshot);s.states[b].attributes.volume_level=from/100;await reset(s);
  const action=row(b).locator(`[data-action=volume-${from?'plus':'minus'}]`);assert.equal(await action.isDisabled(),true);
  await action.evaluate(el=>el.onclick());assert.equal(await page.evaluate(()=>window.calls.length),0,'outward endpoint no send');
 }
 const matrix=probes.filter(p=>p.kind==='matrix');assert.equal(matrix.length,200);
 assert.equal(new Set(matrix.map(p=>p.from+':'+p.direction)).size,200);assert.equal(new Set(matrix.map(p=>p.requested)).size,101);
 const mismatches=probes.filter(p=>p.wirePercent!==p.requested);
 fs.writeFileSync(path.join(out,'semantic-observations.json'),JSON.stringify({probes,mismatches,matrixRequests:matrix.length,controlRequests:8,errors},null,2)+'\n');
 assert.deepEqual(errors,[]);assert.deepEqual(mismatches,[],'emitted payload must preserve independently requested integer through unchanged owning truncation');
 results.push('200 real matrix button requests / 101 targets plus eight boundary/normal controls; deferred service and honest native confirmation; no optimism/retry; exact endpoint no-send');
 fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({status:'PASS',results,matrixRequests:200,controlRequests:8,chromium:browser.browser().version()},null,2)+'\n');
 console.log(JSON.stringify({status:'PASS',matrixRequests:200,controlRequests:8}));
}catch(error){fs.writeFileSync(path.join(out,'failure.json'),JSON.stringify({status:'FAIL',slice,message:String(error),stack:error.stack,results,errors},null,2)+'\n');throw error;}
finally{
 if(page){
  const calls=await page.evaluate(()=>window.allCalls||[]).catch(()=>[]);
  fs.writeFileSync(path.join(out,'browser-service-calls.json'),JSON.stringify({provenance:'Compiled UI2 in Chromium; synthetic owning HA state exports; sink then separately replayed through registered owning HA/authenticated peer',source_sha256:sha(source),asset_sha256:sha(path.join(out,'card.js')),states_sha256:sha(statesPath),calls},null,2)+'\n');
  fs.writeFileSync(path.join(out,'rendered.html'),await page.locator('loxone-group-control-card').evaluate(el=>el.shadowRoot.innerHTML).catch(()=>''));
 }
 if(browser)await browser.close();if(server)await new Promise(r=>server.close(r));fs.rmSync(path.join(out,'browser-profile'),{recursive:true,force:true});
}
