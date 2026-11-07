// Trusted-contact follow-up: rejected nonprimary must not leave keyboard disabled.
export async function run({page,browser,manager,services,nativeCalls,out,fs,path,assert,results}){
 const cdp=await browser.newCDPSession(page),range=()=>manager.locator('[data-group-id=one] [data-master] input');
 const point=async(p,id)=>{const e=range();await e.scrollIntoViewIfNeeded();const b=await e.boundingBox();return {x:b.x+8+(b.width-16)*p/100,y:b.y+b.height/2,id};};
 const send=async(type,points)=>{await cdp.send('Input.dispatchTouchEvent',{type,touchPoints:points});await page.waitForTimeout(90);};
 const n=services.length,a=await point(25,1),b=await point(65,1),s=await point(80,2);
 await send('touchStart',[a]);await send('touchMove',[b]);await send('touchStart',[b,s]);await send('touchEnd',[b]);
 const third=await point(90,3);await send('touchStart',[s,third]);await send('touchEnd',[third]);await send('touchEnd',[]);
 assert.equal(services.length,n,'all ambiguous releases zero');
 await range().focus();await page.keyboard.press('ArrowRight');await page.waitForTimeout(120);
 fs.writeFileSync(path.join(out,'recovery-keyboard.json'),JSON.stringify({calls:nativeCalls.slice(n).map(c=>({domain:c.domain,service:c.service,data:c.data,target:c.target})),value:await range().inputValue()},null,2));
 assert.equal(services.length,n+1,'keyboard works immediately after ambiguous contacts end, without fresh pointer or hass refresh');
 assert.equal(Math.round(nativeCalls.at(-1).data.volume_level*100),26,'keyboard starts from confirmed25, not rejected90');
 await cdp.detach();results.push('no tombstone blocks subsequent real keyboard');
}
