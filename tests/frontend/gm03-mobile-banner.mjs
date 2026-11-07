// Immutable banner behavioural oracle; no product implementation assumptions.
export async function run({page,manager,dialog,out,fs,path,assert,results}){
 const records=[];
 const check=async(mode,actions)=>{
  for(const fraction of [0,.5,1]){
   const data=await manager.evaluate((m,{fraction,actions})=>{
    const roots=[];let e=m;while(e){roots.push(e);e=e.parentElement||e.getRootNode()?.host;}
    const all=[...m.shadowRoot.querySelectorAll('*'),...roots,...roots.flatMap(e=>e.shadowRoot?[...e.shadowRoot.querySelectorAll('*')]:[])];
    const scrolling=[...new Set(all)].filter(e=>/auto|scroll/.test(getComputedStyle(e).overflowY)&&e.scrollHeight>e.clientHeight);
    for(const e of scrolling)e.scrollTop=fraction*(e.scrollHeight-e.clientHeight);
    const hit=e=>{const r=e.getBoundingClientRect();let t=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);while(t?.shadowRoot){const n=t.shadowRoot.elementFromPoint(r.x+r.width/2,r.y+r.height/2);if(!n||n===t)break;t=n;}let p=t;while(p){if(p===e)return true;p=p.parentElement||p.getRootNode()?.host;}return false;};
    return {fraction,scrolling:scrolling.map(e=>({tag:e.localName,cls:e.className,top:e.scrollTop,max:e.scrollHeight-e.clientHeight})),actions:actions.map(a=>{const e=m.shadowRoot.querySelector(`[data-action=${a}]`),r=e?.getBoundingClientRect();return {action:a,rect:r?.toJSON(),hit:!!e&&hit(e)};})};
   },{fraction,actions});
   await page.screenshot({path:path.join(out,`${mode}-${fraction}.png`)});records.push({mode,...data});
  }
 };
 await check('overview',['create']);
 // Return ancestors to top before ordinary real click.
 await manager.evaluate(m=>{for(const e of [m,...m.shadowRoot.querySelectorAll('*')])e.scrollTop=0;let p=m;while(p){p.scrollTop=0;for(const e of p.shadowRoot?.querySelectorAll('*')||[])e.scrollTop=0;p=p.parentElement||p.getRootNode()?.host;}});
 await manager.locator('[data-action=create]').click();await page.waitForTimeout(100);
 await check('picker',['confirm-create','back']);
 const close=await dialog.locator('[data-action=close]').boundingBox();
 fs.writeFileSync(path.join(out,'banner-geometry.json'),JSON.stringify({records,close},null,2));
 assert.ok(records.every(r=>r.actions.every(a=>a.hit&&a.rect.y>=0&&a.rect.y+a.rect.height<=page.viewportSize().height)),'creation/navigation must remain visible and hit-testable at top/middle/bottom');
 results.push('non-scrolling TOP actions throughout overview and long picker');
}
