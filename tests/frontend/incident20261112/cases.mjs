// New incident: real native FIRST Group click, playing leader, no household I/O.
import {dialogState,waitGrouping} from '../r13/native-utils.mjs';
export async function run(ctx) {
  const {page,assert,results,services,publishNative,snapshot,mode}=ctx;
  const states=structuredClone(snapshot.states);
  const entity=states[snapshot.target].attributes.group_members[0];
  states[entity].state='playing';
  await publishNative(states);
  const foreign=mode.includes('foreign');
  const unauthenticated=mode.includes('unauthenticated');
  if(unauthenticated) await page.evaluate(()=>{
    const root=document.querySelector('home-assistant');
    root.hass={...root.hass,user:{...root.hass.user,id:''}};
  });
  if(foreign) await page.evaluate(entity=>{
    const root=document.querySelector('home-assistant');
    root.hass={...root.hass,entities:{...root.hass.entities,[entity]:{...root.hass.entities[entity],platform:'synthetic_other'}}};
  },entity);
  const all=()=>{
    const found=[];
    const walk=root=>{for(const e of root.querySelectorAll('*')){found.push(e);if(e.shadowRoot)walk(e.shadowRoot);}};
    walk(document);return found;
  };
  await page.evaluate(({entity,card})=>{
    const root=document.querySelector('home-assistant');
    if(!card)root.dispatchEvent(new CustomEvent('hass-more-info',{detail:{entityId:entity},bubbles:true,composed:true}));
  },{entity,card:mode.startsWith('card')});
  const card=mode.startsWith('card');
  const selector=card?'hui-media-control-card':'more-info-media_player';
  await page.waitForFunction(({selector,card})=>{
    const walk=root=>{for(const e of root.querySelectorAll('*')){if(e.matches(selector)&&e.shadowRoot?.querySelector(card?'ha-icon-button.join-media':'#grouping-button'))return true;if(e.shadowRoot&&walk(e.shadowRoot))return true;}return false;};
    return walk(document);
  },{selector,card},{timeout:15000});
  const before=await page.evaluate(({selector,card,entity})=>{
    const found=[];const walk=root=>{for(const e of root.querySelectorAll('*')){found.push(e);if(e.shadowRoot)walk(e.shadowRoot);}};walk(document);
    const host=found.find(e=>e.matches(selector)&&(!card||e._config?.entity===entity));
    const button=host?.shadowRoot?.querySelector(card?'ha-icon-button.join-media':'#grouping-button');
    const r=button?.getBoundingClientRect();
    return {state:host?.stateObj?.state || host?.hass?.states?.[entity]?.state,entity:host?.stateObj?.entity_id || host?._config?.entity,button:button&&r?{x:r.x+r.width/2,y:r.y+r.height/2,w:r.width,h:r.height}:null};
  },{selector,card,entity});
  assert.equal(before.state,'playing');assert.equal(before.entity,entity);assert.ok(before.button?.w>0);
  await page.locator(selector).locator(card?'ha-icon-button.join-media':'#grouping-button').click();
  // Observe BOTH outcomes. Never wait only for the desired custom component.
  await waitGrouping(page);
  const dialogs=await dialogState(page);
  const after={custom:dialogs.filter(d=>d.tag==='loxone-group-manager-dialog'&&d.open&&d.visible).length,stock:dialogs.filter(d=>d.tag==='dialog-join-media-players'&&d.open&&d.visible).length};
  const supported=['2026.10.4','2026.11.0','2026.11.1'].includes(process.env.INCIDENT_CORE_VERSION||'2026.11.1');
  const expectedCustom=supported&&!foreign&&!unauthenticated;
  assert.equal(after.custom,expectedCustom?1:0,JSON.stringify({before,after,mode}));
  assert.equal(after.stock,expectedCustom?0:1,JSON.stringify({before,after,mode}));
  assert.equal(services.length,0);
  results.push({id:`first-playing-leader-${mode}-${process.env.INCIDENT_CORE_VERSION||'2026.11.1'}`,before,after,services:services.length});
  if(mode.includes('gestures')) {
    assert.ok(expectedCustom);
    // Existing trusted-gesture oracle uses its original 'one' fixture selector.
    // Adapt that selector only to this unchanged r13 fixture's group identity.
    const groupId=snapshot.states[snapshot.target].attributes.loxone_group_control.group_id;
    const manager={locator:selector=>page.locator('loxone-group-manager').locator(selector.replace('[data-group-id=one]',`[data-group-id=${JSON.stringify(groupId)}]`))};
    await (await import('../gm03-mobile-gesture.mjs')).run({...ctx,manager});
  }
}
