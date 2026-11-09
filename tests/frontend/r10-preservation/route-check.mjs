// Native full-app regression; only backend fixtures are synthetic.
export async function run({page,assert,results,services,snapshot,snapshots,publishNative,out,fs,path}){
 await page.waitForFunction(()=>!!customElements.get('loxone-group-manager-dialog'));
 const follower=snapshot.target,leader=snapshot.states[follower].attributes.group_members[0];
 const more=page.locator('ha-more-info-dialog more-info-media_player');
 const open=async id=>{await page.evaluate(id=>document.querySelector('home-assistant').dispatchEvent(new CustomEvent('hass-more-info',{bubbles:true,composed:true,detail:{entityId:id}})),id);await page.waitForFunction(id=>{function walk(r){for(const e of r.querySelectorAll('*')){if(e.localName==='more-info-media_player'&&e.stateObj?.entity_id===id)return true;if(e.shadowRoot&&walk(e.shadowRoot))return true;}return false;}return walk(document);},id);};
 const link=more.locator('ha-button[data-loxone-media-leader]');
 const label=async id=>`Media controls on ${await page.evaluate(id=>document.querySelector('home-assistant').hass.states[id].attributes.friendly_name,id)}`;
 const checkLabel=async id=>{await link.waitFor({state:'visible',timeout:5000});const expected=await label(id);await page.waitForFunction(expected=>{function walk(r){for(const e of r.querySelectorAll('*')){if(e.matches?.('[data-loxone-media-leader]')&&e.textContent===expected)return true;if(e.shadowRoot&&walk(e.shadowRoot))return true;}return false;}return walk(document);},expected);assert.equal(await link.innerText(),expected);};
 await open(follower);await checkLabel(leader);
 for(const viewport of[{width:390,height:844},{width:1280,height:900}]){
  await page.setViewportSize(viewport);await link.scrollIntoViewIfNeeded();const box=await link.boundingBox();assert.ok(box.width>0&&box.x>=0&&box.x+box.width<=viewport.width&&box.y>=0&&box.y+box.height<=viewport.height);await page.screenshot({path:path.join(out,`follower-link-${viewport.width}.png`)});
 }
 // Preserve the actual obsolete navigation callback to prove ABA cannot revive it.
 await link.evaluate(n=>{window.__oldMediaLink=n;window.__oldMediaClick=n.onclick;});
 const changed=snapshots.find(s=>s.scenario==='changed-leader');publishNative(changed.states);const nextLeader=changed.states[follower].attributes.group_members[0];await checkLabel(nextLeader);
 await page.evaluate(()=>window.__oldMediaClick());assert.equal(await more.evaluate(m=>m.stateObj.entity_id),follower);
 const restored=snapshots.find(s=>s.scenario==='restored-leader');publishNative(restored.states);await checkLabel(leader);
 await page.evaluate(()=>window.__oldMediaClick());assert.equal(await more.evaluate(m=>m.stateObj.entity_id),follower);
 // Real native keyboard activation, not a fabricated service or product click.
 await link.locator('button').first().press('Enter');
 await page.waitForFunction(id=>{function walk(r){for(const e of r.querySelectorAll('*')){if(e.localName==='more-info-media_player'&&e.stateObj?.entity_id===id)return true;if(e.shadowRoot&&walk(e.shadowRoot))return true;}return false;}return walk(document);},leader);
 await page.waitForTimeout(50);assert.equal(await more.locator('[data-loxone-media-leader]').count(),0);
 assert.ok(await more.evaluate(m=>!!(m.stateObj.attributes.supported_features&131072)));
 results.push('Current leader follows native HA updates; obsolete callbacks rejected through A-B-A; Enter opens exact leader; no source services');
 await open(follower);await checkLabel(leader);await link.click();await page.waitForTimeout(50);assert.equal(await more.evaluate(m=>m.stateObj.entity_id),leader);results.push('Real pointer click opens exact leader native panel');
 await open(follower);await checkLabel(leader);publishNative(snapshots.find(s=>s.scenario==='became-leader').states);await page.waitForFunction(id=>{function walk(r){for(const e of r.querySelectorAll('*')){if(e.localName==='more-info-media_player'&&e.stateObj?.entity_id===id)return !!(e.stateObj.attributes.supported_features&131072)&&!e.shadowRoot.querySelector('[data-loxone-media-leader]');if(e.shadowRoot&&walk(e.shadowRoot))return true;}return false;}return walk(document);},follower);
 publishNative(snapshots.find(s=>s.scenario==='independent').states);await page.waitForTimeout(150);assert.equal(await link.count(),0);results.push('Leader and independent rooms retain native Browse and have no follower shortcut');
 await open('media_player.synthetic_foreign');assert.equal(await link.count(),0);await more.locator('#grouping-button').click();await page.locator('dialog-join-media-players ha-dialog ha-button').first().waitFor({state:'visible'});assert.ok(await page.locator('dialog-join-media-players ha-dialog').evaluate(d=>d.open));assert.ok((await page.locator('loxone-group-manager-dialog').evaluateAll(ds=>ds.every(d=>!d._open&&!d.shadowRoot.querySelector('ha-dialog').open))));results.push('Unrelated integration remains native; cached custom dialog stays closed');
 assert.deepEqual(services,[]);
}
