// Real wall-clock finite upper bound through native app and delayed service peer.
export async function run({page,manager,publishNative,snapshots,services,nativeCalls,pendingReplies,out,fs,path,assert,results}){
 const party=snapshots.find(s=>s.scenario==='party12');assert.ok(party);publishNative(party.states);await page.waitForTimeout(150);
 const count=party.states[party.target].attributes.group_members.length;assert.equal(count,12);
 const bound=(count+2)*8000+2000,before=services.length,start=Date.now();
 await manager.locator('[data-master] [data-action=group-play]').first().click();
 await page.waitForTimeout(bound-500);
 const held=await manager.evaluate(m=>({pending:!!m._pending,error:m._error}));assert.equal(held.pending,true);assert.equal(held.error,'');
 await page.waitForTimeout(1100);
 const ended=await manager.evaluate(m=>({pending:!!m._pending,error:m._error}));
 assert.equal(ended.pending,false);assert.match(ended.error,/timed out/);assert.equal(services.length,before+1);assert.equal(pendingReplies.length,1);
 pendingReplies.shift()();await page.waitForTimeout(150);assert.equal(services.length,before+1);assert.equal(await manager.evaluate(m=>m._error),ended.error);
 fs.writeFileSync(path.join(out,'finite-deadline.json'),JSON.stringify({count,bound,elapsed:Date.now()-start,held,ended,calls:nativeCalls.slice(before)},null,2));results.push('All12 native UI finite114s bound, truthful timeout and ignored late success, one send/no replay');
}
