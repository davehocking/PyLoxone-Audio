// Bounded native regression: no services intended; current compiled app/widgets.
export async function run({page,browser,out,fs,path,assert,results,services,publishNative,snapshot}){
 const records=[],card=page.locator('loxone-group-control-card'),publish=async s=>{publishNative(s);await page.waitForTimeout(180);};
 const check=async(name,work)=>{try{records.push({name,status:'PASS',evidence:await work()});}catch(e){records.push({name,status:'FAIL',error:String(e),stack:e.stack});}fs.writeFileSync(path.join(out,'safety-cases.json'),JSON.stringify(records,null,2));};
 const ids=Object.keys(snapshot.states),free=ids.at(-1),first=ids[0];
 for(const kind of ['mixed-valid-group-unavailable','mixed-valid-group-unknown','mixed-all-unknown-free','missing-state','duplicate-partial','handover-partial'])await check(kind,async()=>{
  const states=structuredClone(snapshot.states),unknown=ids.slice(2,4);
  for(const id of unknown){if(kind==='missing-state')delete states[id];else if(kind.includes('unavailable'))states[id].state='unavailable';else delete states[id].attributes.loxone_group_control;}
  if(kind==='mixed-all-unknown-free')for(const id of ids.slice(0,5))delete states[id].attributes.loxone_group_control;
  if(kind==='duplicate-partial')for(const id of ids.slice(0,2))states[id].attributes.friendly_name='Duplicate leader';
  if(kind==='handover-partial')for(const id of ids.slice(0,2)){states[id].attributes.group_members=[ids[1],ids[0],ids[4]];states[id].attributes.loxone_group_control.members=[ids[1],ids[0],ids[4]];} // include third member's handover
  if(kind==='handover-partial'){states[ids[4]].attributes.group_members=[ids[1],ids[0],ids[4]];states[ids[4]].attributes.loxone_group_control.members=[ids[1],ids[0],ids[4]];}
  await publish(states);const shown=await card.locator('ha-card').innerText();assert.match(shown,/incomplete|unavailable|unknown/i);assert.doesNotMatch(shown,/No confirmed audio groups/);assert.equal(await card.locator('[data-action=create] button').isDisabled(),false);
  await card.locator('[data-action=open]').click();const m=page.locator('loxone-group-manager-dialog loxone-group-manager');assert.match(await m.locator('.content').innerText(),/incomplete|unavailable|unknown/i);
  const n=await m.locator('[data-group-id]').count();assert.equal(n,kind==='mixed-all-unknown-free'?0:1);await m.locator('[data-action=create]').click();assert.equal(await m.locator(`[data-picker=free] [data-entity="${free}"] ha-checkbox`).isEnabled(),true);assert.equal(await m.locator('[data-grouped-entity]').count(),kind==='mixed-all-unknown-free'?0:3);
  await page.locator('loxone-group-manager-dialog [data-action=close]').click();return {shown,confirmedGroups:n,services:services.length};
 });
 await publish(snapshot.states);await card.locator('[data-action=open]').click();const m=page.locator('loxone-group-manager-dialog loxone-group-manager');
 const cdp=await browser.newCDPSession(page);
 await check('meaningful-update-while-native-button-pressed',async()=>{
  const b=m.locator(`[data-entity="${first}"] [data-action=volume-plus]`);await b.scrollIntoViewIfNeeded();const box=await b.boundingBox();await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();
  const states=structuredClone(snapshot.states);states[free].attributes.loxone_room_volume_level=.63;states[free].attributes.volume_level=.63;await publish(states);await page.mouse.up();await page.waitForTimeout(100);assert.equal(services.length,0,'Old physical press cannot acquire a newly rebound action');return {services:services.length};
 });
 // Each callback is captured BEFORE an A-B-A presentation update on surviving nodes.
 await check('surviving-node-stale-handler-token-ABA',async()=>{
  await publish(snapshot.states);await m.evaluate(m=>{window.__oldBindings=[...m.shadowRoot.querySelectorAll('button,ha-button,input,ha-checkbox')].filter(n=>n.onclick||n.onchange).map(n=>({n,click:n.onclick,change:n.onchange,value:n.value}));});
  const states=structuredClone(snapshot.states);states[free].attributes.loxone_room_volume_level=.64;states[free].attributes.volume_level=.64;await publish(states);await publish(snapshot.states);
  const data=await m.evaluate(m=>{let survived=0;for(const x of window.__oldBindings){if(x.n.isConnected)survived++;if(x.click)x.click();if(x.change){x.n.value='73';x.change();}}return {captured:window.__oldBindings.length,survived};});await page.waitForTimeout(80);assert.ok(data.survived>8);assert.equal(services.length,0);return data;
 });
 await cdp.detach();assert.equal(services.length,0);results.push(...records.filter(r=>r.status==='PASS').map(r=>r.name));assert.deepEqual(records.filter(r=>r.status==='FAIL').map(r=>r.name),[]);
}
