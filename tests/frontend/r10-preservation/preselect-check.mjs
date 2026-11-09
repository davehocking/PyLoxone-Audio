// Current compiled native HA app; synthetic state, services and authentication.
export async function run(ctx){
 const {page,assert,results,services,snapshots,publishNative}=ctx;
 const free=snapshots.find(s=>s.scenario==='independent'),initial=snapshots.find(s=>s.scenario==='initial'),origin=free.target;
 const more=page.locator('ha-more-info-dialog more-info-media_player');
 const dialog=page.locator('loxone-group-manager-dialog'),manager=dialog.locator('loxone-group-manager');
 const open=async id=>{await page.evaluate(id=>document.querySelector('home-assistant').dispatchEvent(new CustomEvent('hass-more-info',{bubbles:true,composed:true,detail:{entityId:id}})),id);await page.waitForFunction(id=>{function walk(r){for(const e of r.querySelectorAll('*')){if(e.localName==='more-info-media_player'&&e.stateObj?.entity_id===id)return true;if(e.shadowRoot&&walk(e.shadowRoot))return true;}return false;}return walk(document);},id);};
 if(ctx.mode==='global'){
  await page.locator('loxone-group-control-card [data-action=create]').click();
  await dialog.locator('[data-action=close]').waitFor({state:'visible'});
  assert.deepEqual(await manager.evaluate(m=>[...m._selected]),[]);assert.deepEqual(services,[]);
  results.push('Fresh direct global card Create physical click has no preselected room');return;
 }
 publishNative(free.states);await open(origin);
 await more.locator('#grouping-button').click();
 await dialog.locator('ha-button[data-action=close]').waitFor({state:'visible'});
 await manager.locator('[data-action=create]').click();
 const checkbox=manager.locator(`[data-entity="${origin}"] ha-checkbox`);
 await checkbox.waitFor({state:'visible'});
 assert.equal(await checkbox.evaluate(n=>n.checked),true,'The initiating free native speaker must already be selected');
 assert.deepEqual(await manager.evaluate(m=>[...m._selected]),[origin]);
 assert.deepEqual(services,[]);
 results.push('Native More-info Group/Join -> Create preselects exact free initiating speaker with zero service calls');
 // A restored login must not resurrect an old contextual default.
 await manager.evaluate(m=>{const h=m.hass;m.hass={...h,user:{...h.user,id:'synthetic-other-owner'}};m.hass=h;});
 assert.deepEqual(await manager.evaluate(m=>[...m._selected]),[]);
 await manager.locator('[data-action=back]').click();await manager.locator('[data-action=create]').click();
 assert.deepEqual(await manager.evaluate(m=>[...m._selected]),[],'Authentication ABA must revoke the old contextual preselection');
 results.push('Authentication ABA clears staged selection and revokes contextual default through Back/re-entry');
 const close=async()=>{await dialog.locator('[data-action=close]').click();await dialog.locator('[data-action=close]').waitFor({state:'hidden'});};
 await close();
 // Exercise every real exported room through the native entry; grouped rooms stay unselected.
 for(const width of[390,1280]){
  await page.setViewportSize({width,height:844});
  for(const id of Object.keys(free.states)){
   publishNative(free.states);await open(id);await more.locator('#grouping-button').click();
   await dialog.locator('[data-action=close]').waitFor({state:'visible'});await manager.locator('[data-action=create]').click();
   const grouped=free.states[id].attributes.group_members.length>1;
   assert.deepEqual(await manager.evaluate(m=>[...m._selected]),grouped?[]:[id]);
   assert.equal(await manager.locator('[data-action=create]').count(),0);
   if(!grouped){
    const cb=manager.locator(`[data-entity="${id}"] ha-checkbox`);
    assert.equal(await cb.evaluate(n=>n.checked),true);
    await cb.locator('input').press('Space');await page.waitForTimeout(30);
    assert.deepEqual(await manager.evaluate(m=>[...m._selected]),[],'Origin can be deselected using the native checkbox');
    const benign=structuredClone(free.states);benign[id].attributes.media_position+=1;publishNative(benign);await page.waitForTimeout(30);
    assert.deepEqual(await manager.evaluate(m=>[...m._selected]),[],'Benign feedback must not re-apply a deselected default');
    await manager.locator('[data-action=back]').click();await manager.locator('[data-action=create]').click();
    assert.deepEqual(await manager.evaluate(m=>[...m._selected]),[id]);
   }
   await close();
  }
 }
 results.push('All12native origins at390/1280: free preselection/deselection/benign feedback/Back, grouped-origin no stealing, zero services');
 assert.deepEqual(services,[]);
 // A source change must retire an old connected Create callback.
 await dialog.evaluate((d,id)=>d.showDialog({entity:id,preselectEntity:id}),origin);
 await manager.locator('[data-action=create]').evaluate(n=>window.__oldCreate=n.onclick);
 const other=Object.keys(free.states).find(id=>id!==origin&&free.states[id].attributes.group_members.length===1);
 await dialog.evaluate((d,id)=>d.showDialog({entity:id,preselectEntity:id}),other);
 await page.evaluate(()=>window.__oldCreate());assert.equal(await manager.locator('[data-action=confirm-create]').count(),0);
 await manager.locator('[data-action=create]').click();assert.deepEqual(await manager.evaluate(m=>[...m._selected]),[other]);await close();
 results.push('Current native origin follows dialog reuse; old callback cannot pick a new speaker');
 // Global card entry has no implicit room anchor, including after contextual reuse.
 await page.locator('ha-more-info-dialog').evaluate(d=>{if(typeof d.closeDialog!=='function')throw new Error('Native close API absent');d.closeDialog();});
 const card=page.locator('loxone-group-control-card');await card.evaluate(c=>c.open('create'));
 await dialog.locator('[data-action=close]').waitFor({state:'visible'});assert.deepEqual(await manager.evaluate(m=>[...m._selected]),[]);await close();
 results.push('Actual global card Create starts empty after contextual reuse');
 publishNative(initial.states);
 const leader=initial.states[initial.target].attributes.group_members[0];await open(leader);
 const controls=await more.evaluate(m=>{const found=[];function walk(r){for(const n of r.querySelectorAll('*')){if(/slider|progress/.test(n.localName))found.push({tag:n.localName,label:n.getAttribute('aria-label'),class:n.className,disabled:n.disabled});if(n.shadowRoot)walk(n.shadowRoot);}}walk(m.shadowRoot);return found;});
 ctx.fs.writeFileSync(ctx.path.join(ctx.out,'native-seek-controls.json'),JSON.stringify(controls,null,2));
 assert.ok(controls.some(c=>c.tag==='ha-slider'&&c.class!=='volume-slider'&&c.disabled===false),'Actual native group-leader seek slider must be enabled');
 results.push('Actual native group-leader seek slider is present and enabled');
 const {run:preserve}=await import('./route-check.mjs');await preserve(ctx);
}
