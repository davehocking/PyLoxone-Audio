import {waitGrouping} from '../r13/native-utils.mjs';
export async function run(ctx){
 const {page,snapshot}=ctx,leader=snapshot.states[snapshot.target].attributes.group_members[0];
 await page.evaluate(id=>document.querySelector('home-assistant').dispatchEvent(new CustomEvent('hass-more-info',{detail:{entityId:id},bubbles:true,composed:true})),leader);
 await page.locator('more-info-media_player').locator('#grouping-button').click();await waitGrouping(page);
 await (await import('./multicontact-v3.mjs')).run({...ctx,manager:page.locator('loxone-group-manager'),dialog:page.locator('loxone-group-manager-dialog')});
}
