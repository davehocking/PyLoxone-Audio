// SPDX-License-Identifier: Apache-2.0
// Resource entrypoint: loads the More-info route even without a custom card.
import {afterNativeBootstrap} from './native-bootstrap.js';
import {initializeNativeGroupManager} from './native-group-manager.js';
import {overview} from './group-manager.js';
export {project} from './group-manager.js';

export let LoxoneGroupControlCard;
afterNativeBootstrap(()=>{
initializeNativeGroupManager();
if(customElements.get('loxone-group-control-card'))LoxoneGroupControlCard=customElements.get('loxone-group-control-card');
else{
LoxoneGroupControlCard=class LoxoneGroupControlCard extends HTMLElement {
  constructor(){
    super();this.attachShadow({mode:'open'});
    this.shadowRoot.innerHTML='<style>ha-card{padding:16px}ha-button{--ha-button-height:44px}ha-button[hidden]{display:none}.summary{margin:0 0 12px;padding:0;list-style:none;overflow-wrap:anywhere}.summary li+li{margin-top:8px}.actions{display:flex;flex-wrap:wrap;gap:12px}</style><ha-card><ul class="summary" aria-label="Confirmed audio groups"></ul><div class="actions"><ha-button data-action="open">Manage audio groups</ha-button><ha-button data-action="create">Create Group</ha-button></div></ha-card>';
    this.shadowRoot.querySelector('[data-action=open]').onclick=()=>this.open();
    this.shadowRoot.querySelector('[data-action=create]').onclick=()=>this.open('create');
  }
  // Older entity/presentation fields are accepted as presentation metadata only.
  // They never manufacture a group or a mandatory independent room.
  setConfig(config){if(!config||typeof config!=='object')throw new Error('Card configuration required');this._config={...config};}
  set hass(hass){
    this._hass=hass;
    const o=overview(hass),known=hass?.connected!==false&&!!hass?.user?.id&&o.views.size>0;
    const labels=o.groups.map(v=>hass.states[v.leader].attributes.friendly_name||v.leader);
    const summary=known?o.groups.map((v,i)=>`${labels[i]}${labels.filter(n=>n===labels[i]).length>1?' ('+v.leader+')':''} · ${v.members.length} rooms`):[];
    if(known&&o.incomplete)summary.push('Native grouping incomplete: some rooms are unavailable or unknown.');
    else if(!summary.length)summary.push(known?'No confirmed audio groups.':'Confirmed native grouping unavailable.');
    const signature=JSON.stringify(summary);
    if(this._summary!==signature){const list=this.shadowRoot.querySelector('.summary');list.replaceChildren(...summary.map(text=>{const li=document.createElement('li');li.textContent=text;return li;}));this._summary=signature;}
    const manage=this.shadowRoot.querySelector('[data-action=open]');manage.hidden=!known||(!o.groups.length&&!o.incomplete);manage.disabled=!known;
    this.shadowRoot.querySelector('[data-action=create]').disabled=!known;
  }
  get hass(){return this._hass;}
  getCardSize(){return 1;}
  static getStubConfig(){return {};}
  open(mode='overview'){
    if(!this.isConnected||this.hass?.connected===false||!this.hass?.user?.id)return;
    this.dispatchEvent(new CustomEvent('show-dialog',{bubbles:true,composed:true,detail:{dialogTag:'loxone-group-manager-dialog',dialogImport:()=>Promise.resolve(),dialogParams:{mode}}}));
  }
};
customElements.define('loxone-group-control-card',LoxoneGroupControlCard);
}
window.customCards=window.customCards||[];
if(!window.customCards.some(c=>c.type==='loxone-group-control-card'))window.customCards.push({type:'loxone-group-control-card',name:'Loxone audio groups',description:'Create and manage actual native groups; no fixed room required',preview:true});
});