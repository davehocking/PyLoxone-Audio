// The native service promise remains pending during slow, successful qualification.
export async function run({page,manager,services,nativeCalls,pendingReplies,out,fs,path,assert,results}){
 const before=services.length;
 await manager.locator('[data-master] [data-action=group-play]').first().click();
 await page.waitForTimeout(8400);
 const held=await manager.evaluate(m=>({pending:!!m._pending,error:m._error,status:m.shadowRoot.querySelector('[role=status]').textContent}));
 fs.writeFileSync(path.join(out,'deadline-held.json'),JSON.stringify({held,calls:nativeCalls.slice(before)},null,2));
 assert.equal(held.pending,true,'Slow successful all-member qualification must not false-fail at the old8s UI deadline');
 assert.equal(held.error,'');assert.match(held.status,/Please wait/);assert.equal(services.length,before+1);assert.equal(pendingReplies.length,1);
 pendingReplies.shift()();
 await page.waitForFunction(()=>!document.querySelector('home-assistant').shadowRoot.querySelector('loxone-group-manager-dialog')._manager._pending);
 assert.equal(await manager.evaluate(m=>m._error),'');assert.equal(services.length,before+1);
 results.push('Native UI retains pending beyond8s, consumes one delayed success without retry/false failure');
}
