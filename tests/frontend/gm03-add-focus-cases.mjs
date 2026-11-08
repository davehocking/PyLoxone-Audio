// Direct related binding regression: an open Add picker belongs to a group, not its old leader.
export async function addFocusCase({assert,fs,path,out,manager,page,publishNative,ids,services,nativeCalls,movedStates}){
 await manager.locator('[data-group-id=one] [data-action=add]').click();
 await manager.locator(`[data-picker=free] [data-entity="${ids[5]}"] ha-checkbox`).focus();
 publishNative(movedStates);await page.waitForTimeout(200);
 await page.keyboard.press('Space');await page.waitForTimeout(100);
 const actual=nativeCalls.at(-1);
 fs.writeFileSync(path.join(out,'add-context.json'),JSON.stringify({actual,services},null,2));
 assert.equal(services.length,1,'Exactly one real keyboard Add');
 assert.equal(actual.service,'audio_group_manage');assert.equal(actual.data.action,'add');
 assert.equal(actual.data.group_id,'one','Open Add picker must retain the logical group, not follow its old leader to outside');
 assert.deepEqual(actual.target,{entity_id:ids[1]});assert.deepEqual(actual.data.members,[ids[5]]);
 fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({status:'PASS'},null,2));
}
