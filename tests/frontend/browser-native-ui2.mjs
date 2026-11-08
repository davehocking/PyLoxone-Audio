// Actual complete pinned HA frontend application. Only backend is synthetic.
import fs from 'node:fs';import path from 'node:path';import http from 'node:http';import assert from 'node:assert/strict';import crypto from 'node:crypto';
import {fileURLToPath, pathToFileURL} from 'node:url';import {createRequire} from 'node:module';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const require=createRequire(path.resolve(process.env.FRONTEND_NODE_MODULES,'esbuild/package.json'));
const {build}=require('esbuild'),{chromium}=require('playwright-core');
const out=path.resolve(process.argv[2]),native=path.resolve(process.argv[3]);fs.mkdirSync(out,{recursive:false});
const snapshots=JSON.parse(fs.readFileSync(path.join(root,'tests/frontend/room-ui-states.json'))),snapshot=snapshots.find(s=>s.scenario==='confirmed');
const ids=Object.keys(snapshot.states),entity=snapshot.target;
const config={latitude:0,longitude:0,elevation:0,unit_system:{length:'km',accumulated_precipitation:'mm',mass:'g',pressure:'Pa',temperature:'°C',volume:'L',wind_speed:'m/s'},location_name:'Offline Synthetic',time_zone:'UTC',components:['frontend','lovelace','media_player','media_source','loxone'],config_dir:'/synthetic',version:'2026.10.4',state:'RUNNING',safe_mode:false,internal_url:null,external_url:null,currency:'GBP',country:'GB',language:'en',debug:false,whitelist_external_dirs:[],allowlist_external_dirs:[],allowlist_external_urls:[]};
const panel={component_name:'lovelace',icon:'hass:view-dashboard',title:'Overview',config:{mode:'yaml'},url_path:'lovelace',require_admin:false};
const results=[],errors=[],unknownWS=[],blocked=[],services=[],requests=[],nativeCalls=[];let browser,server,page,publishNative,currentStates;
try{
 await build({entryPoints:[path.join(root,'adapters/pyloxone/frontend/src/group-control-card.js')],outfile:path.join(out,'card.js'),bundle:true,format:'esm',target:'es2022',legalComments:'inline'});
 // Render only the two server-template variables; all native JS bytes unmodified.
 const index=fs.readFileSync(path.join(native,'index.html'),'utf8').replace(/\{%[-]?[\s\S]*?for extra_module[\s\S]*?endfor [-]?%\}/,'').replace(/\{%[-]?[\s\S]*?for extra_script[\s\S]*?endfor [-]?%\}/,'').replace('{{ theme_color }}','#03a9f4');
 assert.ok(!index.includes('{%'),'All synthetic server template blocks rendered');
 fs.writeFileSync(path.join(out,'offline-index.html'),index);
 const mime={'.js':'application/javascript','.json':'application/json','.css':'text/css','.html':'text/html','.svg':'image/svg+xml','.png':'image/png','.woff2':'font/woff2'};
 server=http.createServer((req,res)=>{
  const url=new URL(req.url,'http://127.0.0.1');let file;
  if(url.pathname==='/'||url.pathname.startsWith('/lovelace'))file=path.join(out,'offline-index.html');
  else if(url.pathname==='/ui1.js')file=path.join(out,'card.js');
  else{file=path.resolve(native,'.'+url.pathname);if(!file.startsWith(native+path.sep)){res.writeHead(403).end();return;}}
  try{res.setHeader('Content-Type',mime[path.extname(file)]||'application/octet-stream');res.end(fs.readFileSync(file));}catch{res.writeHead(404).end();}
 });await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin=`http://127.0.0.1:${server.address().port}`;
 browser=await chromium.launchPersistentContext(path.join(out,'browser-profile'),{executablePath:'/snap/bin/chromium',headless:true,serviceWorkers:'block',viewport:{width:768,height:900},args:['--no-sandbox','--disable-dev-shm-usage']});const context=browser;
 await context.route('**/*',r=>{
  const url=r.request().url();requests.push(url.replace(origin,''));if(!url.startsWith(origin+'/')){blocked.push(url);return r.abort();}
  const p=new URL(url).pathname;if(p.startsWith('/api/')||p==='/manifest.json')return r.fulfill({json:p==='/api/onboarding'?[]:p==='/api/config'?config:{}});return r.continue();
 });
 await context.routeWebSocket('**/api/websocket',ws=>{
  assert.ok(ws.url().startsWith(origin.replace('http:','ws:')+'/'));
  ws.send(JSON.stringify({type:'auth_required',ha_version:'2026.10.4'}));
  ws.onMessage(raw=>{
   const m=JSON.parse(String(raw));if(m.type==='auth'){ws.send(JSON.stringify({type:'auth_ok',ha_version:'2026.10.4'}));return;}
   const ok=result=>ws.send(JSON.stringify({id:m.id,type:'result',success:true,result})),event=event=>ws.send(JSON.stringify({id:m.id,type:'event',event}));
   if(m.type==='subscribe_entities'){ok(null);publishNative=states=>{currentStates=structuredClone(states);event({a:Object.fromEntries(Object.values(states).map(s=>[s.entity_id,{s:s.state,a:s.attributes,lc:Date.now()/1000,c:'synthetic'}]))});};publishNative(snapshot.states);return;}
   if(m.type==='frontend/subscribe_user_data'||m.type==='frontend/subscribe_system_data'){ok(null);event({value:m.key==='core'?{onboarded_version:'2026.10',onboarded_date:'2026-10-01'}:null});return;}
   if(['subscribe_events','unsubscribe_events','supported_features','persistent_notification/subscribe','labs/subscribe'].includes(m.type)){ok(null);return;}
   if(m.type==='call_service'){
    services.push(m);
    const groups=[...new Map(Object.values(currentStates).map(s=>s.attributes.loxone_group_control).filter(d=>d&&d.members.length>1).map(d=>[d.group_id,{id:d.group_id,members:[...d.members]}])).values()];
    nativeCalls.push({domain:m.domain,service:m.service,data:structuredClone(m.service_data),target:structuredClone(m.target),groups,staticEntities:Object.values(currentStates).filter(s=>!s.attributes.loxone_group_control).map(s=>s.entity_id),mode:'immediate',states:structuredClone(currentStates)});
    ok({context:{id:'synthetic-service'}});return;
   }
   const map={get_config:config,get_states:Object.values(snapshot.states),get_services:{media_player:{join:{fields:{}},unjoin:{fields:{}},media_play:{fields:{}},media_pause:{fields:{}},volume_set:{fields:{}}}},get_panels:{lovelace:panel},
    'frontend/get_themes':{default_theme:'default',default_dark_theme:null,themes:{}},'auth/current_user':{id:'synthetic-owner',name:'Offline Test',is_owner:true,is_admin:true,credentials:[],mfa_modules:[],local_only:true},
    'config/entity_registry/list_for_display':{entities:ids.map(ei=>({ei,lb:[],pl:'loxone'})),entity_categories:{}},'config/entity_registry/list':[], 'config/device_registry/list':[], 'config/area_registry/list':[], 'config/floor_registry/list':[], 'config/label_registry/list':[],
    'repairs/list_issues':{issues:[]},'recorder/info':{backlog:0,migration_in_progress:false,recording:true},
    'lovelace/config':{title:'Synthetic ordinary dashboard',views:[{title:'Home',path:'home',cards:[{type:'custom:loxone-group-control-card',entity,presentation:'player'},{type:'custom:loxone-group-control-card',entity}]}]},
    'lovelace/resources':[{id:'synthetic-ui1',url:'/ui1.js',type:'module'}],'lovelace/info':{resource_mode:'yaml'},'lovelace/dashboards/list':[],'frontend/get_user_data':{value:null},'frontend/get_system_data':{value:null},'brands/access_token':{token:'SYNTHETIC_NOT_A_SECRET'},'config/entity_registry/get':null,
    'frontend/get_translations':{resources:{}},'frontend/get_icons':{resources:{}},'http/config':{server_port:8123,ssl_certificate:null,ssl_key:null,pending_config:null},'config_entries/get':[], 'persistent_notification/get':[], 'history/stream':{}, 'ping':null};
   if(Object.hasOwn(map,m.type)){ok(map[m.type]);return;}unknownWS.push(m.type);ok(null);
  });
 });
 await context.addInitScript(({origin})=>{
  localStorage.setItem('hassTokens',JSON.stringify({hassUrl:origin,clientId:origin+'/',access_token:'SYNTHETIC_NOT_A_SECRET',refresh_token:'SYNTHETIC_NOT_A_SECRET',expires:Date.now()+86400000,expires_in:86400,token_type:'Bearer'}));localStorage.setItem('selectedLanguage',JSON.stringify('en'));localStorage.setItem('defaultPanel',JSON.stringify('lovelace'));
 },{origin});
 page=await context.newPage();page.on('pageerror',e=>errors.push(String(e)));await page.goto(origin+'/lovelace/home');
 await page.waitForFunction(()=>document.querySelector('home-assistant')?.hass?.states?.['media_player.synthetic_speaker_3'],{timeout:60000});
 const cards=page.locator('loxone-group-control-card');await cards.first().waitFor({timeout:30000});assert.equal(await cards.count(),2);
 const card=cards.first(),stock=card.locator('hui-media-control-card');
 await stock.waitFor({timeout:12000});
 assert.equal(await stock.locator('ha-card').count(),1,'actual built-in card rendered, not just a helper stub');
 assert.ok(await stock.locator('.more-info').isVisible());
 assert.equal(await cards.nth(1).locator('hui-media-control-card').count(),0,'standalone button mode retained');
 assert.equal(services.length,0,'creating native player and opening dashboard sends no service');
 await page.waitForTimeout(100);assert.deepEqual(errors,[],'lazy native player must be configured before reactive update');
 results.push('actual pinned built-in media-control card on ordinary dashboard via real loadCardHelpers.createCardElement; standalone button retained; no creation service');
 await stock.locator('.join-media').click();await card.locator('dialog[open]').waitFor({timeout:2000});
 assert.equal(await page.locator('dialog-join-media-players').count(),0,'own native Groups route must not open stock dialog');
 assert.equal(await card.locator('[data-action=open]').isVisible(),false,'duplicate companion hidden only for attached supported route');
 for(const id of ids.slice(0,4)){
  const button=card.locator(`[data-entity="${id}"] [data-action=row-play]`),icon=button.locator('ha-svg-icon');
  await icon.locator('svg path.primary-path').waitFor();
  assert.equal(await icon.locator('svg path.primary-path').getAttribute('d'),'M8,5.14V19.14L19,12.14L8,5.14Z');
  const geometry=await button.evaluate(el=>{const r=el.getBoundingClientRect();return {width:r.width,height:r.height};});assert.ok(geometry.width>=44&&geometry.height>=44);
 }
 // Feed actual HA state into existing complete native/card instances, no UI stub.
 await card.evaluate((el,id)=>{const states={...el.hass.states,[id]:{...el.hass.states[id],state:'playing'}};el.hass={...el.hass,states};},ids[0]);
 assert.equal(await card.locator(`[data-entity="${ids[0]}"] [data-action=row-play] ha-svg-icon svg path`).getAttribute('d'),'M14,19H18V5H14M6,19H10V5H6V19Z');
 for(const [action,expected] of [['volume-minus','M19,13H5V11H19V13Z'],['volume-plus','M19,13H13V19H11V13H5V11H11V5H13V11H19V13Z']]){
  assert.equal(await card.locator(`[data-entity="${ids[0]}"] [data-action=${action}] ha-svg-icon svg path`).getAttribute('d'),expected,'proper stepper icon actually renders native HA SVG');
 }
 assert.equal(await card.locator('[data-action=group-play] ha-svg-icon svg path').getAttribute('d'),'M14,19H18V5H14M6,19H10V5H6V19Z');
 await page.screenshot({path:path.join(out,'native-popup.png'),fullPage:true});
 results.push('actual HA ha-svg-icon renders standard play/pause SVG in full pinned app; accessible room/top controls and 44px touch targets');
 await card.locator('[data-action=context]').selectOption(ids[3]);
 await stock.waitFor();await page.waitForFunction(id=>{
  const walk=root=>{for(const el of root.querySelectorAll('*')){if(el.localName==='hui-media-control-card'&&el._config?.entity===id)return true;if(el.shadowRoot&&walk(el.shadowRoot))return true;}return false;};return walk(document);
 },ids[3]);
 assert.equal(await stock.evaluate(el=>el._config.entity),ids[3]);assert.equal(await stock.locator('ha-card').count(),1);assert.equal(services.length,0);
 await card.locator('[data-action=context]').selectOption(entity);await stock.waitFor();
 assert.equal(await stock.evaluate(el=>el._config.entity),entity);
 await page.keyboard.press('Escape');await card.locator('dialog[open]').waitFor({state:'detached'});
 await stock.locator('.more-info').click();await page.locator('more-info-media_player').waitFor({timeout:15000});
 assert.equal(await card.locator('dialog[open]').count(),0,'standard more-info never redirected to custom popup');
 results.push('real stock More-info caller still opens native More-info, not intercepted');
 // Fresh owning application for keyboard control; More-info's independent
 // native adaptive-dialog focus trap is not a custom-card override surface.
 await page.reload();await stock.locator('.join-media').waitFor();
 await stock.locator('.join-media').locator('button').focus();
 await page.keyboard.press('Enter');
 await card.locator('dialog[open]').waitFor({timeout:2000});
 assert.equal(await page.locator('dialog-join-media-players').count(),0,'scoped native button must open custom popup instead of stock join');
 results.push('PRODUCT: real native Groups icon and keyboard route to custom popup; duplicate companion hidden; zero stock join dialog/service');
 await page.keyboard.press('Escape');
 await cards.nth(1).evaluate(async (container,entity)=>{
  const helpers=await window.loadCardHelpers(),player=helpers.createCardElement({type:'media-control',entity});
  await customElements.whenDefined('hui-media-control-card');await Promise.resolve();
  player.hass=document.querySelector('home-assistant').hass;
  player.style.cssText='position:fixed;top:10px;left:10px;width:500px;z-index:10000';container.shadowRoot.append(player);window.unmodifiedPlayer=player;
 },entity);
 await cards.nth(1).locator('hui-media-control-card').locator('.join-media').click();
 await page.locator('dialog-join-media-players').waitFor({state:'attached',timeout:15000});
 await page.waitForFunction(()=>{
  const walk=root=>{for(const el of root.querySelectorAll('*')){if(el.localName==='dialog-join-media-players')return el;if(el.shadowRoot){const found=walk(el.shadowRoot);if(found)return found;}}};
  return walk(document)?.shadowRoot?.querySelector('ha-dialog')?.open===true;
 });
 assert.equal(await card.locator('dialog[open]').count(),0);
 results.push('FEASIBILITY negative control: separate untouched default HA player still opens stock join; no global changes');
 await page.keyboard.press('Escape');await page.evaluate(()=>window.unmodifiedPlayer.remove());
 // A changed native layout must restore the companion and leave native stock
 // behavior intact. Fixture remains inside actual Lovelace owning DOM.
 await page.reload();await stock.locator('.join-media').waitFor();
 await stock.locator('.join-media').evaluate(el=>el.className='ui2-unknown-groups');
 await card.locator('[data-action=open]').waitFor({state:'visible'});
 await stock.locator('.ui2-unknown-groups').click();await page.locator('dialog-join-media-players').waitFor({state:'attached'});
 assert.equal(await card.locator('dialog[open]').count(),0,'unknown layout leaves stock callback intact');
 await page.reload();await stock.locator('.join-media').waitFor();
 await stock.locator('.join-media').evaluate(el=>el.remove());await card.locator('[data-action=open]').waitFor({state:'visible'});
 await card.locator('[data-action=open]').click();await card.locator('dialog[open]').waitFor();
 await page.keyboard.press('Escape');
 results.push('unsupported native button match and missing button restore usable companion; actual stock callback preserved in owning Lovelace DOM');
 await page.reload();await stock.locator('.join-media').waitFor();
 // Capture saved old listeners/players before changing runtime context.
 await card.evaluate(el=>window.savedBinding=el._nativeBinding);
 await stock.locator('.join-media').click();await card.locator('[data-action=context]').selectOption(ids[3]);
 await stock.locator('.join-media').waitFor();await page.keyboard.press('Escape');
 await card.evaluate(el=>window.savedBinding.listener({composedPath:()=>[window.savedBinding.button],preventDefault:()=>{throw new Error('stale route intercepted');},stopImmediatePropagation:()=>{throw new Error('stale route intercepted');}}));
 assert.equal(await card.locator('dialog[open]').count(),0);
 await stock.locator('.join-media').click();await card.locator('dialog[open]').waitFor();
 assert.equal(await card.locator('[data-action=context]').inputValue(),ids[3]);await page.keyboard.press('Escape');
 await card.evaluate(el=>{window.detachedCard=el;window.owningParent=el.parentNode;el.remove();});
 assert.equal(await page.evaluate(()=>window.detachedCard._nativeBinding),null);
 await page.evaluate(()=>window.owningParent.append(window.detachedCard));await stock.locator('.join-media').waitFor();
 await stock.locator('.join-media').click();await card.locator('dialog[open]').waitFor();await page.keyboard.press('Escape');
 results.push('context rebuild invalidates saved listener; exact selected native player follows; detach removes instance listener and reconnect attaches usable native route');
 // Genuine pending room request blocks native controls and context. No HA
 // websocket mutation: only this card's service completion is synthetic here.
 await card.evaluate(el=>{el.hass={...el.hass,callService:()=>new Promise(resolve=>window.nativeRelease=resolve)};});
 await stock.locator('.join-media').click();await card.locator('[data-action=group-play]').click();
 assert.equal(await card.locator('.native-player').evaluate(el=>el.inert),true);
 await stock.locator('.join-media').evaluate(el=>el.dispatchEvent(new MouseEvent('click',{bubbles:true,composed:true,cancelable:true})));
 assert.equal(await page.locator('dialog-join-media-players').count(),0,'programmatic native event cannot bypass pending guard');
 await page.evaluate(()=>window.nativeRelease());await page.waitForFunction(()=>!window.detachedCard._pending);await page.keyboard.press('Escape');
 assert.equal(await card.locator('.native-player').evaluate(el=>el.inert),false);
 for(const authChange of ['connection','auth','owner']){
  await page.reload();await stock.locator('.join-media').waitFor();
  await card.evaluate((el,kind)=>{window.invalidBinding=el._nativeBinding;if(kind==='connection')el.hass={...el.hass,connected:false};if(kind==='auth')el.hass={...el.hass,user:null};if(kind==='owner'){const states=structuredClone(el.hass.states);states[el._entity].attributes.loxone_group_control.owner='wrong';el.hass={...el.hass,states};}},authChange);
  await card.locator('[data-action=open]').waitFor({state:'visible'});
  await card.evaluate(el=>window.invalidBinding.listener({composedPath:()=>[window.invalidBinding.button],preventDefault:()=>{throw new Error('revoked route intercepted');},stopImmediatePropagation:()=>{throw new Error('revoked route intercepted');}}));
  assert.equal(await card.locator('dialog[open]').count(),0);
 }
 await page.reload();await stock.locator('.join-media').waitFor();
 results.push('genuine pending blocks native mouse/keyboard controls; auth/connection/owner revocation restores fallback and invalidates old listeners; subsequent real native instance recovers');
 await cards.nth(1).locator('[data-action=open]').click();await cards.nth(1).locator('dialog[open]').waitFor();
 assert.equal(services.length,0,'all access/presentation/context operations are read-only');
 await page.keyboard.press('Escape');
 // Failure injection wraps the REAL loader/factory, never a fake native card.
 await page.evaluate(async entity=>{
  window.realLoader=window.loadCardHelpers;window.realHelpers=await window.realLoader();window.lateCreations=0;
  window.loadCardHelpers=()=>new Promise(resolve=>window.releaseHelper=()=>resolve({...window.realHelpers,createCardElement:config=>{window.lateCreations++;return window.realHelpers.createCardElement(config);}}));
  const el=document.createElement('loxone-group-control-card');el.style.cssText='position:fixed;top:10px;left:10px;width:500px;z-index:10000';el.setConfig({entity,presentation:'player'});el.hass=document.querySelector('home-assistant').hass;document.body.append(el);window.fixture=el;
 },entity);
 const fixture=page.locator('body > loxone-group-control-card');
 await fixture.locator('[data-role=player-status]').filter({hasText:'Native player unavailable'}).waitFor({timeout:7000});
 await fixture.locator('[data-action=open]').click();await fixture.locator('dialog[open]').waitFor();await page.keyboard.press('Escape');
 await page.evaluate(()=>window.releaseHelper());await page.waitForTimeout(150);
 assert.equal(await page.evaluate(()=>window.lateCreations),0,'timed-out helper must not create a late native player');
 assert.equal(await fixture.locator('hui-media-control-card').count(),0);
 await page.evaluate(entity=>{window.fixture.remove();window.loadCardHelpers=()=>Promise.reject(new Error('Synthetic loader failure'));const el=document.createElement('loxone-group-control-card');el.style.cssText='position:fixed;top:10px;left:10px;width:500px;z-index:10000';el.setConfig({entity,presentation:'player'});el.hass=document.querySelector('home-assistant').hass;document.body.append(el);window.fixture=el;},entity);
 await fixture.locator('[data-role=player-status]').filter({hasText:'Native player unavailable'}).waitFor();
 await fixture.locator('[data-action=open]').click();await fixture.locator('dialog[open]').waitFor();
 await page.keyboard.press('Escape');
 await page.evaluate(()=>{window.fixture.remove();window.loadCardHelpers=window.realLoader;});
 assert.equal(services.length,0,'failed/timed-out loader does not dispatch or break popup availability');
 results.push('real-loader timeout/rejection injection: no late creation, no service, shared popup stays available');
 const nudgeId=ids[1],nativeGeometry=[],feedbackStates=structuredClone(snapshot.states);
 for(const [theme,background,color] of [['light','#ffffff','#212121'],['dark','#202020','#eeeeee']])for(const width of [320,768]){
  // Lovelace rebuilds card instances at its responsive breakpoint. Establish
  // the viewport BEFORE starting this instance's operation, not mid-flight.
  await page.setViewportSize({width,height:480});await page.waitForTimeout(150);await stock.locator('.join-media').waitFor();
  await stock.locator('.join-media').click();await card.locator('dialog[open]').waitFor();
  await card.evaluate((el,{background,color})=>{el.style.setProperty('--card-background-color',background);el.style.setProperty('--primary-text-color',color);},{background,color});
  const requested=Math.round(feedbackStates[nudgeId].attributes.volume_level*100)+1,count=services.length;
  await card.locator(`[data-entity="${nudgeId}"] [data-action=volume-plus]`).click();await page.waitForTimeout(120);
  assert.equal(services.length,count+1);const request=services.at(-1);assert.equal(request.domain,'media_player');assert.equal(request.service,'volume_set');
  assert.deepEqual(request.target,{entity_id:nudgeId});assert.deepEqual(request.service_data,{volume_level:requested/100});
  assert.equal(await card.evaluate(el=>el._pending),true,'real HA websocket ACK still needs native volume feedback');
  for(const position of [0,.5,1]){
   const g=await card.evaluate((el,position)=>{const d=el._dialog,b=el.shadowRoot.querySelector('[role=status]');d.scrollTop=position*(d.scrollHeight-d.clientHeight);const r=b.getBoundingClientRect(),dr=d.getBoundingClientRect();return {top:r.top,bottom:r.bottom,dialogTop:dr.top,dialogBottom:dr.bottom,opacity:getComputedStyle(b).opacity,controlOpacity:getComputedStyle(el.shadowRoot.querySelector('input[type=range]')).opacity};},position);
   assert.ok(g.top>=g.dialogTop&&g.bottom<=g.dialogBottom+1&&g.bottom>g.top);assert.equal(g.opacity,'1');assert.equal(g.controlOpacity,'0.25');nativeGeometry.push({theme,width,position,...g});
  }
  feedbackStates[nudgeId].attributes.volume_level=requested/100;publishNative(feedbackStates);
  await card.evaluate(el=>window.currentNative=el);await page.waitForFunction(()=>!window.currentNative._pending);
  assert.equal(await card.locator(`[data-entity="${nudgeId}"] output`).innerText(),requested+'%');
  assert.equal(await card.locator('dialog').getAttribute('aria-busy'),'false');assert.equal(services.length,count+1);await page.keyboard.press('Escape');
 }
 fs.writeFileSync(path.join(out,'native-busy-geometry.json'),JSON.stringify(nativeGeometry,null,2)+'\n');
 results.push('actual native SVG minus/plus and real HA callService/websocket row volume_set; ACK blocks until owning HA native state update; actual-app 320/768 light/dark pending banner visibility and .25 control dimming');
 assert.deepEqual(errors,[]);assert.deepEqual(blocked,[]);
 fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({status:'PASS',frontend:'20260930.5',coreFixture:'2026.10.4',chromium:browser.browser().version(),results,limits:['Complete real frontend with synthetic backend; not household installation, physical sound or synchrony']},null,2)+'\n');
 console.log(JSON.stringify({status:'PASS',results}));
}catch(error){fs.writeFileSync(path.join(out,'failure.json'),JSON.stringify({status:'FAIL',message:String(error),stack:error.stack,results},null,2)+'\n');throw error;}
finally{
 const sha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
 if(fs.existsSync(path.join(out,'card.js')))fs.writeFileSync(path.join(out,'browser-service-calls.json'),JSON.stringify({provenance:'Complete actual HA frontend callService/websocket with synthetic backend; native state snapshots before each emitted call',source_sha256:sha(path.join(root,'adapters/pyloxone/frontend/src/group-control-card.js')),asset_sha256:sha(path.join(out,'card.js')),states_sha256:sha(path.join(root,'tests/frontend/room-ui-states.json')),calls:nativeCalls},null,2)+'\n');
 fs.writeFileSync(path.join(out,'traffic.json'),JSON.stringify({errors,unknownWS,blocked,services,requests},null,2)+'\n');
 if(page)fs.writeFileSync(path.join(out,'page.html'),await page.content().catch(()=>''));
 if(browser)await browser.close();if(server)await new Promise(r=>server.close(r));fs.rmSync(path.join(out,'browser-profile'),{recursive:true,force:true});
}
