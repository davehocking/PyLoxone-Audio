// SPDX-License-Identifier: Apache-2.0
// Narrow pinned-native bindings: Loxone More-info and media-card Group buttons.
import {project,initializeGroupManager} from './group-manager.js';
const SINGLETON=Symbol.for('pyloxone-audio.gm03.more-info');
const validContext=(hass,instance,tag='more-info-media_player')=>{
  const id=tag==='hui-media-control-card'?instance?._config?.entity:instance?.stateObj?.entity_id,s=hass?.states?.[id],d=s?.attributes?.loxone_group_control;
  return ['2026.10.4','2026.11.0'].includes(hass?.config?.version)&&hass?.connected!==false&&!!hass?.user?.id
    &&instance?.isConnected&&instance.localName===tag
    &&project(hass,id)&&hass?.entities?.[id]?.platform==='loxone'&&d?.version===2&&Array.isArray(d.members)
    &&d.members.includes(id)&&Array.isArray(d.candidates)&&d.members.every(i=>{
      const other=hass.states[i]?.attributes?.loxone_group_control;
      return hass.entities?.[i]?.platform==='loxone'&&other?.version===2&&other.owner===d.owner&&other.revision===d.revision;
    })&&!['unknown','unavailable'].includes(s.state)?id:null;
};
function nativeTree(element,visit){
  visit(element);
  for(const child of element.children||[])nativeTree(child,visit);
  if(element.shadowRoot)nativeTree(element.shadowRoot,visit);
}
export function installNativeMoreInfo(){
  if(!customElements.get('home-assistant'))return;
  if(window[SINGLETON])return window[SINGLETON];
  let root,binding,observed,mediaLink,cardRoot,observers=[],scheduled=false,stopped=false,disposed=false;
  // Delegate only the pinned native card's exact Group button. No full-panel
  // DOM scanning, native method replacement or blanket dialog interception.
  const cardClick=event=>{
    if(stopped||!root?.isConnected)return;
    const path=event.composedPath(),card=path.find(n=>n?.localName==='hui-media-control-card');
    if(card?._config?.type!=='media-control')return;
    const id=validContext(root.hass,card,'hui-media-control-card');
    const buttons=card.shadowRoot?.querySelectorAll('ha-icon-button.join-media');
    const button=buttons?.length===1?buttons[0]:null;
    if(!id||!button||button.disabled||!path.includes(button))return;
    event.preventDefault();event.stopImmediatePropagation();
    card.dispatchEvent(new CustomEvent('show-dialog',{bubbles:true,composed:true,detail:{dialogTag:'loxone-group-manager-dialog',dialogImport:()=>Promise.resolve(),dialogParams:{entity:id,preselectEntity:id}}}));
  };
  const dropCards=()=>{cardRoot?.removeEventListener('click',cardClick,true);cardRoot=null;};
  const dropMedia=()=>{if(mediaLink){mediaLink.active=false;mediaLink.node.onclick=null;mediaLink.node.remove();mediaLink=null;}};
  const drop=()=>{dropMedia();if(binding)binding.instance.removeEventListener('click',binding.listener,true);binding=null;};
  // Observation is not action authority. Keep the current native host's Lit
  // lifecycle through temporary ineligibility: property-only recovery may
  // produce no DOM mutation, and must rebind BEFORE the next Group click.
  const observe=instance=>{
    if(observed?.instance===instance)return;
    observed?.instance.removeController?.(observed.controller);observed=null;
    if(instance){const controller={hostUpdated:schedule,hostDisconnected:schedule};observed={instance,controller};instance.addController?.(controller);}
  };
  const mediaContext=current=>{
    if(binding!==current||validContext(root?.hass,current.instance)!==current.id)return null;
    const h=root.hass,v=project(h,current.id),lead=v&&project(h,v.leader);
    if(!v||!v.group||v.members.length<2||v.leader===current.id||v.busy||!lead||lead.busy
      ||!(h.states[v.leader].attributes.supported_features&131072))return null;
    return {leader:v.leader,name:h.states[v.leader].attributes.friendly_name||v.leader,
      key:JSON.stringify([h.user,v.owner,v.revision,v.group,v.members,current.id])};
  };
  const updateMedia=current=>{
    const context=mediaContext(current);
    if(!context){dropMedia();return;}
    if(mediaLink?.key===context.key&&mediaLink.binding===current){
      const label=`Media controls on ${context.name}`;if(mediaLink.node.textContent!==label)mediaLink.node.textContent=label;return;
    }
    dropMedia();const node=document.createElement('ha-button');node.setAttribute('data-loxone-media-leader','');
    node.textContent=`Media controls on ${context.name}`;
    node.style.cssText='display:flex;max-width:100%;margin-block:12px;--ha-button-height:44px;white-space:normal';
    const link={node,key:context.key,binding:current,active:true};mediaLink=link;
    node.onclick=()=>{
      const now=mediaContext(current);
      if(!link.active||mediaLink!==link||!node.isConnected||!now||now.key!==link.key)return;
      current.instance.dispatchEvent(new CustomEvent('hass-more-info',{bubbles:true,composed:true,detail:{entityId:now.leader}}));
    };
    current.instance.shadowRoot.append(node);
  };
  const reconcile=()=>{
    scheduled=false;if(stopped)return;
    const next=document.querySelector('home-assistant');
    if(root!==next){drop();observe(null);root=next;}
    if(cardRoot!==root){dropCards();if(root?.isConnected){cardRoot=root;cardRoot.addEventListener('click',cardClick,true);}}
    for(const o of observers)o.disconnect();observers=[];
    if(!root?.isConnected||!root.shadowRoot){observe(null);return;}
    const watch=target=>{const o=new MutationObserver(schedule);o.observe(target,{childList:true,subtree:true,attributes:true,attributeFilter:['disabled','open','class']});observers.push(o);};
    watch(root.shadowRoot);
    const dialog=root.shadowRoot.querySelector('ha-more-info-dialog');let instance;
    if(dialog)nativeTree(dialog,el=>{if(el.shadowRoot)watch(el.shadowRoot);if(el.localName==='more-info-media_player')instance=el;});
    observe(instance);
    const id=validContext(root.hass,instance),buttons=instance?.shadowRoot?.querySelectorAll('ha-icon-button#grouping-button');
    const button=buttons?.length===1&&!buttons[0].disabled?buttons[0]:null;
    if(!id||!button){drop();return;}
    if(binding?.instance===instance&&binding.button===button&&binding.id===id){updateMedia(binding);return;}
    drop();const current={instance,button,id};
    current.listener=event=>{
      const activeId=validContext(root?.hass,instance);
      if(binding!==current||!activeId||!root?.isConnected
        ||instance.shadowRoot?.querySelectorAll('ha-icon-button#grouping-button').length!==1
        ||instance.shadowRoot.querySelector('#grouping-button')!==button||button.disabled||!event.composedPath().includes(button))return;
      event.preventDefault();event.stopImmediatePropagation();
      instance.dispatchEvent(new CustomEvent('show-dialog',{bubbles:true,composed:true,detail:{dialogTag:'loxone-group-manager-dialog',dialogImport:()=>Promise.resolve(),dialogParams:{entity:activeId,preselectEntity:activeId}}}));
    };
    binding=current;instance.addEventListener('click',current.listener,true);

    updateMedia(current);
  };
  const schedule=()=>{if(!scheduled&&!stopped){scheduled=true;queueMicrotask(reconcile);}};
  const start=()=>{if(!disposed){stopped=false;reconcile();}};
  const stop=()=>{stopped=true;drop();observe(null);dropCards();for(const o of observers)o.disconnect();observers=[];};
  const api={start,stop,dispose(){disposed=true;stop();window.removeEventListener('pagehide',stop);window.removeEventListener('pageshow',start);delete window[SINGLETON];},get binding(){return binding;}};window[SINGLETON]=api;
  start();
  window.addEventListener('pagehide',stop);window.addEventListener('pageshow',start);
  return api;
}

export let LoxoneGroupManagerDialog;
export function initializeNativeGroupManager(){
initializeGroupManager();
if(customElements.get('loxone-group-manager-dialog')){LoxoneGroupManagerDialog=customElements.get('loxone-group-manager-dialog');installNativeMoreInfo();return LoxoneGroupManagerDialog;}
LoxoneGroupManagerDialog=class LoxoneGroupManagerDialog extends HTMLElement {
  constructor(){
    super();this.attachShadow({mode:'open'});
    this.shadowRoot.innerHTML='<style>ha-button[data-action=close]{--ha-button-height:44px}</style><ha-dialog><loxone-group-manager></loxone-group-manager><ha-button slot="footer" data-action="close">Close</ha-button></ha-dialog>';
    this._dialog=this.shadowRoot.querySelector('ha-dialog');this._manager=this.shadowRoot.querySelector('loxone-group-manager');this._dialog.flexContent=true;
    // Native title owns the font/line-box and accessible label. A slotted h2's
    // default margins overflow the pinned header's fixed title slot.
    this._dialog.headerTitle='Audio groups';
    this.shadowRoot.querySelector('[data-action=close]').onclick=()=>this.closeDialog();
    // Native Escape/header/scrim dismissal changes ha-dialog's internal state,
    // not its public open input. Reconcile that input before HA caches/reuses us.
    this._dialog.addEventListener('closed',()=>{this._open=false;this._dialog.open=false;this._manager._epoch++;this._manager._cancelGesture();this.dispatchEvent(new CustomEvent('dialog-closed',{detail:{dialog:this.localName},bubbles:true,composed:true}));});
    // ha-dialog does not forward the HTML dialog's cancel event. Guard its
    // actual owning dismissal paths, without changing native global behaviour.
    this._dialog.addEventListener('keydown',e=>{if(this._manager._pending&&e.key==='Escape'){e.preventDefault();e.stopImmediatePropagation();}},true);
    this._dialog.addEventListener('wa-hide',e=>{if(this._manager._pending&&e.composedPath()[0]===this._dialog.shadowRoot?.querySelector('wa-dialog'))e.preventDefault();},true);
  }
  set hass(hass){this._hass=hass;this._dialog.hass=hass;if(this._open)this._manager.hass=hass;}
  get hass(){return this._hass;}
  showDialog(params={}){
    this._entity=params.entity;this._open=true;this._manager._cancelGesture();
    this._manager._mode=params.mode==='create'?'create':'overview';this._manager._adding=null;this._manager._selected.clear();
    this._manager._createOrigin=null;this._manager.hass=this.hass;
    if(typeof params.preselectEntity==='string'&&params.preselectEntity===params.entity)
      this._manager._createOrigin={entity:params.entity,auth:this._manager._auth()};
    if(params.mode==='create')this._manager._enterCreate();else this._manager.render();
    this._dialog.open=true;
  }
  closeDialog(){if(this._manager._pending)return false;this._open=false;this._dialog.open=false;this._manager._epoch++;this._manager._cancelGesture();return true;}
  disconnectedCallback(){this._manager._epoch++;this._manager._cancelGesture();this._manager._cancel?.(new Error('Dialog disconnected.'));this._open=false;this._dialog.open=false;}
};
customElements.define('loxone-group-manager-dialog',LoxoneGroupManagerDialog);
installNativeMoreInfo();
return LoxoneGroupManagerDialog;
}
