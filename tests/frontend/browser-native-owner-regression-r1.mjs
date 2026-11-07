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
    ok({context:{id:'synthetic-service'}});return;
   }
   const map={get_config:config,get_states:Object.values(snapshot.states),get_services:{media_player:{join:{fields:{}},unjoin:{fields:{}},media_play:{fields:{}},media_pause:{fields:{}},volume_set:{fields:{}}}},get_panels:{lovelace:panel},
    'frontend/get_themes':{default_theme:'default',default_dark_theme:null,themes:{}},'auth/current_user':{id:'synthetic-owner',name:'Offline Test',is_owner:true,is_admin:true,credentials:[],mfa_modules:[],local_only:true},
    'config/entity_registry/list_for_display':{entities:[...ids.map(ei=>({ei,lb:[],pl:'loxone'})),{ei:foreign.entity_id,lb:[],pl:'synthetic_other'}],entity_categories:{}},'config/entity_registry/list':[], 'config/device_registry/list':[], 'config/area_registry/list':[], 'config/floor_registry/list':[], 'config/label_registry/list':[],
    'repairs/list_issues':{issues:[]},'recorder/info':{backlog:0,migration_in_progress:false,recording:true},
    'lovelace/config':{title:'Synthetic ordinary dashboard',views:[{title:'Home',path:'home',cards:[{type:'media-control',entity}]}]},
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
 const stock=page.locator('hui-media-control-card');await stock.locator('.more-info').click();
 const more=page.locator('more-info-media_player');await more.locator('#grouping-button').waitFor();
 await more.locator('#grouping-button').click();
 await page.locator('loxone-group-manager-dialog').waitFor({state:'attached',timeout:2500});
 await page.locator('loxone-group-manager-dialog [data-action=create]').waitFor({timeout:2500});
 assert.equal(await page.locator('dialog-join-media-players').count(),0,'Expanded More-info Join must route only eligible Loxone into custom manager');
 assert.equal(services.length,0);results.push('expanded More-info Join on ordinary native dashboard without any custom card');
 assert.equal(await page.locator('loxone-group-manager-dialog [data-group-id]').count(),2,'Overview must show both actual native groups, not selected-room fiction');
 const manager=page.locator('loxone-group-manager-dialog loxone-group-manager');
 const mode=process.argv[5]||'full';
 if(mode!=='full'){
  const modules={gesture:'gm03-mobile-gesture.mjs',controls:'gm03-mobile-gesture-controls.mjs',multicontact:'gm03-mobile-multicontact.mjs',recovery:'gm03-mobile-recovery-keyboard.mjs',header:'gm03-mobile-header.mjs',banner:'gm03-mobile-banner.mjs',labels:'gm03-mobile-labels.mjs'};
  const dialog=page.locator('loxone-group-manager-dialog');
  const ctx={page,browser,manager,dialog,publishNative,snapshot,snapshots,ids,services,nativeCalls,out,fs,path,assert,results,errors,unknownWS,blocked};
  if(mode==='focus'){
   const parent=path.dirname(process.env.GM03_FOCUS_EXPORT);
   ctx.movedStates=JSON.parse(fs.readFileSync(path.join(parent,'moved-owning-states.json')));
   ctx.handoverStates=JSON.parse(fs.readFileSync(path.join(parent,'handover-owning-states.json')));
   await (await import('./gm03-focus-cases.mjs')).focusCases(ctx);
  }else await (await import('./'+modules[mode])).run(ctx);
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({status:'PASS',results,engine:await browser.browser().version()},null,2));
 }else{
 const uiCalls=[];let count=0;
 const advance=async label=>{

  const until=Date.now()+3000;while(services.length===count&&Date.now()<until)await new Promise(r=>setTimeout(r,20));
  assert.equal(services.length,++count,'Exactly one UI mutation');
  uiCalls.push({...nativeCalls.at(-1),label});
  const next=snapshots.find(s=>s.scenario===label);assert.ok(next,label);
  publishNative(next.states);await page.waitForTimeout(150);
  await manager.evaluate(m=>m._pending).then(v=>assert.ok(!v,'Wait must end on actual owning feedback'));
 };
 // Actual compiled expanded native slider. The stock caller emits entity_id in service_data.
 await page.locator('loxone-group-manager-dialog [data-action=close]').click();
 const nativeSlider=more.locator('ha-slider.volume-slider');
 assert.equal(await nativeSlider.evaluate(s=>s.value),25);
 await nativeSlider.evaluate(s=>{s.value=45;s.dispatchEvent(new Event('change',{bubbles:true,composed:true}));});
 await advance('group-volume');
 assert.equal(nativeCalls.at(-1).service,'volume_set');assert.equal(nativeCalls.at(-1).data.volume_level,.45);
 await more.locator('#grouping-button').click();await manager.locator('[data-group-id=one]').waitFor();
 await manager.locator('[data-group-id=one] [data-master] input').evaluate(s=>{s.value=55;s.dispatchEvent(new Event('change',{bubbles:true}));});
 await advance('manager-group-volume');assert.equal(nativeCalls.at(-1).service,'volume_set');assert.equal(nativeCalls.at(-1).data.volume_level,.55);
 const room=manager.locator('[data-group-id=one] [data-entity="media_player.synthetic_speaker_1"]');
 assert.equal(await room.locator('input').inputValue(),'40');
 await room.locator('input').evaluate(s=>{s.value=29;s.dispatchEvent(new Event('change',{bubbles:true}));});
 await page.waitForTimeout(50);assert.match(await manager.locator('[role=status]').innerText(),/Please wait/);
 assert.equal(await room.locator('button[data-action=volume-plus]').isDisabled(),true);
 await page.keyboard.press('Escape');await page.waitForTimeout(600);
 assert.equal(await page.locator('loxone-group-manager-dialog').evaluate(d=>d._open),true,'Native Escape cannot dismiss a pending operation');
 assert.equal(await room.locator('input').isVisible(),true,'Pending native dialog remains actually visible');
 await page.locator('loxone-group-manager-dialog ha-icon-button[data-dialog=close]').click();await page.waitForTimeout(600);
 assert.equal(await room.locator('input').isVisible(),true,'Native header close cannot dismiss pending feedback');
 await advance('room-volume');assert.equal(nativeCalls.at(-1).service,'audio_room_volume');assert.equal(nativeCalls.at(-1).data.volume_percent,29);
 await room.locator('[data-action=volume-plus]').click();await advance('room-nudge');
 assert.equal(nativeCalls.at(-1).data.volume_percent,30);
 await manager.locator('[data-action=create]').click();
 assert.equal(await manager.locator('[data-picker=free] ha-checkbox').count(),2);
 assert.equal(await manager.locator('[data-grouped-entity] ha-checkbox').evaluateAll(nodes=>nodes.filter(n=>n.disabled).length),4);
 for(const p of [5,6])await manager.locator(`[data-picker=free] [data-entity="media_player.synthetic_speaker_${p}"] ha-checkbox`).click();
 await manager.locator('[data-action=confirm-create]').click();await advance('created');
 assert.equal(await manager.locator('[data-group-id]').count(),3);
 await manager.locator('[data-group-id=outside] [data-action=destroy]').click();await advance('destroyed-outside');
 assert.equal(await manager.locator('[data-group-id]').count(),2);
 await room.locator('[data-action=remove]').click();await advance('dissolved-pair');
 assert.equal(await manager.locator('[data-group-id]').count(),1);
 await manager.locator('[data-group-id=created] [data-action=destroy]').click();await advance('empty');
 assert.equal(await manager.locator('[data-group-id]').count(),0);
 assert.equal(await manager.locator('[data-action]').count(),1,'Empty overview only Create Group, no independent anchor');
 assert.equal(await manager.locator('[data-action=create]').count(),1);
 fs.writeFileSync(path.join(out,'owning-requests.json'),JSON.stringify(uiCalls,null,2));
 results.push('native public group slider + independent raw room slider/stepper + free-only native-widget create + exact destroy + singleton dissolve + empty overview; exact requests exported');
 await page.locator('loxone-group-manager-dialog [data-action=close]').click();
 publishNative(snapshot.states);await page.waitForTimeout(400);
 // Duplicate resource execution must retain exactly one scoped binding.
 await page.evaluate(async()=>{await import('/gm03.js?duplicate');});
 await more.locator('#grouping-button ha-button button').focus();await page.keyboard.press('Enter');
 await page.waitForTimeout(150);fs.writeFileSync(path.join(out,'reopen-context.json'),JSON.stringify(await page.evaluate(()=>{const h=document.querySelector('home-assistant'),d=h.shadowRoot.querySelector('loxone-group-manager-dialog'),b=window[Symbol.for('pyloxone-audio.gm03.more-info')].binding;return {open:d._open,states:h.hass.states['media_player.synthetic_speaker_2'].attributes,binding:!!b,buttonDisabled:b?.button.disabled,dialogHass:d.hass.states['media_player.synthetic_speaker_2'].attributes};}),null,2));
 await manager.locator('[data-group-id=one]').waitFor();assert.equal(await page.locator('loxone-group-manager-dialog').count(),1);
 assert.equal(services.length,count);await page.keyboard.press('Escape');await page.waitForTimeout(150);
 assert.equal(await page.locator('loxone-group-manager-dialog').evaluate(d=>d._open),false,'Native keyboard close lifecycle');
 assert.equal(await page.locator('loxone-group-manager-dialog ha-dialog').evaluate(d=>d.open),false,'Native dismissal must reconcile public open before cached dialog reuse');
 fs.writeFileSync(path.join(out,'closed-context.json'),JSON.stringify(await page.evaluate(()=>{const root=document.querySelector('home-assistant'),more=root.shadowRoot.querySelector('ha-more-info-dialog'),manager=root.shadowRoot.querySelector('loxone-group-manager-dialog');const data=e=>({tag:e.localName,keys:Object.fromEntries(Object.keys(e).filter(k=>/open|hide|dialog/i.test(k)).map(k=>[k,typeof e[k]==='object'?String(e[k]):e[k]])),box:[e.getBoundingClientRect().width,e.getBoundingClientRect().height],style:e.getAttribute('style'),hidden:e.hidden,inert:e.inert});const children=e=>[...e.querySelectorAll('*'),...(e.shadowRoot?[...e.shadowRoot.querySelectorAll('*')].flatMap(x=>[x,...(x.shadowRoot?[...x.shadowRoot.querySelectorAll('*')]:[])]):[])].filter(e=>e.localName.includes('dialog')).map(data);return {root:data(root),more:data(more),manager:data(manager),children:[...children(more),...children(manager)]};}),null,2));
 // Compact stock caller is not overridden, even for the very same Loxone entity.
 await page.locator('ha-more-info-dialog').evaluate(d=>d.closeDialog());await page.waitForTimeout(350);
 await stock.locator('.join-media').click();await page.locator('dialog-join-media-players').waitFor({state:'attached'});
 assert.equal(await page.locator('dialog-join-media-players').evaluate(d=>!!d._open),true);
 await page.locator('dialog-join-media-players [data-dialog=close]:visible').click();
 // New module on old backend: More-info fallback stays native, never enables new row writes.
 const old=structuredClone(snapshot.states);for(const s of Object.values(old))if(s.attributes.loxone_group_control)s.attributes.loxone_group_control.version=1;
 publishNative(old);await stock.locator('.more-info').click();await more.locator('#grouping-button').click();
 await page.locator('dialog-join-media-players').waitFor({state:'attached'});
 assert.equal(await page.locator('loxone-group-manager-dialog').evaluate(d=>d._open),false);
 assert.equal(services.length,count);assert.deepEqual(errors,[]);assert.deepEqual(blocked,[]);
 results.push('duplicate module + native Enter/Escape close/reopen + untouched same-entity compact stock caller + new UI/old descriptor native fallback; no extra mutation/error');
 await page.locator('dialog-join-media-players [data-dialog=close]:visible').click();publishNative(snapshot.states);await page.waitForTimeout(400);
 await more.evaluate(m=>m.dispatchEvent(new CustomEvent('hass-more-info',{bubbles:true,composed:true,detail:{entityId:'media_player.synthetic_speaker_3'}})));await page.waitForTimeout(400);
 assert.equal(await more.evaluate(m=>m.stateObj.entity_id),'media_player.synthetic_speaker_3');
 await page.evaluate(()=>{window.__touch=[];window.addEventListener('click',e=>{const b=window[Symbol.for('pyloxone-audio.gm03.more-info')]?.binding;window.__touch.push({path:e.composedPath().map(e=>e.localName||e.constructor.name),boundId:b?.id,instanceId:b?.instance.stateObj?.entity_id,inPath:!!b&&e.composedPath().includes(b.button)});},true);});
 await more.locator('#grouping-button').tap();await page.waitForTimeout(150);fs.writeFileSync(path.join(out,'touch-context.json'),JSON.stringify(await page.evaluate(()=>{const h=document.querySelector('home-assistant'),d=h.shadowRoot.querySelector('loxone-group-manager-dialog'),s=h.shadowRoot.querySelector('dialog-join-media-players');return {events:window.__touch,open:d._open,dialogOpen:d._dialog.open,stockOpen:s?._open,history:history.state,instanceEntity:h.shadowRoot.querySelector('ha-more-info-dialog')._entityId};}),null,2));await manager.locator('[data-group-id=outside]').waitFor();
 // Free-only Add and grey explicit Remove, with real feedback transitions.
 const reset=snapshots.find(s=>s.scenario==='reset');publishNative(reset.states);await page.waitForTimeout(200);
 await manager.locator('[data-group-id=one] [data-action=add]').click();
 assert.deepEqual(await manager.locator('[data-picker=free] [data-entity]').evaluateAll(ns=>ns.map(n=>n.dataset.entity)),[ids[4],ids[5]],'Free picker is sorted independently of occupied rooms');
 await manager.locator('[data-picker=free] [data-entity="media_player.synthetic_speaker_5"] ha-checkbox').click();await advance('added-five');
 assert.equal(await manager.locator('[data-group-id=one] [data-entity]').count(),3);
 await manager.locator('[data-action=create]').click();
 const grey=manager.locator('[data-grouped-entity="media_player.synthetic_speaker_1"]');
 assert.equal(await grey.locator('ha-checkbox').evaluate(n=>n.disabled),true);
 await grey.locator('[data-action=remove]').click();
 assert.equal(await manager.locator('[data-picker=free] [data-entity="media_player.synthetic_speaker_1"]').count(),0,'No optimistic grouped-to-free move before feedback');
 assert.equal(await grey.locator('ha-checkbox').evaluate(n=>n.disabled),true);
 await advance('removed-leader-picker');
 await manager.locator('[data-group-id=one] [data-action=add]').click();
 assert.equal(await manager.locator('[data-picker=free] [data-entity="media_player.synthetic_speaker_1"] ha-checkbox').evaluate(n=>n.disabled),false);
 await manager.locator('[data-picker=free] [data-entity="media_player.synthetic_speaker_1"] ha-checkbox').click();await advance('readded-leader');
 assert.equal(await manager.locator('[data-group-id=one] [data-entity="media_player.synthetic_speaker_2"] .leader').innerText(),'Leader','Display sorting never promotes the re-added old leader');
 await manager.locator('[data-group-id=one] [data-entity="media_player.synthetic_speaker_5"] [data-action=remove]').click();await advance('removed-five');
 await manager.locator('[data-group-id=one] [data-action=destroy]').click();await advance('destroyed-one');
 assert.equal(await manager.locator('[data-group-id=outside] [data-entity]').count(),2,'Every edit preserves the independent outside group');
 fs.writeFileSync(path.join(out,'owning-requests.json'),JSON.stringify(uiCalls,null,2));
 // Selection and saved closures cannot survive external membership/availability.
 publishNative(reset.states);await page.waitForTimeout(200);await manager.locator('[data-action=create]').click();
 await manager.locator('[data-picker=free] [data-entity="media_player.synthetic_speaker_5"] ha-checkbox').click();
 await manager.locator('[data-picker=free] [data-entity="media_player.synthetic_speaker_6"] ha-checkbox').click();
 await manager.locator('[data-action=confirm-create]').evaluate(n=>{window.__savedCreate=n;});
 publishNative(snapshots.find(s=>s.scenario==='added-five').states);await page.waitForTimeout(150);
 await page.evaluate(()=>window.__savedCreate.click());assert.equal(services.length,count,'External membership invalidates the staged selection and old button');
 assert.equal(await manager.locator('[data-action=confirm-create]').evaluate(n=>n.disabled),true);
 for(const kind of ['unavailable','malformed','busy']){
  publishNative(reset.states);await page.waitForTimeout(100);await manager.locator('[data-action=back]').click();
  await manager.locator('[data-group-id=one] [data-action=destroy]').evaluate(n=>{window.__savedDestroy=n;});
  const bad=structuredClone(reset.states);for(const s of Object.values(bad)){if(kind==='unavailable')s.state='unavailable';if(kind==='malformed')s.attributes.loxone_group_control.version=999;if(kind==='busy')s.attributes.loxone_group_control.busy=true;}
  publishNative(bad);await page.waitForTimeout(100);await page.evaluate(()=>window.__savedDestroy.click());assert.equal(services.length,count,kind+' saved closure must not dispatch');
  publishNative(reset.states);await page.waitForTimeout(100);await manager.locator('[data-action=create]').click();
 }
 await manager.locator('[data-action=back]').click();
 results.push('native Add/free sorting/grey Remove waits feedback/leader order/outside preservation; external membership and stale unavailable/malformed/busy closures fail closed');
 // Every attainable integer +/- row nudge in the full compiled native host.
 const numeric=[];
 for(let p=0;p<=100;p++)for(const delta of [-1,1]){
  const before=structuredClone(reset.states),mean=Math.floor((p+40)/2+.5);
  before[ids[0]].attributes.loxone_room_volume_level=p/100;
  for(const id of [ids[0],ids[1]])before[id].attributes.volume_level=mean/100;
  publishNative(before);await page.waitForFunction(p=>{const m=document.querySelector('home-assistant').shadowRoot.querySelector('loxone-group-manager-dialog')._manager;return !m._pending&&Math.round(m.hass.states['media_player.synthetic_speaker_1'].attributes.loxone_room_volume_level*100)===p;},p);
  const button=room.locator(`[data-action=volume-${delta<0?'minus':'plus'}]`),baseline=services.length;
  if(p+delta<0||p+delta>100){assert.equal(await button.isDisabled(),true);await button.evaluate(b=>b.click());assert.equal(services.length,baseline);continue;}
  await button.evaluate(b=>b.click());
  const deadline=Date.now()+2000;while(services.length===baseline&&Date.now()<deadline)await new Promise(r=>setTimeout(r,1));
  assert.equal(services.length,baseline+1);const request=nativeCalls.at(-1);assert.equal(request.service,'audio_room_volume');assert.equal(request.data.volume_percent,p+delta);numeric.push({...request,from:p,delta});
  const after=structuredClone(before);after[ids[0]].attributes.loxone_room_volume_level=(p+delta)/100;for(const id of [ids[0],ids[1]])after[id].attributes.volume_level=Math.floor((p+delta+40)/2+.5)/100;
  publishNative(after);await page.waitForFunction(()=>!document.querySelector('home-assistant').shadowRoot.querySelector('loxone-group-manager-dialog')._manager._pending);
 }
 assert.equal(numeric.length,200);fs.writeFileSync(path.join(out,'numeric-requests.json'),JSON.stringify(numeric,null,2));count=services.length;
 results.push('200 actual integer room nudges, including 29/57/58 and disabled endpoints, preserve own-room service boundary');
 const invalidated=[];
 for(const kind of ['auth-aba','disconnect-aba','owner-takeover']){
  publishNative(reset.states);await page.waitForTimeout(120);const baseline=services.length;
  await room.locator('[data-action=volume-plus]').evaluate(b=>{window.__staleNudge=b.onclick;b.click();});
  await page.waitForTimeout(50);assert.equal(services.length,baseline+1);assert.ok(await manager.evaluate(m=>!!m._pending));
  invalidated.push({...nativeCalls.at(-1),kind});
  if(kind==='owner-takeover'){const takeover=structuredClone(reset.states);for(const s of Object.values(takeover))s.attributes.loxone_group_control.owner='synthetic-owner-takeover';publishNative(takeover);await page.waitForTimeout(80);publishNative(reset.states);}
  else await manager.evaluate((m,kind)=>{const h=m.hass;m.hass=kind==='auth-aba'?{...h,user:{...h.user,id:'synthetic-revoked-user'}}:{...h,connected:false};m.hass=h;},kind);
  await page.waitForFunction(()=>!document.querySelector('home-assistant').shadowRoot.querySelector('loxone-group-manager-dialog')._manager._pending);
  assert.match(await manager.locator('[role=alert]').innerText(),/changed|disconnect|Native/);
  await page.evaluate(()=>window.__staleNudge());await page.waitForTimeout(100);
  assert.equal(services.length,baseline+1,kind+' revocation is sticky; detached saved nudge cannot replay after A returns');
 }
 fs.writeFileSync(path.join(out,'guard-dispatches.json'),JSON.stringify(invalidated,null,2));count=services.length;
 results.push('Pending auth/disconnect A-B-A and owner takeover cancel visibly; saved detached handlers send no replay');
 await page.locator('loxone-group-manager-dialog [data-action=close]').click();await page.waitForTimeout(400);
 await more.evaluate(m=>m.dispatchEvent(new CustomEvent('hass-more-info',{bubbles:true,composed:true,detail:{entityId:'media_player.synthetic_foreign'}})));await page.waitForTimeout(400);
 await more.locator('#grouping-button').tap();await page.locator('dialog-join-media-players [data-dialog=close]:visible').waitFor();
 assert.equal(await page.locator('loxone-group-manager-dialog').evaluate(d=>d._open),false);assert.equal(services.length,count);
 await page.locator('dialog-join-media-players [data-dialog=close]:visible').click();
 await more.evaluate(m=>m.dispatchEvent(new CustomEvent('hass-more-info',{bubbles:true,composed:true,detail:{entityId:'media_player.synthetic_speaker_3'}})));await page.waitForTimeout(400);
 results.push('Foreign integration expanded More-info grouping stays stock; scoped binding restores on Loxone context');
 await page.evaluate(()=>{const s=window[Symbol.for('pyloxone-audio.gm03.more-info')];window.dispatchEvent(new Event('pagehide'));if(s.binding)throw new Error('pagehide binding retained');window.dispatchEvent(new Event('pageshow'));if(!s.binding)throw new Error('pageshow binding not restored');s.dispose();if(s.binding||window[Symbol.for('pyloxone-audio.gm03.more-info')])throw new Error('dispose retained singleton/binding');});
 await more.locator('#grouping-button').tap();await page.locator('dialog-join-media-players').waitFor({state:'attached'});assert.equal(await page.locator('dialog-join-media-players').evaluate(d=>!!d._open),true);
 assert.equal(services.length,count);assert.deepEqual(errors,[]);assert.deepEqual(blocked,[]);results.push('actual native touch after More-info entity switch + pagehide/pageshow + module dispose returns native Join; zero extra writes');
 fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({status:'PASS',results},null,2));
}
}catch(error){fs.writeFileSync(path.join(out,'failure.json'),JSON.stringify({message:String(error),stack:error.stack,results},null,2));throw error;}
finally{
 if(page)fs.writeFileSync(path.join(out,'modal-lifecycle.json'),JSON.stringify(await page.evaluate(()=>{const nodes=[];const walk=e=>{if(e instanceof Element){const c=getComputedStyle(e),r=e.getBoundingClientRect();if(/dialog|bottom-sheet|group-manager/.test(e.localName)||e.inert||e.hidden)nodes.push({tag:e.localName,id:e.id,open:e.open,_open:e._open,hidden:e.hidden,inert:e.inert,display:c.display,visibility:c.visibility,opacity:c.opacity,box:[r.x,r.y,r.width,r.height],attrs:[...e.attributes].map(a=>[a.name,a.value]),animations:e.getAnimations().map(a=>({state:a.playState,time:a.currentTime}))});}for(const n of e.children||[])walk(n);if(e.shadowRoot)walk(e.shadowRoot);};walk(document);return {nodes,history:history.state,focus:document.activeElement?.localName};}).catch(e=>({error:String(e)})),null,2));
 if(page)fs.writeFileSync(path.join(out,'model.json'),JSON.stringify(await page.locator('loxone-group-manager').evaluate(m=>({selected:[...m._selected],mode:m._mode,error:m._error,pending:!!m._pending,buttons:[...m.shadowRoot.querySelectorAll('ha-button,ha-checkbox')].map(b=>({action:b.dataset.action,key:b.dataset.key,checked:b.checked,disabled:b.disabled,html:b.shadowRoot?.innerHTML}))})).catch(()=>null),null,2));
 fs.writeFileSync(path.join(out,'traffic.json'),JSON.stringify({errors,unknownWS,blocked,services,requests},null,2));
 if(page)fs.writeFileSync(path.join(out,'dom.txt'),await page.evaluate(()=>{const walk=(el,depth=0)=>[...el.children].map(n=>' '.repeat(depth)+n.localName+(n.id?'#'+n.id:'')+'\n'+(n.shadowRoot?walk(n.shadowRoot,depth+1):'')+walk(n,depth+1)).join('');return walk(document);}).catch(()=>''));
 if(browser)await browser.close();if(server)await new Promise(r=>server.close(r));fs.rmSync(path.join(out,'browser-profile'),{recursive:true,force:true});
}
