export async function run({page,manager,publishNative,snapshot,out,fs,path,assert,results}){
 const records=[];const states=structuredClone(snapshot.states),a='media_player.synthetic_speaker_1',b='media_player.synthetic_speaker_2',c='media_player.synthetic_speaker_5',other='media_player.synthetic_speaker_3';
 const group='11111111-2222-3333-4444-555555555555';
 const name='Synthetic Kitchen Audio';states[a].attributes.friendly_name=name;states[other].attributes.friendly_name=name;
 for(const id of [a,b,c]){states[id].attributes.group_members=[a,b,c];states[id].attributes.loxone_group_control.members=[a,b,c];states[id].attributes.loxone_group_control.group_id=group;}
 publishNative(states);await page.waitForTimeout(150);
 const titles=await manager.locator('section.group h3').allTextContents();records.push({titles});
 await manager.locator('[data-action=create]').click();await page.waitForTimeout(100);
 const picker=await manager.locator('h3').allTextContents(),names=await manager.locator('[data-grouped-entity] .name').allTextContents();records.push({picker,names});
 const idsRetained=await manager.locator(`[data-grouped-entity="${a}"] [data-action=remove]`).getAttribute('data-key');
 // Confirmed leader handover, same native group and duplicate names remain distinct.
 const moved=structuredClone(states);moved[b].attributes.friendly_name='Synthetic second leader with a deliberately long friendly Audio name';
 for(const id of [a,b,c]){moved[id].attributes.group_members=[b,c,a];moved[id].attributes.loxone_group_control.members=[b,c,a];}
 publishNative(moved);await page.waitForTimeout(150);const after=await manager.locator('h3').allTextContents();records.push({after});
 fs.writeFileSync(path.join(out,'labels.json'),JSON.stringify(records,null,2));
 assert.ok(titles.includes(name+' +2')&&titles.includes(name+' +1'),'confirmed leader friendly name + OTHER count in overview, including same names');
 assert.ok(picker.includes('Already grouped · '+name+' +2'),'same readable picker heading');
 assert.ok(names.includes(name)&&!names.some(n=>n.includes(group)),'one unchanged friendly name per grouped row, no visible UUID');
 assert.ok(idsRetained.includes(group)&&idsRetained.includes(a),'exact internal group/entity identity retained');
 assert.ok(after.includes('Already grouped · '+moved[b].attributes.friendly_name+' +2'),'label follows confirmed leader handover');
 results.push('leader + OTHER count / row names / duplicate names / internal exact IDs / handover');
}
