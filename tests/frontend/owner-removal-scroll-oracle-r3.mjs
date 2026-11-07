// Owner-facing immutable r1 oracle. Actual complete HA native app and trusted Chromium events.
export async function run(ctx){
 const {page,browser,out,fs,path,assert,results,services,nativeCalls,publishNative,snapshot,mode}=ctx;
 const records=[],failures=[];
 const check=async(name,work)=>{try{const evidence=await work();records.push({name,status:'PASS',evidence});results.push(name);}catch(e){records.push({name,status:'FAIL',error:String(e),stack:e.stack});failures.push(name);}fs.writeFileSync(path.join(out,'owner-cases.json'),JSON.stringify(records,null,2));};
 const stock=page.locator('hui-media-control-card'),card=page.locator('loxone-group-control-card');
 await stock.locator('.more-info').click();await page.locator('more-info-media_player #grouping-button').click();
 const dialog=page.locator('loxone-group-manager-dialog'),manager=dialog.locator('loxone-group-manager');
 await manager.locator('[data-group-id=one]').waitFor();
 const reset=async()=>{publishNative(snapshot.states);await page.waitForTimeout(300);await manager.evaluate(m=>{m._mode='overview';m._error='';m.render();});};
 const update=()=>{const next=structuredClone(snapshot.states);next['media_player.synthetic_speaker_6'].attributes.media_title='Benign metadata '+Date.now();publishNative(next);};
 const cdp=await browser.newCDPSession(page);
 const touch=async(type,points)=>cdp.send('Input.dispatchTouchEvent',{type,touchPoints:points});
 if(['all','removal'].includes(mode))for(const method of ['mouse','touch','Space','Enter'])for(const churn of [false,true])await check(`remove-${method}-${churn?'churn':'static'}`,async()=>{
  await page.setViewportSize({width:768,height:1000});await reset();
  const target=manager.locator('[data-entity="media_player.synthetic_speaker_5"] [data-action=remove]');
  await target.scrollIntoViewIfNeeded();await target.evaluate(b=>{window.__pressed=b;window.__ownerEvents=[];for(const t of ['pointerdown','pointerup','click','keydown','keyup'])b.addEventListener(t,e=>window.__ownerEvents.push({type:t,trusted:e.isTrusted,key:e.key,connected:b.isConnected}));});
  const before=services.length,b=await target.boundingBox(),x=b.x+b.width/2,y=b.y+b.height/2;
  if(method==='touch')await touch('touchStart',[{x,y,id:1}]);else if(method==='mouse'){await page.mouse.move(x,y);await page.mouse.down();}else{await target.locator('button').focus();await page.keyboard.down(method);}
  await page.waitForTimeout(35);if(churn){update();await page.waitForTimeout(100);}
  const connected=await page.evaluate(()=>window.__pressed.isConnected);
  if(method==='touch')await touch('touchEnd',[]);else if(method==='mouse')await page.mouse.up();else await page.keyboard.up(method);
  await page.waitForTimeout(450);
  const calls=nativeCalls.slice(before),events=await page.evaluate(()=>window.__ownerEvents);
  fs.writeFileSync(path.join(out,`remove-${method}-${churn}.json`),JSON.stringify({connected,events,calls},null,2));
  assert.equal(calls.length,1,'Exactly one real removal service, not a swallowed/disconnected action or retry');
  assert.deepEqual({domain:calls[0].domain,service:calls[0].service,data:calls[0].data,target:calls[0].target},{domain:'loxone',service:'audio_group_manage',data:{action:'remove',revision:snapshot.states['media_player.synthetic_speaker_5'].attributes.loxone_group_control.revision,group_id:'one'},target:{entity_id:'media_player.synthetic_speaker_5'}});
  assert.equal(await manager.evaluate(m=>!!m._pending),false,'Confirmed feedback clears pending');
  assert.equal(await manager.locator('[data-group-id=one] [data-entity]').count(),2);
  assert.equal(await manager.locator('[data-group-id=one] [data-entity="media_player.synthetic_speaker_5"]').count(),0,'Actual confirmed member removed');
  assert.equal(await manager.locator('[data-group-id=outside] [data-entity]').count(),2);
  assert.ok(events.some(e=>e.type==='click'&&e.trusted));return {connected,events,call:{domain:calls[0].domain,service:calls[0].service,data:calls[0].data,target:calls[0].target}};
 });
 if(['all','scroll'].includes(mode))for(const [width,height]of [[390,740],[844,390],[1280,900]])for(const churn of [false,true])await check(`scroll-${width}-${height}-${churn?'churn':'static'}`,async()=>{
  await page.setViewportSize({width,height});await reset();
  const content=manager.locator('.content');
  await content.evaluate(e=>{window.__scrollNode=e;window.__scrollEvents=[];for(const t of ['touchstart','touchmove','touchend','scroll'])e.addEventListener(t,v=>window.__scrollEvents.push({type:t,trusted:v.isTrusted,top:e.scrollTop}));});
  const samples=[];
  for(let n=0;n<14;n++){
   const box=await content.boundingBox(),x=box.x+Math.min(70,box.width/3),bottom=box.y+box.height-12,top=box.y+12;
   await touch('touchStart',[{x,y:bottom,id:1}]);
   for(let i=1;i<=7;i++){await touch('touchMove',[{x,y:bottom-(bottom-top)*i/7,id:1}]);if(churn)update();await page.waitForTimeout(45);}
   await touch('touchEnd',[]);await page.waitForTimeout(120);
   samples.push(await content.evaluate(e=>({top:e.scrollTop,height:e.clientHeight,total:e.scrollHeight,connected:window.__scrollNode.isConnected})));
  }
  const geometry=await manager.evaluate(m=>{
   const c=m.shadowRoot.querySelector('.content'),r=c.getBoundingClientRect(),buttons=[...m.shadowRoot.querySelectorAll('section:last-child [data-action=add],section:last-child [data-action=destroy]')];
   return {content:r.toJSON(),top:c.scrollTop,extent:c.scrollHeight-c.clientHeight,buttons:buttons.map(b=>{const rect=b.shadowRoot.querySelector('button').getBoundingClientRect();let hit=m.shadowRoot.elementFromPoint(rect.x+rect.width/2,rect.y+rect.height/2);return {action:b.dataset.action,rect:rect.toJSON(),hit:hit===b,visible:rect.y>=r.y&&rect.bottom<=r.bottom};}),events:window.__scrollEvents};
  });
  fs.writeFileSync(path.join(out,`scroll-${width}-${churn}.json`),JSON.stringify({samples,geometry},null,2));await page.screenshot({path:path.join(out,`scroll-${width}-${churn}.png`)});
  assert.ok(samples.some(s=>s.top>50),'Real touch gesture must actually scroll');
  assert.ok(geometry.top>=geometry.extent-4,'Reach actual end of room content with updates still flowing');
  assert.ok(geometry.buttons.length===2&&geometry.buttons.every(b=>b.visible&&b.hit&&b.rect.height>=44),'Actual final Add/Destroy visible, hit-testable native 44px targets');
  const before=geometry.top;update();await page.waitForTimeout(150);assert.ok(Math.abs((await content.evaluate(e=>e.scrollTop))-before)<=2,'Ordinary update preserves scroll position');
  assert.ok(geometry.events.some(e=>e.type==='touchmove'&&e.trusted),'Trusted touch, not scrollTop assignment');return {samples,geometry};
 });
 if(['all','entry'].includes(mode))await check('closed-entry-truthful-confirmed-groups',async()=>{
  await reset();await dialog.locator('[data-action=close]').click();await page.locator('ha-more-info-dialog').evaluate(d=>d.closeDialog());await page.waitForTimeout(450);
  const text=await card.locator('ha-card').innerText();assert.match(text,/3 rooms/);assert.match(text,/2 rooms/);assert.match(text,/Synthetic speaker 1/i);assert.equal(await card.locator('[data-action=open]').innerText(),'Manage audio groups');assert.equal(await card.locator('[data-action=create]').count(),1);
  await card.locator('[data-action=open]').click();await manager.locator('[data-group-id=one]').waitFor();return {text};
 });
 if(['all','spacing'].includes(mode))for(const dark of [false,true])await check(`member-and-actions-spacing-${dark?'dark':'light'}`,async()=>{
  await page.setViewportSize({width:390,height:844});await reset();
  await page.evaluate(dark=>{const h=document.querySelector('home-assistant'),themes=h.hass.themes;h.hass={...h.hass,themes:{...themes,darkMode:dark}};document.documentElement.style.setProperty('--primary-text-color',dark?'#eee':'#212121');document.documentElement.style.setProperty('--card-background-color',dark?'#202020':'#fff');},dark);
  const layout=await manager.locator('[data-group-id=one]').evaluate(s=>{
   const q=t=>s.querySelector(t),r=e=>e.getBoundingClientRect().toJSON(),members=q('.members'),master=q('[data-master]'),add=q('[data-action=add]'),destroy=q('[data-action=destroy]');
   return {masterBorder:getComputedStyle(master).borderBottomWidth,inset:parseFloat(getComputedStyle(members).marginInlineStart),memberBackground:getComputedStyle(members).backgroundColor,sectionBackground:getComputedStyle(s).backgroundColor,members:r(members),add:r(add),destroy:r(destroy),section:r(s),internalBorders:[...members.children].slice(0,-1).map(e=>getComputedStyle(e).borderBottomWidth),roomInside:!!members.querySelector('[data-action=remove]')&&!!members.querySelector('[data-volume=room]'),masterOutside:!members.contains(master),actionsOutside:!members.contains(add)&&!members.contains(destroy)};
  });fs.writeFileSync(path.join(out,`spacing-${dark}.json`),JSON.stringify(layout,null,2));await page.screenshot({path:path.join(out,`spacing-${dark}.png`)});
  assert.equal(layout.masterBorder,'0px','Remove only redundant divider immediately above member panel');assert.equal(layout.inset,8);assert.ok(layout.roomInside&&layout.masterOutside&&layout.actionsOutside);assert.ok(layout.internalBorders.every(b=>b==='1px'));
  assert.ok(layout.add.y-layout.members.bottom>=8,'Whitespace above actions');
  const horizontal=layout.destroy.x-layout.add.right,vertical=layout.destroy.y-layout.add.bottom;assert.ok(horizontal>=8||vertical>=8,'Gap BETWEEN Add and Destroy even when wrapping');assert.ok(layout.section.bottom-Math.max(layout.add.bottom,layout.destroy.bottom)>=12,'Space below actions');return layout;
 });
 await cdp.detach();
 fs.writeFileSync(path.join(out,'browser-requests.json'),JSON.stringify(nativeCalls.filter(c=>c.service==='audio_group_manage').map(({domain,service,data,target})=>({domain,service,data,target})),null,2));
 assert.deepEqual(failures,[],'Owner outcomes failed; raw cases preserved');
}
