// Explicit 12-room/three-member-group synthetic cadence; full native application.
export async function run({page,browser,out,fs,path,assert,results,services,publishNative,snapshot}){
 await page.setViewportSize({width:390,height:740});await page.locator('hui-media-control-card .more-info').click();await page.locator('more-info-media_player #grouping-button').click();
 const m=page.locator('loxone-group-manager-dialog loxone-group-manager'),cdp=await browser.newCDPSession(page),records=[];
 for(const mode of ['overview','picker'])for(const churn of ['volume','state','name']){
  publishNative(snapshot.states);await page.waitForTimeout(180);if(mode==='picker'&&!(await m.locator('[data-action=back]').count()))await m.locator('[data-action=create]').click();
  await m.locator('.content').evaluate(c=>{c.scrollTop=0;window.__ordinaryEvents=[];c.addEventListener('touchmove',e=>window.__ordinaryEvents.push({trusted:e.isTrusted}));});
  const samples=[];let seq=0;
  for(let j=0;j<12;j++){
   const b=await m.locator('.content').boundingBox(),x=b.x+40,start=b.y+b.height-8,end=b.y+8;
   await page.evaluate(({x,y})=>{let e=document.elementFromPoint(x,y);while(e?.shadowRoot){const next=e.shadowRoot.elementFromPoint(x,y);if(!next||next===e)break;e=next;}window.__ordinaryTarget=e;},{x,y:start});
   await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y:start,id:1}]});
   for(let i=1;i<=6;i++){
    await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x,y:start-(start-end)*i/6,id:1}]});
    const states=structuredClone(snapshot.states),id='media_player.synthetic_speaker_9',s=states[id];seq++;
    if(churn==='volume'){s.attributes.loxone_room_volume_level=(seq%2?31:32)/100;const members=s.attributes.group_members,mean=Math.round(members.reduce((sum,id)=>sum+states[id].attributes.loxone_room_volume_level*100,0)/members.length)/100;for(const id of members)states[id].attributes.volume_level=mean;}
    if(churn==='state')s.state=seq%2?'paused':'playing';
    if(churn==='name')s.attributes.friendly_name='Ordinary synthetic room 09 '+(seq%2?'aaa':'bbb');
    publishNative(states);await page.waitForTimeout(32);
   }
   await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await page.waitForTimeout(90);
   const sample=await m.locator('.content').evaluate(c=>({top:c.scrollTop,max:c.scrollHeight-c.clientHeight,targetConnected:window.__ordinaryTarget.isConnected}));samples.push(sample);if(sample.top>=sample.max-3)break;
  }
  const data=await m.evaluate((m,mode)=>{const root=m.shadowRoot,c=root.querySelector('.content'),body=c.getBoundingClientRect(),last=root.querySelector(mode==='picker'?'[data-grouped-entity="media_player.synthetic_speaker_9"]':'[data-entity="media_player.synthetic_speaker_9"]'),r=last.getBoundingClientRect(),label=last.querySelector('.name'),lr=label.getBoundingClientRect();const buttons=mode==='picker'?[last.querySelector('[data-action=remove]')]:[...root.querySelectorAll('section:last-child .group-actions ha-button')];return {top:c.scrollTop,max:c.scrollHeight-c.clientHeight,body:body.toJSON(),lastMember:{rect:r.toJSON(),visible:r.top>=body.top&&r.bottom<=body.bottom,hit:label.contains(root.elementFromPoint(lr.x+lr.width/2,lr.y+lr.height/2))},buttons:buttons.map(b=>{const r=b.shadowRoot.querySelector('button').getBoundingClientRect();return {action:b.dataset.action,visible:r.top>=body.top&&r.bottom<=body.bottom,hit:root.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===b,height:r.height};}),trusted:window.__ordinaryEvents.some(e=>e.trusted)};},mode);
  data.samples=samples;records.push({mode,churn,...data});fs.writeFileSync(path.join(out,'ordinary-scroll.json'),JSON.stringify(records,null,2));await page.screenshot({path:path.join(out,mode+'-'+churn+'.png')});
  assert.ok(samples.every(s=>s.targetConnected),'Touched descendants stay connected through meaningful ordinary feedback');assert.ok(data.top>=data.max-3);assert.ok(data.lastMember.visible&&data.lastMember.hit);assert.ok(data.buttons.every(b=>b.visible&&b.hit&&b.height>=44));assert.ok(data.trusted);assert.equal(services.length,0);
 }
 await cdp.detach();results.push('12 rooms / three three-member groups; overview/picker volume/state/name churn; last member/actions visible and hit-testable; zero services');
}
