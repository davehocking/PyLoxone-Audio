// Actual frozen packaged UI1/UI2-R1 code, including saved row handlers.
import fs from 'node:fs';import path from 'node:path';import http from 'node:http';import assert from 'node:assert/strict';import crypto from 'node:crypto';import {createRequire} from 'node:module';
const require=createRequire(path.resolve(process.env.FRONTEND_NODE_MODULES,'playwright-core/package.json'));const {chromium}=require('playwright-core');
const root=path.resolve(process.argv[2]),out=path.resolve(process.argv[3]);fs.mkdirSync(out,{recursive:false});
const fixture=JSON.parse(fs.readFileSync(path.join(root,'tests/frontend/room-ui-states.json'))).find(s=>s.scenario==='confirmed');
let browser,server;const evidence=[];
try{
 server=http.createServer((req,res)=>{if(req.url==='/')res.end('<script type="module" src="/old.js"></script>');else if(req.url==='/old.js'){res.setHeader('Content-Type','application/javascript');res.end(fs.readFileSync(server.asset));}else res.writeHead(404).end();});await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin=`http://127.0.0.1:${server.address().port}`;
 browser=await chromium.launchPersistentContext(path.join(out,'browser-profile'),{executablePath:'/snap/bin/chromium',headless:true,serviceWorkers:'block',args:['--no-sandbox','--disable-dev-shm-usage']});
 for(const suffix of ['ui1','ui2-r1']){
  const asset=path.join(root,`adapters/pyloxone/frontend/dist/group-control-card-0.1.3.dev6-${suffix}.js`);server.asset=asset;
  const context=browser;await context.route('**/*',r=>r.request().url().startsWith(origin+'/')?r.continue():r.abort());const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(String(e)));await page.goto(origin);await page.waitForFunction(()=>!!customElements.get('loxone-group-control-card'));
  const result=await page.evaluate(s=>{
   const card=document.createElement('loxone-group-control-card');card.setConfig({entity:s.target});document.body.append(card);const calls=[];
   const h={states:structuredClone(s.states),entities:s.entities,user:{id:'synthetic'},connected:true,callService:(...r)=>{calls.push(r);return Promise.resolve();}};card.hass=h;card.open();
   const row=card.shadowRoot.querySelector(`[data-entity="${s.target}"]`),slider=row.querySelector('input[type=range]'),change=slider.onchange,plus=row.querySelector('[data-action=volume-plus]'),step=plus?.onclick;
   if(!change)throw new Error('Positive legacy row slider handler missing');
   const count=card.shadowRoot.querySelectorAll('[data-entity]').length;
   for(const state of Object.values(h.states))if(state.attributes.loxone_group_control)state.attributes.loxone_group_control.version=2;
   card.hass={...h};slider.value=70;change();step?.();
   card.close?.();card.open();
   return {legacyRows:count,hasSavedSlider:!!change,hasSavedStepper:!!step,postV2Rows:card.shadowRoot.querySelectorAll('[data-entity]').length,calls};
  },fixture);
  assert.ok(result.legacyRows>0);assert.equal(result.postV2Rows,0);assert.deepEqual(result.calls,[]);assert.deepEqual(errors,[]);evidence.push({suffix,sha256:crypto.createHash('sha256').update(fs.readFileSync(asset)).digest('hex'),...result});await page.close();
 }
 fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({status:'PASS',evidence},null,2));
}finally{if(browser)await browser.close();if(server)await new Promise(r=>server.close(r));}
