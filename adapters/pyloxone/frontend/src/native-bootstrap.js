// SPDX-License-Identifier: Apache-2.0
// The pinned native app installs scoped registries AND replaces HTMLElement
// before defining/upgrading home-assistant. Never await its abandoned registry.
export function afterNativeBootstrap(initialize){
  let timer,deadline,stopped=false,disposed=false;
  const stop=()=>{stopped=true;clearTimeout(timer);};
  const dispose=()=>{disposed=true;stop();window.removeEventListener('pagehide',stop);window.removeEventListener('pageshow',start);};
  const probe=()=>{
    if(stopped||disposed)return;
    const Native=customElements.get('home-assistant'),root=document.querySelector('home-assistant');
    if(Native&&root instanceof Native&&root.isConnected&&root.shadowRoot){dispose();initialize();return;}
    if(performance.now()>=deadline){dispose();return;}
    // Bounded read-only positive readiness check, not a timing assumption or
    // permanent registry watcher. A missing/unsupported host stays native.
    timer=setTimeout(probe,25);
  };
  const start=()=>{if(disposed)return;stop();stopped=false;deadline=performance.now()+15000;probe();};
  window.addEventListener('pagehide',stop);window.addEventListener('pageshow',start);
  start();return dispose;
}
