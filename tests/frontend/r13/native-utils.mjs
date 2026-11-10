export async function dialogState(page){return page.evaluate(()=>{
 function modal(r){for(const n of r?.querySelectorAll('*')||[]){if(n.localName==='dialog'&&n.matches(':modal')&&n.getBoundingClientRect().width>0)return true;if(n.shadowRoot&&modal(n.shadowRoot))return true;}return false;}
 function walk(r){let a=[];for(const n of r.querySelectorAll('*')){if(['loxone-group-manager-dialog','dialog-join-media-players'].includes(n.localName))a.push({tag:n.localName,open:!!n._open||!!n.shadowRoot?.querySelector('ha-dialog')?.open,visible:modal(n.shadowRoot),entity:n._entity||null});if(n.shadowRoot)a.push(...walk(n.shadowRoot));}return a;}return walk(document);
 });}
export async function waitGrouping(page){await page.waitForFunction(()=>{
 function modal(r){for(const n of r?.querySelectorAll('*')||[]){if(n.localName==='dialog'&&n.matches(':modal')&&n.getBoundingClientRect().width>0)return true;if(n.shadowRoot&&modal(n.shadowRoot))return true;}return false;}
 function walk(r){for(const n of r.querySelectorAll('*')){if(['loxone-group-manager-dialog','dialog-join-media-players'].includes(n.localName)&&(n._open||n.shadowRoot?.querySelector('ha-dialog')?.open)&&modal(n.shadowRoot))return true;if(n.localName==='ha-alert'&&n.getAttribute('alert-type')==='error'&&n.getBoundingClientRect().width>0)return true;if(n.shadowRoot&&walk(n.shadowRoot))return true;}return false;}return walk(document);
 },null,{timeout:5000});}
export async function closeGrouping(page){for(const tag of ['loxone-group-manager-dialog','dialog-join-media-players'])await page.locator(tag).evaluateAll(ds=>{for(const d of ds)d.closeDialog?.();});await page.waitForFunction(()=>{
 function modal(r){for(const n of r?.querySelectorAll('*')||[]){if(n.localName==='dialog'&&n.matches(':modal'))return true;if(n.shadowRoot&&modal(n.shadowRoot))return true;}return false;}
 function walk(r){for(const n of r.querySelectorAll('*')){if(['loxone-group-manager-dialog','dialog-join-media-players'].includes(n.localName)&&modal(n.shadowRoot))return true;if(n.shadowRoot&&walk(n.shadowRoot))return true;}return false;}return !walk(document);
 },null,{timeout:5000});}
