// Strict owned native-widget mode extension through the full compiled app.
export async function run({page,assert,results,services,nativeCalls,pendingReplies,publishNative,snapshot,snapshots,mode}){
 const states=structuredClone(snapshot.states),follower=snapshot.target,leader=states[follower].attributes.group_members[0];
 const more=page.locator('more-info-media_player');
 const open=async id=>{await page.evaluate(id=>document.querySelector('home-assistant').dispatchEvent(new CustomEvent('hass-more-info',{detail:{entityId:id},bubbles:true,composed:true})),id);await more.waitFor({state:'visible'});await page.waitForFunction(id=>{function walk(r){for(const e of r.querySelectorAll('*')){if(e.localName==='more-info-media_player'&&e.stateObj?.entity_id===id&&e.shadowRoot?.querySelector('#grouping-button'))return true;if(e.shadowRoot&&walk(e.shadowRoot))return true;}return false;}return walk(document);},id);};
 const owned=()=>more.locator('[data-loxone-mode]');
 const settle=async()=>{await page.waitForTimeout(120);};
 const publish=async s=>{publishNative(s);await settle();};
 await publish(states);await open(follower);await settle();
 if(mode==='positive'){
  assert.equal(states[follower].state,'idle');
  assert.equal(await owned().count(),2,'truthful idle follower needs exactly two visible native widgets');
  for(const action of ['shuffle_set','repeat_set']){
   const b=more.locator(`[action=${action}]`);assert.equal(await b.count(),1);assert.equal(await b.isVisible(),true);assert.equal(await b.evaluate(n=>n.localName),'ha-icon-button');
   assert.ok(await b.evaluate(n=>n.path?.length>10));assert.ok(await b.locator('ha-svg-icon').count());
  }
  assert.equal(await more.locator('[data-loxone-media-leader]').isVisible(),true);
  const shuffle=more.locator('[data-loxone-mode=shuffle]'),repeat=more.locator('[data-loxone-mode=repeat]');
  assert.equal(await shuffle.getAttribute('aria-pressed'),'true');
  await shuffle.click();await settle();
  assert.equal(services.length,1);assert.deepEqual(nativeCalls[0].data,{entity_id:follower,shuffle:false});
  assert.equal(nativeCalls[0].domain,'media_player');assert.equal(nativeCalls[0].service,'shuffle_set');
  assert.equal(await shuffle.getAttribute('aria-pressed'),'true','no optimistic update');
  for(const [current,next]of [['one','off'],['off','all'],['all','one']]){
   const s=structuredClone(states);for(const id of s[follower].attributes.group_members)Object.assign(s[id].attributes,{shuffle:false,repeat:current});await publish(s);
   assert.equal(await shuffle.getAttribute('aria-pressed'),'false');
   const before=services.length;await repeat.focus();await repeat.press('Enter');await settle();assert.equal(services.length,before+1);
   assert.deepEqual(nativeCalls.at(-1).data,{entity_id:follower,repeat:next});assert.equal(nativeCalls.at(-1).service,'repeat_set');
  }
  // Touch executes exactly once through the native accessible button.
  const before=services.length;await shuffle.tap();await settle();assert.equal(services.length,before+1);assert.deepEqual(nativeCalls.at(-1).data,{entity_id:follower,shuffle:true});
  for(const state of ['playing','paused']){
   const s=structuredClone(states);s[follower].state=state;await publish(s);
   assert.equal(await owned().count(),0);for(const a of ['shuffle_set','repeat_set'])assert.equal(await more.locator(`[action=${a}]`).count(),1,`${state} no duplicate`);
  }
  await publish(states);assert.equal(await owned().count(),2);
  results.push({id:'idle-native-widgets-values-cycle-keyboard-touch-no-optimism-active-no-duplicates',calls:nativeCalls});return;
 }
 if(mode==='guards'){
  for(const boundary of ['busy','capability','leader-value','leader-removed','leader-changed','registry','auth','unsupported','foreign','off']){
   await publish(states);await open(follower);await settle();assert.equal(await owned().count(),2);
   await owned().first().evaluate(n=>{window.heldMode=n.onclick;window.heldModeNode=n;});
   const before=services.length,s=structuredClone(states);
   if(boundary==='busy')for(const id of s[follower].attributes.group_members)s[id].attributes.loxone_group_control.busy=true;
   if(boundary==='capability')for(const id of [leader,follower])s[id].attributes.supported_features&=~(32768|262144);
   if(boundary==='leader-value')s[leader].attributes.shuffle=false;
   if(boundary==='leader-removed')delete s[leader];
   if(boundary==='leader-changed'){
    const members=[...s[follower].attributes.group_members].reverse();for(const id of members){s[id].attributes.group_members=members;s[id].attributes.loxone_group_control.members=members;}
   }
   if(boundary==='off')s[follower].state='off';
   if(['auth','registry','unsupported','foreign'].includes(boundary)){
    await page.evaluate(({boundary,follower})=>{const root=document.querySelector('home-assistant'),h=root.hass;window.savedHass=h;const n={...h,user:{...h.user},config:{...h.config},entities:{...h.entities}};if(boundary==='auth')n.user.id='synthetic-other-user';if(boundary==='unsupported')n.config.version='2099.1.0';if(boundary==='registry'||boundary==='foreign')n.entities[follower]={...n.entities[follower],platform:'synthetic_other'};root.hass=n;root.requestUpdate();}, {boundary,follower});await settle();
   }else await publish(s);
   // Old callback cannot act, including A->B->A restoration.
   await page.evaluate(()=>window.heldMode?.(new MouseEvent('click')));await settle();assert.equal(services.length,before,boundary+' stale');
   if(['auth','registry','unsupported','foreign'].includes(boundary)){await page.evaluate(()=>{const r=document.querySelector('home-assistant');r.hass=window.savedHass;r.requestUpdate();});await settle();}else await publish(states);
   await page.evaluate(()=>window.heldMode?.(new MouseEvent('click')));await settle();assert.equal(services.length,before,boundary+' ABA');
  }
  // A held physical key/pointer cannot acquire authority from a later binding.
  for(const held of ['pointer','key']){
   await publish(states);await open(follower);await settle();const b=owned().first(),before=services.length;
   await b.evaluate((n,held)=>{if(held==='pointer')n.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerId:7}));else n.dispatchEvent(new KeyboardEvent('keydown',{key:' ',bubbles:true}));window.oldModeNode=n;},held);
   const s=structuredClone(states);for(const id of s[follower].attributes.group_members)s[id].attributes.loxone_group_control.revision+='changed';await publish(s);await publish(states);
   await page.evaluate(()=>window.oldModeNode.dispatchEvent(new MouseEvent('click',{bubbles:true})));await settle();assert.equal(services.length,before,held+' held rebind');
  }
  results.push({id:'authority-capability-busy-leader-registry-user-core-fallback-and-held-ABA',services:services.length});return;
 }
 if(mode==='warning-pending'){
  assert.equal(await owned().count(),2);const b=owned().first();
  await b.click();await settle();assert.equal(services.length,1);assert.equal(pendingReplies.length,1);
  assert.equal(await b.evaluate(n=>n.disabled),true);
  await b.evaluate(n=>n.onclick(new MouseEvent('click')));assert.equal(services.length,1);
  pendingReplies[0].failure();await settle();assert.equal(services.length,1);
  assert.equal(await b.evaluate(n=>n.disabled),false);assert.match(await more.locator('[data-loxone-follower-modes] [role=alert]').innerText(),/Synthetic service refusal/);
  assert.equal(await b.getAttribute('aria-pressed'),'true');
  await b.click();await settle();assert.equal(services.length,2);
  const s=structuredClone(states);for(const id of s[follower].attributes.group_members)s[id].attributes.loxone_group_control.busy=true;
  await publish(s);assert.equal(await owned().count(),0);pendingReplies[1].success();await settle();assert.equal(services.length,2);assert.equal(await owned().count(),0);
  await publish(states);assert.equal(await owned().count(),2);assert.equal(await owned().first().getAttribute('aria-pressed'),'true');
  results.push({id:'pending-disabled-truthful-error-context-loss-late-success-no-replay',services:services.length});return;
 }
 if(mode==='lifecycle'){
  assert.equal(await owned().count(),2);const before=services.length;
  await owned().first().evaluate(n=>window.staleMode=n.onclick);
  await page.evaluate(()=>window[Symbol.for('pyloxone-audio.gm03.more-info')].stop());await settle();assert.equal(await owned().count(),0);
  await page.evaluate(()=>window.staleMode?.(new MouseEvent('click')));assert.equal(services.length,before);
  await page.evaluate(()=>window[Symbol.for('pyloxone-audio.gm03.more-info')].start());await settle();assert.equal(await owned().count(),2);
  await open(leader);await settle();assert.equal(await owned().count(),0);await open(follower);await settle();assert.equal(await owned().count(),2);
  await page.evaluate(()=>window[Symbol.for('pyloxone-audio.gm03.more-info')].dispose());await settle();assert.equal(await owned().count(),0);
  await page.evaluate(()=>window.staleMode?.(new MouseEvent('click')));assert.equal(services.length,before);
  results.push({id:'stop-start-context-reopen-dispose-stale-zero-service',services:services.length});return;
 }
 throw new Error('Unknown follower mode probe');
}
