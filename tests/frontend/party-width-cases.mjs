// Actual pinned HA dialog geometry; no replacement modal or value-only interactions.
export async function run({page,manager,publishNative,snapshot,services,out,fs,path,assert,results}){
 const records=[];
 for(const [width,height] of [[390,844],[844,390],[1280,900]]){
  await page.setViewportSize({width,height});publishNative(snapshot.states);await page.waitForTimeout(180);
  records.push({viewport:{width,height},rows:await manager.evaluate(m=>[...m.shadowRoot.querySelectorAll('[data-master],.members>.row')].map(row=>{
   const input=row.querySelector('input'),vol=row.querySelector('.vol'),label=row.querySelector('.name'),play=row.querySelector('[data-action$=play]'),remove=row.querySelector('[data-action=remove]');
   const rect=e=>e?.getBoundingClientRect().toJSON();
   return {entity:row.dataset.entity||'group',input:rect(input),volume:rect(vol),row:rect(row),name:rect(label),play:rect(play),remove:rect(remove),steps:[...vol.querySelectorAll('button')].map(rect)};
  }))});
  await page.screenshot({path:path.join(out,`width-${width}.png`)});
 }
 fs.writeFileSync(path.join(out,'track-geometry.json'),JSON.stringify(records,null,2));
 for(const r of records)for(const row of r.rows){
  assert.ok(row.steps.every(s=>s.width>=44&&s.height>=44),'44px volume step targets');
  assert.ok(row.volume.y>=Math.max(row.name.bottom,row.play.bottom,row.remove?.bottom||0)-1,'Dedicated volume row MUST be beneath identity/play/remove');
  assert.ok(row.volume.width>=row.row.width-2,'Volume wrapper uses whole available row');
  assert.ok(row.input.width>=row.volume.width-2,'Range itself spans its entire available row, without sharing with steps or percentage');
 }
 assert.equal(services.length,0);results.push('Dedicated full-width room and group volume rows at portrait, landscape and desktop');
}
