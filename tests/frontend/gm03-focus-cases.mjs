// GM03-R01-F01: run inside the complete pinned native application harness.
export async function focusCases({assert,fs,path,out,manager,page,publishNative,snapshot,snapshots,ids,services,nativeCalls,errors,unknownWS,blocked,movedStates,handoverStates}){
 const evidence=[],calls=[];
 const read=()=>manager.evaluate(m=>{const a=m.shadowRoot.activeElement;return {key:a?.dataset.key??null,group:a?.closest('[data-group-id]')?.dataset.groupId??null,entity:a?.closest('[data-entity],[data-grouped-entity]')?.getAttribute(a?.closest('[data-entity]')?'data-entity':'data-grouped-entity')??null,action:a?.dataset.action??null,safe:a?.dataset.focusSafe==='true',disabled:!!a?.disabled};});
 const publish=async states=>{publishNative(states);await page.waitForTimeout(180);};
 const initial=()=>structuredClone(snapshot.states);
 const unrelated=states=>{const next=structuredClone(states);next[ids[4]].attributes.loxone_room_volume_level=.21;next[ids[4]].attributes.volume_level=.21;return next;};
 const reset=async()=>{await publish(initial());if(await manager.locator('[data-action=back]').count())await manager.locator('[data-action=back]').click();};
 const stable=async(label,selector,next,activate,expected)=>{
  const loc=manager.locator(selector);await loc.focus();const before=await read();assert.ok(before.key,label+' has a logical identity');const count=services.length;
  await publish(next);const after=await read();evidence.push({label,before,after});
  assert.equal(after.key,before.key,label+' preserves exact logical key');assert.equal(after.disabled,false);
  if(activate){await page.keyboard.press(activate);await page.waitForTimeout(100);assert.equal(services.length,count+1,label+' genuine keyboard activation emits once');const request=structuredClone(nativeCalls.at(-1));calls.push({...request,label});expected(request);}
  else assert.equal(services.length,count);
 };
 const negative=async(label,selector,next)=>{
  await reset();await manager.locator(selector).focus();const before=await read(),count=services.length;await publish(next);const after=await read();evidence.push({label,before,after});
  assert.equal(after.safe,true,label+' focuses stable non-destructive container, not dialog autofocus');assert.equal(after.action,null);await page.keyboard.press('Enter');await page.waitForTimeout(80);assert.equal(services.length,count,label+' Enter never mutates a replacement target');
 };
 const check=(action,group,entity)=>r=>{assert.equal(r.service,'audio_group_manage');assert.equal(r.data.action,action);assert.equal(r.data.group_id,group);assert.deepEqual(r.target,{entity_id:entity});};
 try{
  await stable('outside-destroy-unrelated','[data-group-id=outside] [data-action=destroy]',unrelated(initial()),'Enter',check('destroy','outside',ids[2]));
  await publish(snapshots.find(s=>s.scenario==='destroyed-outside').states);await reset();
  for(const [group,id] of [['one',ids[1]],['outside',ids[3]]]){
   const next=unrelated(initial());next[id].attributes.friendly_name='AAA reordered exact room';
   await stable('overview-remove-'+group,`[data-group-id=${group}] [data-entity="${id}"] [data-action=remove]`,next,'Enter',check('remove',group,id));
   await publish(snapshots.find(s=>s.scenario==='empty').states);await reset();
  }
  await manager.locator('[data-action=create]').click();
  const grey=unrelated(initial());grey[ids[3]].attributes.friendly_name='AAA occupied reorder';
  await stable('grey-remove-outside',`[data-grouped-entity="${ids[3]}"] [data-action=remove]`,grey,'Enter',check('remove','outside',ids[3]));
  await publish(snapshots.find(s=>s.scenario==='empty').states);await reset();
  // Native handover retains group intent despite changing its command leader.
  const handover=structuredClone(handoverStates);
  await stable('group-volume-handover','[data-group-id=one] [data-master] input',handover,'ArrowRight',r=>{assert.equal(r.service,'volume_set');assert.deepEqual(r.target,{entity_id:ids[1]});});
  await publish(snapshots.find(s=>s.scenario==='empty').states);await reset();
  await stable('group-play-handover','[data-group-id=one] [data-action=group-play]',handover,'Enter',r=>{assert.equal(r.service,'media_play');assert.deepEqual(r.target,{entity_id:ids[1]});});await reset();
  await stable('add-button-handover','[data-group-id=one] [data-action=add]',handover,null);await reset();
  await stable('destroy-button-handover','[data-group-id=one] [data-action=destroy]',handover,null);await reset();
  for(const action of ['volume-minus','volume-plus']){await stable('group-'+action+'-handover',`[data-group-id=one] [data-master] [data-action=${action}]`,handover,null);await reset();}
  for(const selector of [`[data-entity="${ids[1]}"] input`,`[data-entity="${ids[1]}"] [data-action=volume-plus]`,`[data-entity="${ids[1]}"] [data-action=row-play]`])await stable('stable-room-'+selector,selector,unrelated(initial()),null);
  await stable('stable-create','[data-action=create]',unrelated(initial()),null);
  await manager.locator('[data-action=create]').click();await stable('stable-free-selection',`[data-picker=free] [data-entity="${ids[5]}"] ha-checkbox`,unrelated(initial()),null);await stable('stable-back','[data-action=back]',unrelated(initial()),null);await reset();
  await negative('group-disappears','[data-group-id=outside] [data-action=destroy]',snapshots.find(s=>s.scenario==='destroyed-outside').states);
  const owner=initial();for(const s of Object.values(owner))s.attributes.loxone_group_control.owner='different-owner';
  await negative('owner-changes','[data-group-id=outside] [data-action=destroy]',owner);
  const moved=structuredClone(movedStates);const regroup=(states,groups)=>{for(const [index,id] of ids.entries()){const members=groups.find(g=>g.players.includes(index))??{group:null,players:[index]};const a=states[id].attributes;a.group_members=members.players.map(p=>ids[p]);Object.assign(a.loxone_group_control,{group_id:members.group,members:[...a.group_members],revision:'synthetic-moved-revision'});}return states;};
  await negative('same-leader-moves-group','[data-group-id=one] [data-master] input',regroup(initial(),[{group:'outside',players:[0,1,2,3]}]));
  await negative('room-moves-group',`[data-group-id=one] [data-entity="${ids[0]}"] [data-action=remove]`,moved);
  const unavailable=initial();unavailable[ids[2]].state='unavailable';await negative('target-ineligible','[data-group-id=outside] [data-action=destroy]',unavailable);
  const busy=initial();for(const s of Object.values(busy))s.attributes.loxone_group_control.busy=true;await negative('pending-native','[data-group-id=outside] [data-action=destroy]',busy);
  await reset();await manager.locator('[data-group-id=one] [data-action=add]').click();await manager.locator(`[data-picker=free] [data-entity="${ids[5]}"] ha-checkbox`).focus();const count=services.length;
  await publish(moved);await page.keyboard.press('Space');await page.waitForTimeout(100);
  assert.equal(services.length,count+1,'Same native group Add remains keyboard usable after leader moves');const add=structuredClone(nativeCalls.at(-1));calls.push({...add,label:'add-picker-moved-leader'});check('add','one',ids[1])(add);assert.deepEqual(add.data.members,[ids[5]]);
  await publish(snapshots.find(s=>s.scenario==='empty').states);await reset();
  await manager.locator('[data-group-id=one] [data-action=add]').click();await manager.locator(`[data-picker=free] [data-entity="${ids[5]}"] ha-checkbox`).focus();await publish(snapshots.find(s=>s.scenario==='empty').states);const gone=services.length;await page.keyboard.press('Space');await page.waitForTimeout(80);assert.equal(services.length,gone,'Gone Add group must not become staged creation or another group');assert.equal((await read()).safe,true);
  await reset();
  // Delay the actual native widget update to expose ambiguous restoration/races.
  const ambiguous=await manager.evaluate(async m=>{const b=m.shadowRoot.querySelector('[data-group-id=outside] [data-action=destroy]');b.focus();m.render();const next=m.shadowRoot.querySelector('[data-group-id=outside] [data-action=destroy]');next.after(next.cloneNode(true));await new Promise(r=>setTimeout(r,50));return {safe:m.shadowRoot.activeElement?.dataset.focusSafe==='true'};});assert.equal(ambiguous.safe,true,'Never first-match an ambiguous logical identity');
  await reset();
  const keys=await manager.locator('[data-key]').evaluateAll(ns=>ns.map(n=>n.dataset.key));assert.equal(new Set(keys).size,keys.length,'Every simultaneous restorable control is unambiguous');for(const k of keys){const tuple=JSON.parse(k);assert.ok(Array.isArray(tuple)&&tuple.length>=5);}
  assert.deepEqual(errors,[]);assert.deepEqual(unknownWS,[]);assert.deepEqual(blocked,[]);
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({status:'PASS',cases:evidence.map(e=>e.label),requests:calls.length},null,2));
 }finally{fs.writeFileSync(path.join(out,'focus-evidence.json'),JSON.stringify(evidence,null,2));fs.writeFileSync(path.join(out,'focus-requests.json'),JSON.stringify(calls,null,2));}
}
