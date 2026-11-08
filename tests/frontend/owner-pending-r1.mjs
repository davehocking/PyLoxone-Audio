// Real owning frontend pending/timeout cleanup, not a manually assigned pending flag.
export async function run({page,browser,out,fs,path,assert,results,services,nativeCalls,publishNative,snapshot}){
 await page.setViewportSize({width:390,height:740});
 await page.locator('hui-media-control-card .more-info').click();await page.locator('more-info-media_player #grouping-button').click();
 const dialog=page.locator('loxone-group-manager-dialog'),manager=dialog.locator('loxone-group-manager');await manager.locator('[data-group-id=one]').waitFor();
 const count=services.length;
 await manager.locator('[data-entity="media_player.synthetic_speaker_5"] [data-action=volume-plus]').click();
 await page.waitForFunction(()=>document.querySelector('home-assistant').shadowRoot.querySelector('loxone-group-manager-dialog')._manager._pending);
 assert.equal(services.length,count+1);const request=nativeCalls.at(-1);assert.equal(request.service,'audio_room_volume');assert.equal(request.data.volume_percent,21);assert.deepEqual(request.target,{entity_id:'media_player.synthetic_speaker_5'});
 const cdp=await browser.newCDPSession(page),samples=[];
 for(let n=0;n<5;n++){
  const content=manager.locator('.content'),b=await content.boundingBox(),x=b.x+60,start=b.y+b.height-10,end=b.y+10;
  await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y:start,id:1}]});
  for(let i=1;i<=6;i++){await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x,y:start-(start-end)*i/6,id:1}]});const s=structuredClone(snapshot.states);s['media_player.synthetic_speaker_6'].attributes.media_title='pending benign '+i;publishNative(s);await page.waitForTimeout(35);}
  await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await page.waitForTimeout(100);samples.push(await content.evaluate(e=>({top:e.scrollTop,extent:e.scrollHeight-e.clientHeight})));
 }
 assert.ok(samples.at(-1).top>=samples.at(-1).extent-4);assert.ok(await manager.evaluate(m=>!!m._pending));
 const disabled=await manager.locator('ha-button,button,input,ha-checkbox').evaluateAll(ns=>ns.every(n=>n.disabled));assert.ok(disabled,'Actual pending disables every mutation control');
 await manager.locator('[data-action=remove]').first().evaluate(b=>b.click());assert.equal(services.length,count+1);
 await dialog.locator('[data-action=close]').click();assert.equal(await dialog.evaluate(d=>d._open),true,'Cannot dismiss actual pending service');
 await page.screenshot({path:path.join(out,'actual-pending.png')});
 await page.waitForFunction(()=>!document.querySelector('home-assistant').shadowRoot.querySelector('loxone-group-manager-dialog')._manager._pending,{timeout:10000});
 const error=await manager.locator('[role=alert]').innerText();assert.match(error,/timed out|not confirmed/);assert.equal(services.length,count+1,'No automatic retry/rollback');assert.equal(await manager.locator('[data-action=create]').evaluate(b=>b.disabled),false);
 await page.screenshot({path:path.join(out,'actual-error.png')});await cdp.detach();
 fs.writeFileSync(path.join(out,'pending-evidence.json'),JSON.stringify({request,samples,error,disabled,service_count:services.length-count},null,2));results.push('actual own-room volume pending under deliberately withheld feedback; trusted scrolling with updates, disabled mutations/Close fence, real 8s error cleanup, zero retry');
}
