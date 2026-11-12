// SPDX-License-Identifier: Apache-2.0
// Owned IDLE follower widgets only. Native active-state controls remain untouched.
import {project} from './group-manager.js';
const SHUFFLE=32768,REPEAT=262144;
// Same SVG paths and repeat cycle as pinned HA frontend module34769.
const ICONS={
 shuffleOn:'M14.83,13.41L13.42,14.82L16.55,17.95L14.5,20H20V14.5L17.96,16.54L14.83,13.41M14.5,4L16.54,6.04L4,18.59L5.41,20L17.96,7.46L20,9.5V4M10.59,9.17L5.41,4L4,5.41L9.17,10.58L10.59,9.17Z',
 shuffleOff:'M16,4.5V7H5V9H16V11.5L19.5,8M16,12.5V15H5V17H16V19.5L19.5,16',
 all:'M17,17H7V14L3,18L7,22V19H19V13H17M7,7H17V10L21,6L17,2V5H5V11H7V7Z',
 one:'M13,15V9H12L10,10V11H11.5V15M17,17H7V14L3,18L7,22V19H19V13H17M7,7H17V10L21,6L17,2V5H5V11H7V7Z',
 off:'M2,5.27L3.28,4L20,20.72L18.73,22L15.73,19H7V22L3,18L7,14V17H13.73L7,10.27V11H5V8.27L2,5.27M17,13H19V17.18L17,15.18V13M17,5V2L21,6L17,10V7H8.82L6.82,5H17Z'
};
export function followerModeControls(getHass,valid){
 let owned;
 const drop=()=>{if(!owned)return;owned.active=false;for(const n of owned.buttons){n.onclick=n.onpointerdown=n.onkeydown=n.onkeyup=n.onblur=n.onpointercancel=null;}owned.node.remove();owned=null;};
 const context=current=>{
  const h=getHass(),id=valid(current),s=h?.states?.[id],v=id&&project(h,id),lead=v&&project(h,v.leader),a=s?.attributes,l=h?.states?.[v?.leader]?.attributes;
  if(!v||!v.group||v.members.length<2||v.leader===id||v.busy||!lead||lead.busy||s.state!=='idle'||a.assumed_state===true)return null;
  const modes=[];
  if((a.supported_features&SHUFFLE)&&(l.supported_features&SHUFFLE)&&typeof a.shuffle==='boolean'&&a.shuffle===l.shuffle)modes.push('shuffle');
  if((a.supported_features&REPEAT)&&(l.supported_features&REPEAT)&&['off','all','one'].includes(a.repeat)&&a.repeat===l.repeat)modes.push('repeat');
  if(!modes.length)return null;
  return {h,id,a,modes,key:JSON.stringify([h.user,h.connected!==false,h.config.version,v.owner,v.revision,v.group,v.members,v.candidates,id,v.leader,a.supported_features,l.supported_features,a.shuffle,a.repeat,l.shuffle,l.repeat,modes])};
 };
 const update=current=>{
  const c=context(current);
  if(!c){drop();return;}
  if(owned?.key===c.key&&owned.current===current)return;
  drop();const node=document.createElement('div');node.setAttribute('data-loxone-follower-modes','');node.style.cssText='display:flex;gap:16px;align-items:center;margin-block:12px;min-height:44px';
  const state={node,key:c.key,current,active:true,buttons:[],pending:false};owned=state;
  const error=document.createElement('span');error.setAttribute('role','alert');
  for(const mode of c.modes){
   // Never replace or duplicate a native rendered control.
   if(current.instance.shadowRoot.querySelector(`[action=${mode}_set]`))continue;
   const b=document.createElement('ha-icon-button');b.setAttribute('data-loxone-mode',mode);b.setAttribute('action',mode+'_set');
   const translated=c.h.localize?.('ui.card.media_player.'+mode+'_set');
   b.label=translated|| (mode==='shuffle'?'Shuffle':'Repeat');b.setAttribute('aria-label',b.label);
   b.setAttribute('aria-pressed',String(mode==='shuffle'?c.a.shuffle:c.a.repeat!=='off'));
   b.path=mode==='shuffle'?ICONS[c.a.shuffle?'shuffleOn':'shuffleOff']:ICONS[c.a.repeat];b.title=mode==='shuffle'?`${b.label}: ${c.a.shuffle?'on':'off'}`:`${b.label}: ${c.a.repeat}`;
   b.style.cssText='--mdc-icon-button-size:48px';let held=null;
   b.onpointerdown=()=>{held={fired:false};};
   b.onkeydown=e=>{if((e.key===' '||e.key==='Enter')&&!e.repeat)held={fired:false};};
   b.onkeyup=e=>{if(e.key===' '||e.key==='Enter')queueMicrotask(()=>{held=null;});};
   b.onblur=b.onpointercancel=()=>{held={fired:true};};
   b.onclick=async()=>{
    const now=context(current);
    if(!state.active||owned!==state||!b.isConnected||state.pending||!now||now.key!==state.key||held?.fired)return;
    if(held)held.fired=true;
    state.pending=true;state.buttons.forEach(n=>{n.disabled=true;});error.textContent='';
    const value=mode==='shuffle'?!now.a.shuffle:now.a.repeat==='off'?'all':now.a.repeat==='all'?'one':'off';
    try{await now.h.callService('media_player',mode+'_set',{entity_id:now.id,[mode]:value});}
    catch(e){if(state.active)error.textContent=e?.message||'Mode change failed; no retry sent.';}
    finally{if(state.active&&owned===state){state.pending=false;state.buttons.forEach(n=>{n.disabled=false;});}}
   };
   state.buttons.push(b);node.append(b);
  }
  node.append(error);current.instance.shadowRoot.append(node);
 };
 return {update,drop};
}
