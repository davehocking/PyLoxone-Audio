// Full pinned native HA media-control card and More-info entry points.
export async function run(ctx){
 const {page,assert,results,services,publishNative,snapshots}=ctx;
 const initial=snapshots.find(s=>s.scenario==='initial'),free=snapshots.find(s=>s.scenario==='independent');
 const follower=initial.target,leader=initial.states[follower].attributes.group_members[0];
 const playing=structuredClone(initial.states);
 for(const id of initial.states[follower].attributes.group_members){playing[id].state='playing';playing[id].attributes.audio_position_frozen=false;}
 const card=page.locator('hui-media-control-card').first();
 const opened=()=>page.evaluate(()=>{function walk(r){let a=[];for(const n of r.querySelectorAll('*')){if(['loxone-group-manager-dialog','dialog-join-media-players'].includes(n.localName))a.push({tag:n.localName,open:!!n._open||!!n.shadowRoot?.querySelector('ha-dialog')?.open,entity:n._entity||null});if(n.shadowRoot)a.push(...walk(n.shadowRoot));}return a;}return walk(document);});
 const close=async()=>{for(const tag of ['loxone-group-manager-dialog','dialog-join-media-players'])await page.locator(tag).evaluateAll(ds=>{for(const d of ds)d.closeDialog?.();});await page.waitForFunction(()=>{function modal(r){for(const n of r.querySelectorAll('*')){if(n.localName==='dialog'&&n.matches(':modal'))return true;if(n.shadowRoot&&modal(n.shadowRoot))return true;}return false;}return !modal(document);},null,{timeout:5000});};
 const configure=async(id,states)=>{publishNative(states);await card.evaluate((c,id)=>c.setConfig({type:'media-control',entity:id}),id);await card.locator('ha-icon-button.join-media').waitFor({state:'visible',timeout:5000});};
 const clickAndCheck=async(id,custom,role,keyboard=false)=>{
  if(keyboard)await card.locator('ha-icon-button.join-media').locator('button').press('Enter');
  else await card.locator('ha-icon-button.join-media').click();
  await page.waitForFunction(()=>{function walk(r){for(const n of r.querySelectorAll('*')){if(['loxone-group-manager-dialog','dialog-join-media-players'].includes(n.localName)&&(n._open||n.shadowRoot?.querySelector('ha-dialog')?.open))return true;if(n.shadowRoot&&walk(n.shadowRoot))return true;}return false;}return walk(document);},null,{timeout:5000});
  const active=(await opened()).filter(d=>d.open);
  assert.deepEqual(active.map(d=>d.tag),[custom?'loxone-group-manager-dialog':'dialog-join-media-players'],`${role}: the native card must open exactly the intended grouping dialog`);
  if(custom){
   assert.equal(active[0].entity,id);const manager=page.locator('loxone-group-manager-dialog loxone-group-manager');assert.equal(await manager.evaluate(m=>m._mode),'overview');
   await manager.locator('[data-action=create]').click();
   const expected=await manager.evaluate((m,id)=>m.hass.states[id].attributes.group_members.length===1?[id]:[],id);
   assert.deepEqual(await manager.evaluate(m=>[...m._selected]),expected,'Card origin must preselect only a free initiating room, never steal a grouped room');
  }
  assert.deepEqual(services,[]);await close();
 };
 for(const width of[390,1280]){
  await page.setViewportSize({width,height:900});
  await configure(leader,playing);assert.equal(await card.evaluate(async c=>{await c.updateComplete;return c._stateObj.state;}),'playing');await clickAndCheck(leader,true,`playing leader, ${width}`);
  await configure(follower,playing);await clickAndCheck(follower,true,`playing follower, ${width}`);
  await configure(leader,initial.states);await clickAndCheck(leader,true,`paused leader, ${width}`);
  await configure(follower,initial.states);await clickAndCheck(follower,true,`follower, ${width}`);
  await configure(free.target,free.states);await clickAndCheck(free.target,true,`independent, ${width}`);
  results.push(`Native media card leader/follower/independent at${width}: exact custom manager origin, zero services`);
 }
 // Every synthetic room goes through the same actual native card caller.
 for(const id of Object.keys(free.states)){
  await configure(id,free.states);await clickAndCheck(id,true,`room ${id}`);
 }
 results.push('All12rooms use the same native-card Group entry');
 await configure(leader,playing);await clickAndCheck(leader,true,'playing leader Enter key',true);
 results.push('Actual native keyboard Enter opens the same exact leader manager');
 await configure('media_player.synthetic_foreign',initial.states);await clickAndCheck('media_player.synthetic_foreign',false,'foreign integration');
 results.push('Foreign native card keeps the stock grouping dialog');
 // Missing cross-member evidence must not be relaxed to make the button work.
 const invalid=structuredClone(initial.states);invalid[follower].attributes.loxone_group_control.revision='synthetic-mismatched-revision';
 await configure(leader,invalid);await clickAndCheck(leader,false,'inconsistent member revision');
 results.push('Inconsistent native group evidence retains the existing native fallback');
 // Stopping this supported instance removes the added card route too.
 await configure(leader,initial.states);
 await page.evaluate(()=>window[Symbol.for('pyloxone-audio.gm03.more-info')].stop());
 await clickAndCheck(leader,false,'stopped installer');
 await page.evaluate(()=>window[Symbol.for('pyloxone-audio.gm03.more-info')].start());
 await clickAndCheck(leader,true,'restarted installer');
 results.push('Installer stop/start removes/restores the scoped card route without duplicate dialogs');
 // Reuse the exact accepted r9 native More-info, contextual Create, global,
 // follower shortcut and seek-control preservation checks.
 await close();await card.evaluate((c,id)=>c.setConfig({type:'media-control',entity:id}),initial.target);
 const {run:preserve}=await import('./preselect-check.mjs');await preserve(ctx);
 assert.deepEqual(services,[]);
}
