// Full unmodified pinned native HA application; synthetic backend only.
import fs from 'node:fs';import path from 'node:path';import http from 'node:http';import assert from 'node:assert/strict';import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';import {createRequire} from 'node:module';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const require=createRequire(path.resolve(process.env.FRONTEND_NODE_MODULES,'esbuild/package.json'));
const {build}=require('esbuild'),{chromium}=require('playwright-core');
const out=path.resolve(process.argv[2]),native=path.resolve(process.argv[3]);fs.mkdirSync(out,{recursive:false});
const snapshots=JSON.parse(fs.readFileSync(process.env.GM03_BROWSER_STATES)).snapshots,snapshot=snapshots.find(s=>s.scenario==='initial');
const ids=Object.keys(snapshot.states),entity=snapshot.target;
const foreign=structuredClone(snapshot.states[entity]);foreign.entity_id='media_player.synthetic_foreign';foreign.attributes={friendly_name:'Synthetic foreign integration',supported_features:545845,volume_level:.5,group_members:[foreign.entity_id]};

const config={latitude:0,longitude:0,elevation:0,unit_system:{length:'km',accumulated_precipitation:'mm',mass:'g',pressure:'Pa',temperature:'°C',volume:'L',wind_speed:'m/s'},location_name:'Offline Synthetic',time_zone:'UTC',components:['frontend','lovelace','media_player','media_source','loxone'],config_dir:'/synthetic',version:'2026.10.4',state:'RUNNING',safe_mode:false,internal_url:null,external_url:null,currency:'GBP',country:'GB',language:'en',debug:false,whitelist_external_dirs:[],allowlist_external_dirs:[],allowlist_external_urls:[]};
const panel={component_name:'lovelace',icon:'hass:view-dashboard',title:'Overview',config:{mode:'yaml'},url_path:'lovelace',require_admin:false};
const results=[],errors=[],unknownWS=[],blocked=[],services=[],requests=[],nativeCalls=[];let browser,server,page,publishNative,currentStates;
try{
 fs.copyFileSync(path.resolve(process.argv[4]),path.join(out,'card.js'));
 const index=fs.readFileSync(path.join(native,'index.html'),'utf8').replace(/\{%[-]?[\s\S]*?for extra_module[\s\S]*?endfor [-]?%\}/,'').replace(/\{%[-]?[\s\S]*?for extra_script[\s\S]*?endfor [-]?%\}/,'').replace('{{ theme_color }}','#03a9f4');
 assert.ok(!index.includes('{%'));fs.writeFileSync(path.join(out,'offline-index.html'),index);
 const mime={'.js':'application/javascript','.json':'application/json','.css':'text/css','.html':'text/html','.svg':'image/svg+xml','.png':'image/png','.woff2':'font/woff2'};
 server=http.createServer((req,res)=>{
  const url=new URL(req.url,'http://127.0.0.1');let file;
  if(url.pathname==='/'||url.pathname.startsWith('/lovelace'))file=path.join(out,'offline-index.html');
  else if(url.pathname==='/gm03.js')file=path.join(out,'card.js');
  else{file=path.resolve(native,'.'+url.pathname);if(!file.startsWith(native+path.sep)){res.writeHead(403).end();return;}}
  try{res.setHeader('Content-Type',mime[path.extname(file)]||'application/octet-stream');res.end(fs.readFileSync(file));}catch{res.writeHead(404).end();}
 });await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin=`http://127.0.0.1:${server.address().port}`;
 browser=await chromium.launchPersistentContext(path.join(out,'browser-profile'),{executablePath:'/snap/bin/chromium',headless:true,hasTouch:true,serviceWorkers:'block',viewport:{width:768,height:900},args:['--no-sandbox','--disable-dev-shm-usage']});
 await browser.route('**/*',r=>{
  const url=r.request().url();requests.push(url.replace(origin,''));if(!url.startsWith(origin+'/')){blocked.push(url);return r.abort();}
  const p=new URL(url).pathname;if(p.startsWith('/api/')||p==='/manifest.json')return r.fulfill({json:p==='/api/onboarding'?[]:p==='/api/config'?config:{}});return r.continue();
 });
 await browser.routeWebSocket('**/api/websocket',ws=>{
  assert.ok(ws.url().startsWith(origin.replace('http:','ws:')+'/'));
  ws.send(JSON.stringify({type:'auth_required',ha_version:'2026.10.4'}));
  ws.onMessage(raw=>{
   const m=JSON.parse(String(raw));if(m.type==='auth'){ws.send(JSON.stringify({type:'auth_ok',ha_version:'2026.10.4'}));return;}
   const ok=result=>ws.send(JSON.stringify({id:m.id,type:'result',success:true,result})),event=event=>ws.send(JSON.stringify({id:m.id,type:'event',event}));
   if(m.type==='subscribe_entities'){ok(null);publishNative=states=>{currentStates=structuredClone({...states,[foreign.entity_id]:foreign});event({a:Object.fromEntries(Object.values(currentStates).map(s=>[s.entity_id,{s:s.state,a:s.attributes,lc:Date.now()/1000,c:'synthetic'}]))});};publishNative(snapshot.states);return;}
   if(m.type==='frontend/subscribe_user_data'||m.type==='frontend/subscribe_system_data'){ok(null);event({value:m.key==='core'?{onboarded_version:'2026.10',onboarded_date:'2026-10-01'}:null});return;}
   if(['subscribe_events','unsubscribe_events','supported_features','persistent_notification/subscribe','labs/subscribe'].includes(m.type)){ok(null);return;}
   if(m.type==='call_service'){
    services.push(m);nativeCalls.push({domain:m.domain,service:m.service,data:structuredClone(m.service_data),target:structuredClone(m.target),states:structuredClone(currentStates)});
    if(m.service_data?.action==='remove')setTimeout(()=>publishNative(snapshots.find(s=>s.scenario==='removed-five').states),220);ok({context:{id:'synthetic-service'}});return;
   }
   const map={get_config:config,get_states:Object.values(snapshot.states),get_services:{media_player:{join:{fields:{}},unjoin:{fields:{}},media_play:{fields:{}},media_pause:{fields:{}},volume_set:{fields:{}}}},get_panels:{lovelace:panel},
    'frontend/get_themes':{default_theme:'default',default_dark_theme:null,themes:{}},'auth/current_user':{id:'synthetic-owner',name:'Offline Test',is_owner:true,is_admin:true,credentials:[],mfa_modules:[],local_only:true},
    'config/entity_registry/list_for_display':{entities:[...ids.map(ei=>({ei,lb:[],pl:'loxone'})),{ei:foreign.entity_id,lb:[],pl:'synthetic_other'}],entity_categories:{}},'config/entity_registry/list':[], 'config/device_registry/list':[], 'config/area_registry/list':[], 'config/floor_registry/list':[], 'config/label_registry/list':[],
    'repairs/list_issues':{issues:[]},'recorder/info':{backlog:0,migration_in_progress:false,recording:true},
    'lovelace/config':{title:'Synthetic ordinary dashboard',views:[{title:'Home',path:'home',cards:[{type:'media-control',entity},{type:'custom:loxone-group-control-card'}]}]},
    'lovelace/resources':[{id:'synthetic-gm03',url:'/gm03.js',type:'module'}],'lovelace/info':{resource_mode:'yaml'},'lovelace/dashboards/list':[],'frontend/get_user_data':{value:null},'frontend/get_system_data':{value:null},'brands/access_token':{token:'SYNTHETIC_NOT_A_SECRET'},'config/entity_registry/get':null,
    'frontend/get_translations':{resources:{}},'frontend/get_icons':{resources:{}},'http/config':{server_port:8123,ssl_certificate:null,ssl_key:null,pending_config:null},'config_entries/get':[], 'persistent_notification/get':[], 'history/stream':{}, 'ping':null};
   if(Object.hasOwn(map,m.type)){ok(map[m.type]);return;}unknownWS.push(m.type);ok(null);
  });
 });
 await browser.addInitScript(({origin})=>{
  localStorage.setItem('hassTokens',JSON.stringify({hassUrl:origin,clientId:origin+'/',access_token:'SYNTHETIC_NOT_A_SECRET',refresh_token:'SYNTHETIC_NOT_A_SECRET',expires:Date.now()+86400000,expires_in:86400,token_type:'Bearer'}));localStorage.setItem('selectedLanguage',JSON.stringify('en'));localStorage.setItem('defaultPanel',JSON.stringify('lovelace'));
 },{origin});
 page=await browser.newPage();page.on('pageerror',e=>errors.push(String(e)));await page.goto(origin+'/lovelace/home');
 await page.waitForFunction(()=>document.querySelector('home-assistant')?.hass?.states?.['media_player.synthetic_speaker_3'],{timeout:60000});

 const {run}=await import('./owner-supplements-r1.mjs');
 await run({page,browser,out,fs,path,assert,results,services,nativeCalls,publishNative,snapshot,mode:process.argv[5]||'all'});
 assert.deepEqual(errors,[]);assert.deepEqual(blocked,[]);
 fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({status:'PASS',engine:await browser.browser().version(),results},null,2));
}catch(error){fs.writeFileSync(path.join(out,'failure.json'),JSON.stringify({message:String(error),stack:error.stack,results},null,2));throw error;}
finally{
 if(page)fs.writeFileSync(path.join(out,'buttons.json'),JSON.stringify(await page.locator('ha-button').evaluateAll(bs=>bs.map(b=>({action:b.dataset.action,disabled:b.disabled,aria:b.getAttribute('aria-disabled'),inner:b.shadowRoot?.querySelector('button')?.disabled,html:b.outerHTML}))).catch(()=>[]),null,2));
 fs.writeFileSync(path.join(out,'services.json'),JSON.stringify(nativeCalls,null,2));
 fs.writeFileSync(path.join(out,'runtime.json'),JSON.stringify({errors,unknownWS,blocked,requests},null,2));
 if(page)await page.screenshot({path:path.join(out,'final.png')}).catch(()=>{});
 if(browser)await browser.close();if(server)await new Promise(r=>server.close(r));
 fs.rmSync(path.join(out,'browser-profile'),{recursive:true,force:true});
}
