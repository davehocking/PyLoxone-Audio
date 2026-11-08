// F4 supplement: actual native checked property, current local selection, trusted inputs.
// Separate from the immutable frozen three-case oracle; no simulated change/click/key events.
export async function run({page,out,fs,path,assert,results,services,nativeCalls,publishNative,snapshot}){
 const id='media_player.synthetic_speaker_6',other='media_player.synthetic_speaker_5',records=[];
 await page.locator('hui-media-control-card .more-info').click();await page.locator('more-info-media_player #grouping-button').click();
 const dialog=page.locator('loxone-group-manager-dialog'),m=dialog.locator('loxone-group-manager');
 const box=()=>m.locator('[data-picker=free] [data-entity="'+id+'"] ha-checkbox');
 const settle=()=>page.waitForTimeout(180);
 const save=()=>fs.writeFileSync(path.join(out,'checkbox-coherence.json'),JSON.stringify(records,null,2));
 const state=()=>box().evaluate(b=>({checked:b.checked,selected:[...b.getRootNode().host._selected],connected:b.isConnected,disabled:b.disabled,sameNode:b===window.__f4Node,sameBinding:b._binding===window.__f4Binding}));
 const coherent=(s,selected)=>{assert.deepEqual(s.selected,selected);assert.equal(s.checked,selected.includes(id));assert.ok(s.connected);assert.equal(s.disabled,false);};
 const arm=async()=>box().evaluate(b=>{window.__f4Abort?.abort();window.__f4Abort=new AbortController();window.__f4Node=b;window.__f4Binding=b._binding;window.__f4Events=[];const root=b.getRootNode();for(const type of ['keydown','keyup','click','change','pointerdown','pointerup','blur'])root.addEventListener(type,e=>{if(e.composedPath().some(n=>n.localName==='ha-checkbox'))window.__f4Events.push({type,key:e.key,repeat:e.repeat,trusted:e.isTrusted,checked:b.checked,selected:[...root.host._selected],connected:b.isConnected});},{capture:true,signal:window.__f4Abort.signal});});
 const reset=async(selected=false)=>{await m.evaluate(m=>{if(m._pending){const h=m.hass;m.hass={...h,connected:false};m.hass=h;}});publishNative(snapshot.states);await settle();await m.locator('[data-action=create]').click();await settle();if(selected){await box().click();await settle();}await box().scrollIntoViewIfNeeded();await box().focus();await arm();coherent(await state(),selected?[id]:[]);};
 const update=async(kind)=>{
  const s=structuredClone(snapshot.states);
  if(kind==='benign')s[id].attributes.media_title='F4 benign title';
  if(kind==='name')s[id].attributes.friendly_name='Synthetic speaker 6 renamed';
  if(kind==='volume'){s[id].attributes.loxone_room_volume_level=.62;s[id].attributes.volume_level=.62;}
  if(['revision','owner','group-ABA'].includes(kind))for(const v of Object.values(s)){const d=v.attributes.loxone_group_control;if(kind==='revision')d.revision='f4-revision';if(kind==='owner')d.owner='f4-owner';if(kind==='group-ABA'&&d.group_id==='one')d.group_id='f4-other-group';}
  if(kind==='auth-ABA'){await m.evaluate(m=>{const h=m.hass;m.hass={...h,user:{...h.user,id:'f4-other-user'}};});await settle();publishNative(snapshot.states);await settle();return;}
  publishNative(s);await settle();if(['owner','group-ABA'].includes(kind)){publishNative(snapshot.states);await settle();}
 };
 for(const selected of [false,true])for(const kind of ['static','benign','name','volume','revision','owner','group-ABA','auth-ABA','refocus','reopen','picker-context']){
  await reset(selected);const n=services.length,before=await state();await page.keyboard.down('Space');
  if(['benign','name','volume','revision','owner','group-ABA','auth-ABA'].includes(kind))await update(kind);
  if(kind==='refocus'){await m.locator('[data-action=create] button').focus();await box().focus();}
  if(kind==='reopen'){await dialog.locator('[data-action=close]').click();await settle();await page.locator('more-info-media_player #grouping-button').click();await m.locator('[data-action=create]').click();await settle();}
  if(kind==='picker-context'){await m.locator('[data-action=back]').click();await m.locator('[data-action=create]').click();await settle();}
  await box().focus();const ready=await state(),preserves=['static','benign','name','refocus'].includes(kind),readySelected=preserves&&selected?[id]:[];coherent(ready,readySelected);
  if(!['owner','reopen','picker-context'].includes(kind))assert.equal(ready.sameNode,true);
  if(['name','volume','revision','group-ABA','auth-ABA','picker-context'].includes(kind))assert.equal(ready.sameBinding,false);
  await page.keyboard.down('Space');await page.keyboard.up('Space');await settle();
  const after=await state(),legitimate=['static','benign'].includes(kind),expected=legitimate?(selected?[]:[id]):readySelected;coherent(after,expected);assert.equal(services.length,n);
  const heldEvents=await page.evaluate(()=>window.__f4Events);assert.ok(heldEvents.some(e=>e.type==='keydown'&&e.repeat&&e.trusted));assert.ok(heldEvents.some(e=>e.type==='change'),'Native widget emitted change, not a guard-only probe');
  await box().focus();await page.keyboard.press('Space');await settle();const recovery=await state();coherent(recovery,expected.includes(id)?[]:[id]);assert.equal(services.length,n);
  records.push({name:(selected?'selected':'empty')+'/'+kind,status:'PASS',before,ready,after,recovery,heldEvents,events:await page.evaluate(()=>window.__f4Events),services:services.length-n});save();
 }
 // Refused deselection must retain a different still-valid staged room as well.
 await reset();const twoFree=structuredClone(snapshot.states),members=['media_player.synthetic_speaker_1','media_player.synthetic_speaker_2'];for(const e of members){twoFree[e].attributes.group_members=members;twoFree[e].attributes.loxone_group_control.members=members;}twoFree[other].attributes.group_members=[other];twoFree[other].attributes.loxone_group_control={...twoFree[id].attributes.loxone_group_control,members:[other]};publishNative(twoFree);await settle();await box().click();const otherBox=m.locator('[data-picker=free] [data-entity="'+other+'"] ha-checkbox');await otherBox.click();await box().focus();await arm();const n=services.length;
 await page.keyboard.down('Space');twoFree[id].attributes.friendly_name='Synthetic speaker 6 renamed';publishNative(twoFree);await settle();await page.keyboard.down('Space');await page.keyboard.up('Space');await settle();const retained=await state();assert.deepEqual(new Set(retained.selected),new Set([id,other]));assert.equal(retained.checked,true);assert.equal(await otherBox.evaluate(b=>b.checked),true);
 await page.keyboard.press('Space');await settle();coherent(await state(),[other]);assert.equal(services.length,n);records.push({name:'selected/refusal-retains-other-staged-room',status:'PASS',retained,recovery:await state(),events:await page.evaluate(()=>window.__f4Events),services:0});save();
 // Genuine pointer recovery after stale key; pointer also revokes a still-held key.
 for(const during of [false,true]){
  await reset();const n=services.length;await page.keyboard.down('Space');await update('volume');
  if(!during){await page.keyboard.down('Space');await page.keyboard.up('Space');await settle();coherent(await state(),[]);}
  await box().click();await settle();coherent(await state(),[id]);
  if(during){await page.keyboard.down('Space');await page.keyboard.up('Space');await settle();coherent(await state(),[id]);}
  await box().click();await settle();coherent(await state(),[]);assert.equal(services.length,n);records.push({name:'pointer/'+(during?'during-held-key':'after-refusal'),status:'PASS',events:await page.evaluate(()=>window.__f4Events),services:0});save();
 }
 // Existing Add mode retains its immediate guarded service path, not staged Create.
 for(const kind of ['static','volume','leader-handover']){
  await reset();await m.locator('[data-action=back]').click();await m.locator('[data-group-id=one] [data-action=add]').click();await settle();await box().focus();await arm();const n=services.length;
  await page.keyboard.down('Space');
  if(kind==='volume')await update('volume');
  if(kind==='leader-handover'){const s=structuredClone(snapshot.states),members=['media_player.synthetic_speaker_2','media_player.synthetic_speaker_1','media_player.synthetic_speaker_5'];for(const e of members){s[e].attributes.group_members=members;s[e].attributes.loxone_group_control.members=members;}publishNative(s);await settle();}
  await page.keyboard.down('Space');await page.keyboard.up('Space');await settle();assert.equal(services.length-n,kind==='static'?1:0);
  if(kind!=='static'){coherent(await state(),[]);await box().focus();await page.keyboard.press('Space');await settle();}
  assert.equal(services.length-n,1);const calls=nativeCalls.slice(n),call=calls[0];assert.equal(call.domain,'loxone');assert.equal(call.service,'audio_group_manage');assert.deepEqual(call.target,{entity_id:kind==='leader-handover'?'media_player.synthetic_speaker_2':'media_player.synthetic_speaker_1'});assert.deepEqual(call.data,{action:'add',revision:snapshot.states[id].attributes.loxone_group_control.revision,group_id:'one',members:[id]});assert.deepEqual((await state()).selected,[]);assert.equal((await state()).checked,false);records.push({name:'add/'+kind,status:'PASS',calls,events:await page.evaluate(()=>window.__f4Events)});save();
 }
 await reset();assert.equal(records.length,28);results.push(...records.map(r=>r.name));
}
