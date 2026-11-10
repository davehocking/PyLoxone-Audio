import {dialogState,waitGrouping,closeGrouping} from './native-utils.mjs';
export async function run({page,assert,results,services,snapshot,publishNative,out,fs,path,mode}) {
 const follower=snapshot.target,leader=snapshot.states[follower].attributes.group_members[0];
 const more=page.locator('ha-more-info-dialog more-info-media_player');
 await page.waitForFunction(()=>!!customElements.get('loxone-group-manager-dialog'));
 const states=structuredClone(snapshot.states);
 if(mode.includes('playing'))for(const id of states[follower].attributes.group_members)states[id].state='playing';
 publishNative(states);
 await page.evaluate(id=>document.querySelector('home-assistant').dispatchEvent(new CustomEvent('hass-more-info',{bubbles:true,composed:true,detail:{entityId:id}})),follower);
 const link=more.locator('ha-button[data-loxone-media-leader]');await link.waitFor({state:'visible'});
 assert.equal(await page.locator('loxone-group-manager-dialog').count(),0,'Custom manager must not be warmed');
 const activate=async locator=>{if(mode.includes('keyboard'))await locator.locator('button').press('Enter');else if(mode.includes('touch'))await locator.tap();else await locator.click();};
 await activate(link);
 await page.waitForFunction(id=>{function walk(r){for(const n of r.querySelectorAll('*')){if(n.localName==='more-info-media_player'&&n.stateObj?.entity_id===id)return true;if(n.shadowRoot&&walk(n.shadowRoot))return true;}return false;}return walk(document);},leader);
 assert.equal(await more.evaluate(m=>m.stateObj.entity_id),leader);
 if(mode.includes('recovery')){
  const transient=structuredClone(states);delete transient[leader].attributes.loxone_group_control;
  publishNative(transient);
  await page.waitForFunction(id=>!document.querySelector('home-assistant').hass.states[id].attributes.loxone_group_control,leader);
  await page.waitForTimeout(100);
  publishNative(states);
  await page.waitForFunction(id=>!!document.querySelector('home-assistant').hass.states[id].attributes.loxone_group_control,leader);
  await page.waitForTimeout(100);
 }

 const before=await more.evaluate(m=>{const api=window[Symbol.for('pyloxone-audio.gm03.more-info')];return {entity:m.stateObj.entity_id,state:m.stateObj.state,binding:api?.binding?.id,bound:api?.binding?.instance===m,button:api?.binding?.button===m.shadowRoot.querySelector('#grouping-button')};});
 results.push({before});
 await activate(more.locator('#grouping-button'));
 await waitGrouping(page);
 const dialogs=await dialogState(page);
 results.push({dialogs});await page.screenshot({path:path.join(out,'first-group.png')});fs.writeFileSync(path.join(out,'journey.json'),JSON.stringify({before,dialogs},null,2));
 if(mode.includes('characterize')){
  await closeGrouping(page);await activate(more.locator('#grouping-button'));await waitGrouping(page);const second=await dialogState(page);results.push({second});fs.writeFileSync(path.join(out,'second-click.json'),JSON.stringify(second,null,2));assert.deepEqual(second.filter(d=>d.open).map(d=>d.tag),['loxone-group-manager-dialog'],'Closing stock causes re-observation; second click is custom');
 }
 assert.ok(dialogs.filter(d=>d.open).every(d=>d.visible),'Opened grouping dialog must really be visible/modal');
 assert.deepEqual(dialogs.filter(d=>d.open).map(d=>d.tag),['loxone-group-manager-dialog'],'FIRST leader Group after follower shortcut must open custom, not stock');
 assert.equal(dialogs.find(d=>d.open).entity,leader);assert.deepEqual(services,[]);
 results.push('Cold shortcut then FIRST Group opens exact custom leader, zero services');
}
