// Additional owner regression coverage; no mutation to immutable original oracles.
export async function run({page,browser,publishNative,snapshot,services,out,fs,path,assert,results}){
 await page.locator('hui-media-control-card .more-info').click();await page.locator('more-info-media_player #grouping-button').click();
 const dialog=page.locator('loxone-group-manager-dialog'),manager=dialog.locator('loxone-group-manager');await manager.locator('[data-group-id=one]').waitFor();
 const records=[],card=page.locator('loxone-group-control-card');
 const publish=async states=>{publishNative(states);await page.waitForTimeout(200);};
 const text=()=>card.locator('ha-card').innerText();
 const show=async()=>{if(!await dialog.evaluate(d=>d._open)){await card.locator('[data-action=open]').click();await page.waitForTimeout(160);}};
 await dialog.locator('[data-action=close]').click();await page.locator('ha-more-info-dialog').evaluate(d=>d.closeDialog());await page.waitForTimeout(400);
 await publish(snapshot.states);
 records.push({kind:'confirmed',text:await text()});assert.match(await text(),/3 rooms/);assert.match(await text(),/2 rooms/);
 // Same friendly names must remain distinguishable on the CLOSED entry.
 const duplicate=structuredClone(snapshot.states);for(const i of [1,3])duplicate['media_player.synthetic_speaker_'+i].attributes.friendly_name='Same room name';await publish(duplicate);
 const dup=await text();assert.match(dup,/Same room name \(media_player.synthetic_speaker_1\)/);assert.match(dup,/Same room name \(media_player.synthetic_speaker_3\)/);records.push({kind:'duplicate',text:dup});
 const handover=structuredClone(snapshot.states);for(const i of [1,2,5]){const a=handover['media_player.synthetic_speaker_'+i].attributes;a.group_members=['media_player.synthetic_speaker_2','media_player.synthetic_speaker_5','media_player.synthetic_speaker_1'];a.loxone_group_control.members=[...a.group_members];}await publish(handover);assert.match(await text(),/Synthetic speaker 2 · 3 rooms/);records.push({kind:'handover',text:await text()});
 const free=structuredClone(snapshot.states);for(const [id,s]of Object.entries(free)){s.attributes.group_members=[id];Object.assign(s.attributes.loxone_group_control,{members:[id],group_id:null,revision:'synthetic-all-free'});}await publish(free);
 assert.match(await text(),/No confirmed audio groups/);assert.equal(await card.locator('[data-action=open]').isVisible(),false);assert.equal(await card.locator('[data-action=create]').isVisible(),true);records.push({kind:'empty',text:await text()});
 const before=services.length;await card.locator('[data-action=create]').click();await manager.locator('[data-picker=free]').waitFor();assert.equal(await manager.locator('[data-action=confirm-create] button').isDisabled(),true);assert.equal(services.length,before,'Create entry only opens the actual picker');await dialog.locator('[data-action=close]').click();await page.waitForTimeout(200);
 for(const kind of ['descriptor-unknown','unavailable','auth','disconnect']){
  const s=structuredClone(snapshot.states);if(kind==='descriptor-unknown')for(const state of Object.values(s))delete state.attributes.loxone_group_control;if(kind==='unavailable')for(const state of Object.values(s))state.state='unavailable';await publish(s);
  if(kind==='auth'||kind==='disconnect')await card.evaluate((c,kind)=>{const h=c.hass;c.hass=kind==='auth'?{...h,user:null}:{...h,connected:false};},kind);
  assert.match(await text(),/unavailable/);assert.doesNotMatch(await text(),/No confirmed/);assert.equal(await card.locator('[data-action=create] button').isDisabled(),true);assert.equal(await card.locator('[data-action=open]').isVisible(),false);records.push({kind,text:await text()});
 }
 await publish(snapshot.states);await show();
 const cdp=await browser.newCDPSession(page),swipe=async()=>{const b=await manager.locator('.content').boundingBox(),x=b.x+55,start=b.y+b.height-10,end=b.y+10;await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y:start,id:1}]});for(let i=1;i<=6;i++){await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x,y:start-(start-end)*i/6,id:1}]});const s=structuredClone(snapshot.states);s['media_player.synthetic_speaker_6'].attributes.media_title='ongoing '+i;publishNative(s);await page.waitForTimeout(40);}await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await page.waitForTimeout(100);};
 for(const [width,height,dark,large]of [[320,740,false,false],[390,844,true,true],[844,390,false,true],[1280,900,true,false]]){
  await page.setViewportSize({width,height});await publish(snapshot.states);
  await dialog.evaluate((d,{dark,large})=>{d.style.fontSize=large?'21px':'14px';d.style.setProperty('--primary-text-color',dark?'#eee':'#212121');d.style.setProperty('--card-background-color',dark?'#202020':'#fff');}, {dark,large});
  for(const mode of ['overview','picker','pending-error']){
   await manager.evaluate((m,mode)=>{m._mode=mode==='picker'?'create':'overview';m._adding=null;m._error=mode==='pending-error'?'Synthetic native failure; no retry sent.':'';m._pending=mode==='pending-error'?{}:null;m.render();},mode);
   for(let i=0;i<160;i++){await swipe();if(await manager.locator('.content').evaluate(e=>e.scrollTop>=e.scrollHeight-e.clientHeight-4))break;}
   const geometry=await dialog.evaluate(d=>{
    const m=d._manager,c=m.shadowRoot.querySelector('.content'),r=c.getBoundingClientRect(),hd=d._dialog,header=hd.shadowRoot.querySelector('ha-dialog-header'),close=d.shadowRoot.querySelector('[data-action=close]'),footer=close.shadowRoot.querySelector('button'),hit=e=>{const b=e.getBoundingClientRect();let t=document.elementFromPoint(b.x+b.width/2,b.y+b.height/2);while(t?.shadowRoot){const n=t.shadowRoot.elementFromPoint(b.x+b.width/2,b.y+b.height/2);if(!n||n===t)break;t=n;}for(let p=t;p;p=p.parentElement||p.getRootNode()?.host)if(p===e)return true;return false;};
    const members=m.shadowRoot.querySelector('.members'),section=members?.closest('section');return {top:c.scrollTop,extent:c.scrollHeight-c.clientHeight,body:r.toJSON(),footer:footer.getBoundingClientRect().toJSON(),footerHit:hit(close),header:header.getBoundingClientRect().toJSON(),shade:members&&getComputedStyle(members).backgroundColor,base:section&&getComputedStyle(section).backgroundColor,horizontalOverflow:c.scrollWidth>c.clientWidth,actions:[...m.shadowRoot.querySelectorAll('ha-button')].map(b=>({action:b.dataset.action,rect:b.shadowRoot.querySelector('button').getBoundingClientRect().toJSON()}))};
   });records.push({width,height,dark,large,mode,geometry});fs.writeFileSync(path.join(out,'supplements.json'),JSON.stringify(records,null,2));await page.screenshot({path:path.join(out,`${width}-${mode}.png`)});
   assert.ok(geometry.top>=geometry.extent-4,'Touch scroll reaches real bottom during ongoing updates in every mode');assert.ok(geometry.footerHit&&geometry.footer.height>=44&&geometry.footer.bottom<=height,'Actual Close native button visible, hittable and >=44px');assert.ok(geometry.header.bottom<=geometry.body.y);assert.equal(geometry.horizontalOverflow,false);assert.ok(geometry.actions.every(a=>a.rect.height>=44));
  }
  await manager.evaluate(m=>{m._pending=null;m._error='';m.render();});
 }
 await cdp.detach();await publish(snapshot.states);await manager.evaluate(m=>{m._mode='overview';m.render();});
 // Genuine relevant target invalidation remains non-replayable; original closure detached.
 const remove=manager.locator('[data-entity="media_player.synthetic_speaker_5"] [data-action=remove]');await remove.evaluate(b=>window.__savedOwnerRemove=b);const unavailable=structuredClone(snapshot.states);unavailable['media_player.synthetic_speaker_5'].state='unavailable';await publish(unavailable);await page.evaluate(()=>window.__savedOwnerRemove.click());assert.equal(services.length,before);
 await publish(snapshot.states);await page.evaluate(()=>window.__savedOwnerRemove.click());assert.equal(services.length,before,'Restored A never revives detached original action');
 fs.writeFileSync(path.join(out,'supplements.json'),JSON.stringify(records,null,2));results.push('closed entry multiple/duplicate/handover/empty/Create-only/unknown/auth/disconnect; real scrolling overview/picker/pending-error 320 portrait through desktop with themes/text scaling; actual header/footer hitboxes; stale removal revocation');
}
