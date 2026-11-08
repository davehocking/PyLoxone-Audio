// Immutable original Stage A behavioural oracle: compiled native HA, trusted inputs.
export async function run({page,out,fs,path,assert,results,services,nativeCalls,publishNative,snapshot}){
 const records=[],defects=[],id5='media_player.synthetic_speaker_5',id6='media_player.synthetic_speaker_6';
 const save=()=>fs.writeFileSync(path.join(out,'create-actions.json'),JSON.stringify({records,defects},null,2));
 await page.locator('hui-media-control-card .more-info').click();await page.locator('more-info-media_player #grouping-button').click();
 const dialog=page.locator('loxone-group-manager-dialog'),m=dialog.locator('loxone-group-manager');
 const settle=()=>page.waitForTimeout(180),button=a=>m.locator('[data-action='+a+']'),box=id=>m.locator('[data-picker=free] [data-entity="'+id+'"] ha-checkbox');
 const selection=()=>m.evaluate(m=>({selected:[...m._selected],checks:[...m.shadowRoot.querySelectorAll('[data-picker=free] [data-entity]')].map(r=>({id:r.dataset.entity,checked:r.querySelector('ha-checkbox').checked})),mode:m._mode}));
 const coherent=async(expected)=>{const s=await selection();assert.deepEqual(s.selected,expected);for(const c of s.checks)assert.equal(c.checked,expected.includes(c.id));return s;};
 const actions=async(name,expected)=>{
  const actual=await m.locator('.actions ha-button').evaluateAll(nodes=>nodes.map(n=>n.dataset.action));
  try{assert.deepEqual(actual,expected,'Exactly the appropriate overview OR picker actions, never both Create entries');}catch(e){defects.push({name,actual,expected,error:String(e)});}
  const geometry=await m.locator('.actions ha-button').evaluateAll(nodes=>nodes.map(n=>{const b=n.shadowRoot.querySelector('button'),r=b.getBoundingClientRect();return {action:n.dataset.action,disabled:n.disabled,nativeButton:!!b,rect:{x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom},viewport:{width:innerWidth,height:innerHeight}};}));
  for(const g of geometry){assert.ok(g.nativeButton);assert.ok(g.rect.width>=44&&g.rect.height>=44,'Native hitbox minimum44');assert.ok(g.rect.x>=0&&g.rect.y>=0&&g.rect.right<=g.viewport.width&&g.rect.bottom<=g.viewport.height,'Action remains within native dialog viewport');}
  for(let i=0;i<geometry.length;i++)for(let j=i+1;j<geometry.length;j++){const a=geometry[i].rect,b=geometry[j].rect;assert.ok(a.right+7<=b.x||b.right+7<=a.x||a.bottom+7<=b.y||b.bottom+7<=a.y,'Distinct native actions have >=8px spacing (1px tolerance)');}
  records.push({name,actual,expected,geometry,selection:await selection(),serviceCount:services.length});save();
 };
 for(const viewport of [{width:390,height:844},{width:844,height:390}]){
  await page.setViewportSize(viewport);publishNative(snapshot.states);await settle();
  const start=services.length,prefix=viewport.width+'x'+viewport.height;
  await actions(prefix+'/overview',['create']);
  await button('create').click();await settle();await coherent([]);await actions(prefix+'/picker-empty',['confirm-create','back']);assert.equal(await button('confirm-create').evaluate(b=>b.disabled),true);
  await box(id5).click();await settle();await coherent([id5]);assert.equal(await button('confirm-create').evaluate(b=>b.disabled),true);
  await box(id6).click();await settle();await coherent([id5,id6]);assert.equal(await button('confirm-create').evaluate(b=>b.disabled),false);await actions(prefix+'/picker-ready',['confirm-create','back']);
  await box(id5).click();await settle();await coherent([id6]);assert.equal(await button('confirm-create').evaluate(b=>b.disabled),true);
  await button('back').click();await settle();assert.equal((await coherent([])).mode,'overview');await actions(prefix+'/back',['create']);
  await button('create').click();await settle();await coherent([]);await actions(prefix+'/reopened',['confirm-create','back']);
  await box(id5).focus();await page.keyboard.press('Space');await settle();await coherent([id5]);await page.keyboard.press('Space');await settle();await coherent([]);
  assert.equal(services.length,start,'All navigation, local selection/deselection, Back and reopen are service-free');
  await box(id5).click();await box(id6).click();await settle();await coherent([id5,id6]);
  await button('confirm-create').click();await settle();assert.equal(services.length-start,1,'One explicit confirmation, exactly one unchanged request');
  const call=nativeCalls.at(-1);assert.equal(call.domain,'loxone');assert.equal(call.service,'audio_group_manage');assert.deepEqual(call.target,{entity_id:id5});assert.deepEqual(call.data,{action:'create',revision:snapshot.states[id5].attributes.loxone_group_control.revision,members:[id6]});
  // Synthetic feedback only after the real native owning-service emission.
  const created=structuredClone(snapshot.states),members=[id5,id6];for(const id of members){created[id].attributes.group_members=members;created[id].attributes.loxone_group_control.members=members;created[id].attributes.loxone_group_control.group_id='created';}
  publishNative(created);await settle();assert.equal((await coherent([])).mode,'overview');await actions(prefix+'/confirmed-overview',['create']);assert.equal(services.length-start,1);
  await page.screenshot({path:path.join(out,prefix+'.png')});records.push({name:prefix+'/confirmation',call,status:'PASS'});save();results.push(prefix+'/local-journey-and-one-confirmation');
 }
 assert.deepEqual(defects,[],'Duplicate Create Group entry is forbidden during create mode');
}
