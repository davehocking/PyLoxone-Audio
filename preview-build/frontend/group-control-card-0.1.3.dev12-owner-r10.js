// pyloxone-audio/leader-group-entry-20261107/frontend/src/native-bootstrap.js
function afterNativeBootstrap(initialize) {
  let timer, deadline, stopped = false, disposed = false;
  const stop = () => {
    stopped = true;
    clearTimeout(timer);
  };
  const dispose = () => {
    disposed = true;
    stop();
    window.removeEventListener("pagehide", stop);
    window.removeEventListener("pageshow", start);
  };
  const probe = () => {
    if (stopped || disposed) return;
    const Native = customElements.get("home-assistant"), root = document.querySelector("home-assistant");
    if (Native && root instanceof Native && root.isConnected && root.shadowRoot) {
      dispose();
      initialize();
      return;
    }
    if (performance.now() >= deadline) {
      dispose();
      return;
    }
    timer = setTimeout(probe, 25);
  };
  const start = () => {
    if (disposed) return;
    stop();
    stopped = false;
    deadline = performance.now() + 15e3;
    probe();
  };
  window.addEventListener("pagehide", stop);
  window.addEventListener("pageshow", start);
  start();
  return dispose;
}

// pyloxone-audio/leader-group-entry-20261107/frontend/src/group-manager.js
var FEATURES = { volume: 4, pause: 1, play: 16384, grouping: 524288 };
var ICONS = { play: "M8,5.14V19.14L19,12.14L8,5.14Z", pause: "M14,19H18V5H14M6,19H10V5H6V19Z", minus: "M19,13H5V11H19V13Z", plus: "M19,13H13V19H11V13H5V11H11V5H13V11H19V13Z" };
var same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
var ids = (a) => Array.isArray(a) && a.length > 0 && a.length <= 256 && new Set(a).size === a.length && a.every((i) => typeof i === "string" && /^media_player\.[a-z0-9_]+$/.test(i));
var available = (s) => s && !["unknown", "unavailable"].includes(s.state);
var name = (h, id) => h.states[id]?.attributes.friendly_name || id;
var groupLabel = (h, v) => `${name(h, v.leader)} +${v.members.length - 1}`;
var sort = (h, a, b) => name(h, a).toLocaleLowerCase("en").localeCompare(name(h, b).toLocaleLowerCase("en"), "en") || a.localeCompare(b);
function project(hass, target) {
  const s = hass?.states?.[target], d = s?.attributes?.loxone_group_control;
  if (!available(s) || d?.version !== 2 || typeof d.owner !== "string" || typeof d.revision !== "string" || !ids(d.members) || !ids(d.candidates) || !d.members.includes(target) || !same(d.members, s.attributes.group_members)) return null;
  const candidates = d.candidates.filter((id) => {
    const t = hass.states[id], v = t?.attributes.loxone_group_control;
    return available(t) && hass.entities?.[id]?.platform === "loxone" && v?.version === 2 && v.owner === d.owner && v.revision === d.revision && v.candidates?.includes(id) && !!(t.attributes.supported_features & FEATURES.grouping);
  });
  if (!d.members.every((id) => {
    const a = hass.states[id]?.attributes;
    return candidates.includes(id) && same(a?.group_members, d.members) && same(a?.loxone_group_control?.members, d.members) && a.loxone_group_control.group_id === d.group_id;
  })) return null;
  return { owner: d.owner, revision: d.revision, members: [...d.members], leader: d.members[0], group: d.group_id, busy: !!d.busy, candidates, top: [...d.members].sort((a, b) => sort(hass, a, b)), other: candidates.filter((id) => !d.members.includes(id)).sort((a, b) => sort(hass, a, b)) };
}
function overview(hass) {
  const views = new Map(Object.keys(hass?.states || {}).map((id) => [id, project(hass, id)]).filter(([, v]) => v));
  const groups = /* @__PURE__ */ new Map();
  for (const [id, v] of views) if (v.group && v.members.length > 1) groups.set(v.owner + "/" + v.group, { ...v, id: v.leader });
  const relevant = Object.keys(hass?.states || {}).filter((id) => {
    const a = hass.states[id]?.attributes;
    return hass.entities?.[id]?.platform === "loxone" && (a?.loxone_group_control || a?.supported_features & FEATURES.grouping || a?.group_members?.length > 1);
  });
  const incomplete = relevant.some((id) => !views.has(id));
  return { views, incomplete, groups: [...groups.values()].sort((a, b) => sort(hass, a.leader, b.leader)), free: [...views].filter(([, v]) => !v.group && v.members.length === 1).map(([id]) => id).sort((a, b) => sort(hass, a, b)) };
}
function percentOf(s, room = false) {
  const v = s?.attributes?.[room ? "loxone_room_volume_level" : "volume_level"];
  return typeof v === "number" && Number.isFinite(v) && v >= 0 && v <= 1 ? Math.round(v * 100) : null;
}
function percentLevel(p) {
  const v = p / 100;
  return Math.trunc(v * 100) < p ? v + Number.EPSILON : v;
}
var node = (tag, text, attrs = {}) => {
  const n = document.createElement(tag);
  if (text !== null) n.textContent = text;
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
};
var bind = (n, setup) => {
  n._bind = (target) => {
    const token = {};
    target._binding = token;
    if (["button", "ha-button", "ha-checkbox"].includes(target.localName)) {
      target.onpointerdown = () => {
        target._heldKey = null;
        target._press = token;
      };
      target.onkeydown = (e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        if (!e.repeat) target._heldKey = { key: e.key, token };
        target._press = target._heldKey?.key === e.key ? target._heldKey.token : {};
      };
      target.onkeyup = (e) => {
        if (target._heldKey?.key === e.key) target._heldKey = null;
      };
      target.onblur = target.onpointercancel = () => {
        target._heldKey = null;
        target._press = {};
      };
    }
    setup(target, (fn, refuse) => (...args) => {
      if (target._binding !== token) return;
      if (["click", "change"].includes(args[0]?.type)) {
        const press = target._press;
        target._press = null;
        if (press && press !== token) return refuse?.(...args);
      }
      return fn(...args);
    });
  };
  n._bind(n);
};
var renderKey = (n) => n.nodeType === 1 ? JSON.stringify([n.localName, n.getAttribute("data-render-key") ?? n.getAttribute("data-key") ?? [n.className, n.getAttribute("data-volume"), n.getAttribute("data-picker"), n.getAttribute("data-master")]]) : "#text";
function reconcile(parent, fresh, preserveRanges = true) {
  const old = [...parent.childNodes], used = /* @__PURE__ */ new Set();
  let cursor = parent.firstChild;
  for (const next of [...fresh.childNodes]) {
    const key = renderKey(next), current = old.find((n) => !used.has(n) && renderKey(n) === key && (preserveRanges || n.localName !== "input"));
    let target = next;
    if (current) {
      used.add(current);
      target = current;
      if (next.nodeType === 3) {
        if (current.data !== next.data) current.data = next.data;
      } else {
        for (const a of [...current.attributes]) if (!next.hasAttribute(a.name)) current.removeAttribute(a.name);
        for (const a of next.attributes) if (current.getAttribute(a.name) !== a.value) current.setAttribute(a.name, a.value);
        reconcile(current, next, preserveRanges);
        for (const p of ["disabled", "checked", "value", "path"]) if (p in next && current[p] !== next[p]) current[p] = next[p];
        current._bind = next._bind;
        current._bind?.(current);
      }
    }
    if (target !== cursor) parent.insertBefore(target, cursor);
    cursor = target.nextSibling;
  }
  for (const n of old) if (!used.has(n)) {
    n._binding = null;
    for (const child of n.querySelectorAll?.("*") || []) child._binding = null;
    n.remove();
  }
}
var icon = (path) => {
  const el = node("ha-svg-icon", null, { "aria-hidden": "true" });
  el.path = ICONS[path];
  return el;
};
var controlKey = (view, action, owner, group = null, entity = null, context = null) => JSON.stringify([view, action, owner, group, entity, context]);
var transport = (s) => s && ["playing", "paused", "idle", "off", "on", "standby"].includes(s.state) ? s.state === "playing" ? s.attributes.supported_features & FEATURES.pause ? "pause" : null : s.attributes.supported_features & FEATURES.play ? "play" : null : null;
var CSS = `:host{display:block;min-width:0;color:var(--primary-text-color);font-family:Roboto,Arial,sans-serif}section.group{border:1px solid var(--divider-color,#bbb);border-radius:12px;padding:12px;margin:12px 0}h3{font-size:1rem;margin:4px 0 12px}.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;min-height:56px;border-bottom:1px solid var(--divider-color,#ddd);padding:6px 0}.name{flex:1;min-width:90px;overflow-wrap:anywhere}.leader{display:block;font-size:.75rem;color:var(--secondary-text-color)}.vol{display:flex;align-items:center;gap:4px;flex:1;min-width:220px}.vol input{width:100%;min-width:44px;height:44px}.vol output{min-width:4ch;text-align:right}button{border:0;border-radius:50%;background:transparent;color:inherit;min-width:44px;min-height:44px;cursor:pointer;display:inline-flex;align-items:center;justify-content:center}button:disabled,input:disabled{opacity:.3;cursor:default}button:focus-visible,input:focus-visible{outline:3px solid var(--primary-color,#03a9f4)}ha-svg-icon{--mdc-icon-size:24px}.grouped{color:var(--disabled-text-color,#888)}.actions{display:flex;gap:8px;flex-wrap:wrap}.busy{position:sticky;bottom:0;background:var(--card-background-color,#fff);padding:16px;border-top:2px solid var(--primary-color,#03a9f4);font-weight:500;z-index:1}.busy:empty{display:none}[role=alert]{color:var(--error-color,#d33)}[aria-busy=true] .content{opacity:.25;pointer-events:none}ha-checkbox{min-width:44px;min-height:44px}@media(max-width:480px){.vol{flex-basis:100%}}`;
var MEMBER_LAYOUT = `ha-button{--ha-button-height:44px}.members{min-width:0;margin-inline-start:8px;padding:4px 8px;border-radius:8px;background:color-mix(in srgb,var(--primary-text-color) 5%,var(--card-background-color,#fff))}.members .row:last-child{border-bottom:0}[data-master]{border-bottom:0}.group-actions{display:flex;flex-wrap:wrap;gap:12px;padding-block:12px}.group-actions ha-button{max-width:100%;overflow-wrap:anywhere}`;
var LAYOUT = `:host{display:flex;flex:1;min-height:0}.manager-layout{display:flex;flex:1;flex-direction:column;min-height:0;min-width:0;overflow:hidden}.content{flex:1;min-height:0;overflow:auto;overscroll-behavior:contain}.actions{flex:none;padding:8px 0;border-bottom:1px solid var(--divider-color,#ddd)}[role=alert]:empty{display:none}.busy{flex:none}[aria-busy=true] .content{pointer-events:auto}`;
var LoxoneGroupManager;
function initializeGroupManager() {
  if (customElements.get("loxone-group-manager")) return LoxoneGroupManager = customElements.get("loxone-group-manager");
  LoxoneGroupManager = class LoxoneGroupManager extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._selected = /* @__PURE__ */ new Set();
      this._epoch = 0;
      this._error = "";
      this._mode = "overview";
      this.shadowRoot.addEventListener("pointerdown", (e) => {
        if (this._gesture && e.pointerId !== this._gesture.pointer) this._gesture.revoked = true;
      }, true);
    }
    connectedCallback() {
      this._epoch++;
      this.render();
    }
    disconnectedCallback() {
      this._epoch++;
      this._cancelGesture();
      this._cancel?.(new Error("Manager disconnected; no retry sent."));
    }
    set hass(h) {
      this._hass = h;
      try {
        this._ensure?.();
      } catch (e) {
        this._cancel?.(e);
      }
      this.render(true);
    }
    get hass() {
      return this._hass;
    }
    _auth() {
      return JSON.stringify([this.hass?.user, this.hass?.connected !== false]);
    }
    _stamp() {
      const o = overview(this.hass);
      return JSON.stringify([this._epoch, this._auth(), [...o.views], [...o.views.keys()].map((id) => {
        const s = this.hass.states[id];
        return [s.state, s.attributes.supported_features, s.attributes.loxone_room_volume_level, s.attributes.volume_level];
      })]);
    }
    _valid(stamp) {
      return this.isConnected && !this._pending && this.hass?.connected !== false && !!this.hass?.user?.id && stamp === this._stamp() && ![...overview(this.hass).views.values()].some((v) => v.busy);
    }
    // Display/metadata churn is benign. Native identity/eligibility and the actual
    // controlled volumes are not; retain those fences for the whole held gesture.
    _gestureStamp(id, room) {
      const o = overview(this.hass), v = o.views.get(id);
      return JSON.stringify([this._epoch, this._auth(), this.hass?.config?.version, this._mode, [...o.views].map(([i, p]) => [i, p.owner, p.revision, p.group, p.members, p.candidates, p.busy]), v?.members.map((i) => {
        const s = this.hass.states[i];
        return [i, s.state, s.attributes.supported_features, s.attributes.loxone_room_volume_level, room ? null : s.attributes.volume_level];
      })]);
    }
    _cancelGesture() {
      if (this._gesture) this._gesture.revoked = true;
      this._gesture = null;
    }
    _button(parent, label, action, key, work, stamp, disabled = false) {
      const b = node("ha-button", label, { "data-action": action, "aria-label": label, "data-key": key });
      b.disabled = disabled || !this._valid(stamp);
      bind(b, (b2, guard) => {
        b2.onclick = guard(() => {
          if (b2.isConnected && this._valid(stamp) && !b2.disabled) work();
        });
      });
      parent.append(b);
      return b;
    }
    _volume(parent, id, room, stamp) {
      const v = project(this.hass, id), key = (action) => controlKey(room ? "overview-member" : "overview-group", action, v.owner, v.group, room ? id : null);
      const s = this.hass.states[id], p = percentOf(s, room), wrap = node("div", null, { class: "vol", "data-volume": room ? "room" : "group" }), input = node("input", null, { type: "range", min: "0", max: "100", step: "1", "aria-label": `${name(this.hass, id)} ${room ? "room" : "group"} volume`, "data-key": key("volume") }), output = node("output", p === null ? "\u2014" : p + "%");
      input.value = p === null ? "0" : String(p);
      input.disabled = !this._valid(stamp) || p === null || !(s.attributes.supported_features & FEATURES.volume);
      for (const [action, delta, limit] of [["minus", -1, 0], ["plus", 1, 100]]) {
        const b = node("button", null, { "data-action": "volume-" + action, "data-key": key("volume-" + action), "aria-label": `${action === "plus" ? "Increase" : "Decrease"} ${name(this.hass, id)} ${room ? "room" : "group"} volume by 1 percentage point` });
        b.append(icon(action));
        b.disabled = input.disabled || p === limit;
        wrap.append(b);
        if (delta === -1) wrap.append(input);
      }
      wrap.append(output);
      parent.append(wrap);
      bind(wrap, (wrap2) => {
        const input2 = wrap2.querySelector("input"), output2 = wrap2.querySelector("output");
        const change = (value, current = false) => {
          if (input2.isConnected && this._valid(current ? this._stamp() : stamp) && Number.isInteger(value) && value >= 0 && value <= 100 && p !== null && value !== p) this._run(id, room ? "loxone" : "media_player", room ? "audio_room_volume" : "volume_set", room ? { volume_percent: value } : { volume_level: percentLevel(value) }, null, () => percentOf(this.hass.states[id], room) === (room ? value : this._expectedMean(id, value)));
          else this.render();
        };
        bind(input2, (input3, guard) => {
          let gesture;
          input3.onpointerdown = guard((e) => {
            if (this._gesture || e.isPrimary === false) {
              if (this._gesture) this._gesture.revoked = true;
              if (this._gesture?.input !== input3) gesture = { revoked: true, pointer: e.pointerId };
              return;
            }
            if (input3.disabled || !this._valid(stamp)) return;
            gesture = { input: input3, id, room, pointer: e.pointerId, stamp: this._gestureStamp(id, room) };
            this._gesture = gesture;
            input3.setPointerCapture(e.pointerId);
          });
          input3.onpointerup = guard((e) => {
            if (!gesture || e.pointerId !== gesture.pointer) return;
            const valid = this._gesture === gesture && !gesture.revoked && gesture.stamp === this._gestureStamp(id, room);
            this._cancelGesture();
            if (valid) change(Number(input3.value), true);
            else this.render();
          });
          const cancel = () => {
            if (this._gesture === gesture || !this._gesture && gesture?.revoked) {
              this._cancelGesture();
              this.render();
            }
          };
          input3.onpointercancel = guard(cancel);
          input3.onlostpointercapture = guard(cancel);
          input3.onblur = guard(cancel);
          input3.oninput = guard(() => {
            output2.textContent = input3.value + "%";
          });
          input3.onchange = guard(() => {
            if (!gesture) change(Number(input3.value));
          });
        });
        for (const [action, delta] of [["minus", -1], ["plus", 1]]) bind(wrap2.querySelector("[data-action=volume-" + action + "]"), (b, guard) => {
          b.onclick = guard(() => {
            if (!b.disabled) change(Math.max(0, Math.min(100, p + delta)));
          });
        });
      });
    }
    _enterCreate() {
      this._mode = "create";
      this._adding = null;
      this._selected.clear();
      const origin = this._createOrigin;
      if (origin?.auth === this._auth() && overview(this.hass).free.includes(origin.entity)) this._selected.add(origin.entity);
      this._selectionStamp = this._stamp();
      this.render();
    }
    _expectedMean(id, requested) {
      return this._volumeMean;
    }
    _play(parent, id, room, stamp) {
      const v = project(this.hass, id), action = transport(this.hass.states[id]), b = node("button", null, { "data-action": room ? "row-play" : "group-play", "data-key": controlKey(room ? "overview-member" : "overview-group", action, v.owner, v.group, room ? id : null), "aria-label": `${action === "pause" ? "Pause" : "Play"} ${name(this.hass, id)} ${room ? "only" : "group"}` });
      b.append(icon(action || "play"));
      b.disabled = !action || !this._valid(stamp);
      bind(b, (b2, guard) => {
        b2.onclick = guard(() => {
          if (b2.isConnected && !b2.disabled && this._valid(stamp)) this._run(id, room ? "loxone" : "media_player", room ? "audio_room_transport" : "media_" + action, room ? { action } : {}, null, null);
        });
      });
      parent.append(b);
    }
    _manage(id, action, members = []) {
      const v = project(this.hass, id);
      if (!v) return;
      const expected = Object.fromEntries(v.candidates.map((i) => [i, [...project(this.hass, i).members]]));
      if (action === "create") {
        const all = [id, ...members];
        for (const i of all) expected[i] = all;
      }
      if (action === "add") {
        const all = [...v.members, ...members];
        for (const i of all) expected[i] = all;
      }
      if (action === "remove") {
        const rest = v.members.filter((i) => i !== id);
        expected[id] = [id];
        for (const i of rest) expected[i] = rest.length > 1 ? rest : [i];
      }
      if (action === "destroy") for (const i of v.members) expected[i] = [i];
      const data = { action, revision: v.revision };
      if (v.group) data.group_id = v.group;
      if (members.length) data.members = members;
      this._run(id, "loxone", "audio_group_manage", data, expected, () => Object.entries(expected).every(([i, m]) => same(project(this.hass, i)?.members, m)));
    }
    async _run(id, domain, service, data, expected, confirmed) {
      if (this._pending || !project(this.hass, id)) return;
      const original = project(this.hass, id), epoch = this._epoch, auth = this._auth(), before = Object.fromEntries(original.candidates.map((i) => [i, project(this.hass, i).members]));
      if (service === "volume_set") {
        const wanted = Math.round(data.volume_level * 100), values = original.members.map((i) => percentOf(this.hass.states[i], true));
        if (values.some((v) => v === null)) return;
        const mean = Math.floor((2 * values.reduce((a, b) => a + b, 0) + values.length) / (2 * values.length));
        this._volumeMean = Math.floor((2 * values.reduce((a, b) => a + Math.max(0, Math.min(100, b + wanted - mean)), 0) + values.length) / (2 * values.length));
      }
      let valid = true, timer, cancel;
      const token = {};
      this._pending = token;
      this._error = "";
      this.render();
      const ensure = () => {
        const now = project(this.hass, id);
        valid = valid && this.isConnected && this._epoch === epoch && this._auth() === auth && this.hass?.connected !== false && now?.owner === original.owner && same(now?.candidates, original.candidates);
        if (valid) {
          const current = Object.fromEntries(original.candidates.map((i) => [i, project(this.hass, i)?.members]));
          valid = same(current, before) || expected && same(current, expected);
        }
        if (!valid) throw new Error("Native eligibility, membership, context or authentication changed. No retry or rollback sent.");
      };
      this._ensure = ensure;
      const guard = new Promise((_, reject) => {
        cancel = reject;
        this._cancel = reject;
        timer = setInterval(() => {
          try {
            ensure();
          } catch (e) {
            reject(e);
          }
        }, 40);
      });
      const deadline = Date.now() + 8e3;
      try {
        await Promise.race([guard, (async () => {
          ensure();
          await this.hass.callService(domain, service, data, { entity_id: id });
          ensure();
          while (confirmed && !confirmed()) {
            if (Date.now() > deadline) throw new Error("Native feedback not confirmed. No retry or rollback sent.");
            await new Promise((r) => setTimeout(r, 40));
            ensure();
          }
        })(), new Promise((_, reject) => {
          token.timeout = setTimeout(() => reject(new Error("Native operation timed out; partial changes are not undone.")), 8e3);
        })]);
        if (expected) {
          this._mode = "overview";
          this._selected.clear();
        }
      } catch (e) {
        this._error = e?.message || "Native operation failed.";
      } finally {
        valid = false;
        clearInterval(timer);
        clearTimeout(token.timeout);
        if (this._cancel === cancel) {
          this._cancel = null;
          this._ensure = null;
        }
        if (this._pending === token) this._pending = null;
        this.render();
      }
    }
    render(feedback = false) {
      if (this._createOrigin && this._createOrigin.auth !== this._auth()) this._createOrigin = null;
      if (!this.shadowRoot || !this.isConnected) return;
      if (this._gesture) {
        const g = this._gesture;
        if (g.input.isConnected && !g.revoked && this._valid(this._stamp()) && g.stamp === this._gestureStamp(g.id, g.room)) return;
        this._cancelGesture();
        g.input._binding = null;
        g.input.remove();
        this._presentation = null;
      }
      const h = this.hass, o = overview(h), stamp = this._stamp();
      const presentation = JSON.stringify([stamp, h?.config?.version, [...o.views.keys()].map((id) => name(h, id)), o.incomplete, this._mode, [...this._selected], this._adding?.owner, this._adding?.group, !!this._pending, this._error]);
      if (feedback && this._presentation === presentation) return;
      const active = this.shadowRoot.activeElement, key = active?.dataset.key, busy = !!this._pending || o.groups.some((v) => v.busy), existing = this.shadowRoot.querySelector(".manager-layout"), root = existing || node("div", null, { "tabindex": "-1", "data-focus-safe": "true", "role": "group", "aria-label": "Audio group manager" }), content = node("div", null, { class: "content" }), renderEpoch = this._renderEpoch = (this._renderEpoch || 0) + 1;
      if (this._mode === "create" && this._adding) {
        const current = o.groups.find((v) => v.owner === this._adding.owner && v.group === this._adding.group);
        if (current) this._adding = current;
        else {
          this._mode = "overview";
          this._adding = null;
          this._selected.clear();
        }
      }
      const owners = [...new Set([...o.views.values()].map((v) => v.owner))].sort(), context = this._adding ? [this._adding.owner, this._adding.group] : null;
      const globalKey = (action) => controlKey(this._mode, action, owners, null, null, context);
      if (this._selectionStamp !== stamp) {
        this._selected.clear();
        this._selectionStamp = stamp;
      }
      const buttons = node("div", null, { class: "actions", "aria-label": "Group creation and navigation" });
      if (this._mode !== "create") this._button(buttons, "Create Group", "create", globalKey("create"), () => this._enterCreate(), stamp);
      if (this._mode === "create") {
        content.append(node("h3", this._adding ? "Add free rooms" : "Create Group"));
        const list = node("div", null, { "data-picker": "free", "aria-label": "Available Loxone rooms" }), first = [...this._selected][0], owner = first ? o.views.get(first)?.owner : this._adding?.owner;
        for (const id of o.free) {
          const row = node("div", null, { class: "row", "data-entity": id, "data-render-key": controlKey("picker-free", "row", o.views.get(id).owner, null, id, context) }), check = node("ha-checkbox", null, { "aria-label": name(h, id), "data-key": controlKey("picker-free", "select", o.views.get(id).owner, null, id, context) }), label = node("span", name(h, id), { class: "name" });
          check.checked = this._selected.has(id);
          check.disabled = !this._valid(stamp) || !!(owner && o.views.get(id).owner !== owner);
          bind(check, (check2, guard) => {
            const reconcileChecked = () => {
              check2.checked = this._selected.has(id);
            };
            check2.onchange = guard(() => {
              if (!check2.isConnected || !this._valid(stamp) || check2.disabled) return reconcileChecked();
              if (this._adding) {
                this._manage(this._adding.leader, "add", [id]);
                return;
              }
              if (check2.checked) this._selected.add(id);
              else this._selected.delete(id);
              this.render();
            }, reconcileChecked);
          });
          row.append(check, label);
          list.append(row);
        }
        content.append(list);
        if (!this._adding) this._button(buttons, "Create", "confirm-create", controlKey("create", "confirm-create", owner ?? null, null, null, [...this._selected]), () => {
          const selected = [...this._selected];
          if (selected.length >= 2) this._manage(selected[0], "create", selected.slice(1));
        }, stamp, this._selected.size < 2);
        for (const v of o.groups) {
          const title = node("h3", "Already grouped \xB7 " + groupLabel(h, v), { "data-render-key": controlKey("picker-group", "title", v.owner, v.group) });
          content.append(title);
          for (const id of v.top) {
            const row = node("div", null, { class: "row grouped", "data-grouped-entity": id, "data-render-key": controlKey("picker-member", "row", v.owner, v.group, id, context) }), check = node("ha-checkbox", null, { "aria-label": name(h, id) + " already grouped" });
            check.checked = true;
            check.disabled = true;
            row.append(check, node("span", name(h, id), { class: "name" }));
            this._button(row, "Remove from group", "remove", controlKey("picker-member", "remove", v.owner, v.group, id, context), () => this._manage(id, "remove"), stamp);
            content.append(row);
          }
        }
        this._button(buttons, "Back", "back", globalKey("back"), () => {
          this._mode = "overview";
          this._selected.clear();
          this.render();
        }, stamp);
      } else for (const v of o.groups) {
        const section = node("section", null, { class: "group", "data-group-id": v.group, "data-render-key": controlKey("overview-group", "section", v.owner, v.group) }), title = node("h3", groupLabel(h, v));
        section.append(title);
        const master = node("div", null, { class: "row", "data-master": v.group });
        master.append(node("span", "Group volume", { class: "name" }));
        this._play(master, v.leader, false, stamp);
        this._volume(master, v.leader, false, stamp);
        section.append(master);
        const members = node("div", null, { class: "members", "data-members": v.group });
        for (const id of v.top) {
          const row = node("div", null, { class: "row", "data-entity": id, "data-render-key": controlKey("overview-member", "row", v.owner, v.group, id) }), label = node("span", name(h, id), { class: "name" });
          if (id === v.leader) label.append(node("span", "Leader", { class: "leader" }));
          row.append(label);
          this._play(row, id, true, stamp);
          this._volume(row, id, true, stamp);
          this._button(row, "Remove from group", "remove", controlKey("overview-member", "remove", v.owner, v.group, id), () => this._manage(id, "remove"), stamp);
          members.append(row);
        }
        section.append(members);
        const actions = node("div", null, { class: "group-actions", "aria-label": "Group actions" });
        this._button(actions, "Add rooms", "add", controlKey("overview-group", "add", v.owner, v.group), () => {
          this._mode = "create";
          this._adding = v;
          this._selected.clear();
          this._selectionStamp = this._stamp();
          this.render();
        }, stamp);
        this._button(actions, "Destroy Group", "destroy", controlKey("overview-group", "destroy", v.owner, v.group), () => this._manage(v.leader, "destroy"), stamp);
        section.append(actions);
        content.append(section);
      }
      if (!o.views.size) content.append(node("p", "Confirmed native grouping unavailable. Controls disabled."));
      else if (o.incomplete) content.append(node("p", "Native grouping incomplete: some rooms are unavailable or unknown."));
      root.className = "manager-layout";
      root.setAttribute("aria-busy", String(busy));
      const alert = node("p", this._error, { role: "alert", "aria-live": "assertive" }), status = node("div", busy ? "Updating audio\u2026 Please wait." : "", { class: "busy", role: "status", "aria-live": "polite" });
      if (existing) {
        const scroller = root.querySelector(".content"), top = scroller.scrollTop, left = scroller.scrollLeft;
        reconcile(scroller, content, feedback);
        for (const [selector, fresh] of [[".actions", buttons], ["[role=alert]", alert], [".busy", status]]) reconcile(root.querySelector(selector), fresh);
        scroller.scrollTop = top;
        scroller.scrollLeft = left;
      } else {
        root.append(buttons, content, alert, status);
        this.shadowRoot.replaceChildren(node("style", CSS + LAYOUT + MEMBER_LAYOUT), root);
      }
      this._presentation = presentation;
      if (active) {
        root.focus({ preventScroll: true });
        const matches = () => [...this.shadowRoot.querySelectorAll("[data-key]")].filter((n) => n.dataset.key === key), targets = key ? matches() : [], restore = targets.length === 1 ? targets[0] : null;
        Promise.resolve(restore?.updateComplete).then(() => {
          if (!this.isConnected || this._renderEpoch !== renderEpoch || !root.isConnected || this.shadowRoot.activeElement !== root) return;
          const current = key ? matches() : [];
          if (restore && current.length === 1 && current[0] === restore && restore.isConnected && !restore.disabled && this._valid(stamp)) restore.focus({ preventScroll: true });
        });
      }
    }
  };
  customElements.define("loxone-group-manager", LoxoneGroupManager);
  return LoxoneGroupManager;
}

// pyloxone-audio/leader-group-entry-20261107/frontend/src/native-group-manager.js
var SINGLETON = Symbol.for("pyloxone-audio.gm03.more-info");
var validContext = (hass, instance, tag = "more-info-media_player") => {
  const id = tag === "hui-media-control-card" ? instance?._config?.entity : instance?.stateObj?.entity_id, s = hass?.states?.[id], d = s?.attributes?.loxone_group_control;
  return ["2026.10.4", "2026.11.0"].includes(hass?.config?.version) && hass?.connected !== false && !!hass?.user?.id && instance?.isConnected && instance.localName === tag && project(hass, id) && hass?.entities?.[id]?.platform === "loxone" && d?.version === 2 && Array.isArray(d.members) && d.members.includes(id) && Array.isArray(d.candidates) && d.members.every((i) => {
    const other = hass.states[i]?.attributes?.loxone_group_control;
    return hass.entities?.[i]?.platform === "loxone" && other?.version === 2 && other.owner === d.owner && other.revision === d.revision;
  }) && !["unknown", "unavailable"].includes(s.state) ? id : null;
};
function nativeTree(element, visit) {
  visit(element);
  for (const child of element.children || []) nativeTree(child, visit);
  if (element.shadowRoot) nativeTree(element.shadowRoot, visit);
}
function installNativeMoreInfo() {
  if (!customElements.get("home-assistant")) return;
  if (window[SINGLETON]) return window[SINGLETON];
  let root, binding, mediaLink, cardRoot, observers = [], scheduled = false, stopped = false, disposed = false;
  const cardClick = (event) => {
    if (stopped || !root?.isConnected) return;
    const path = event.composedPath(), card = path.find((n) => n?.localName === "hui-media-control-card");
    if (card?._config?.type !== "media-control") return;
    const id = validContext(root.hass, card, "hui-media-control-card");
    const buttons = card.shadowRoot?.querySelectorAll("ha-icon-button.join-media");
    const button = buttons?.length === 1 ? buttons[0] : null;
    if (!id || !button || button.disabled || !path.includes(button)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    card.dispatchEvent(new CustomEvent("show-dialog", { bubbles: true, composed: true, detail: { dialogTag: "loxone-group-manager-dialog", dialogImport: () => Promise.resolve(), dialogParams: { entity: id, preselectEntity: id } } }));
  };
  const dropCards = () => {
    cardRoot?.removeEventListener("click", cardClick, true);
    cardRoot = null;
  };
  const dropMedia = () => {
    if (mediaLink) {
      mediaLink.active = false;
      mediaLink.node.onclick = null;
      mediaLink.node.remove();
      mediaLink = null;
    }
  };
  const drop = () => {
    dropMedia();
    if (binding) {
      binding.instance.removeEventListener("click", binding.listener, true);
      binding.instance.removeController?.(binding.controller);
    }
    binding = null;
  };
  const mediaContext = (current) => {
    if (binding !== current || validContext(root?.hass, current.instance) !== current.id) return null;
    const h = root.hass, v = project(h, current.id), lead = v && project(h, v.leader);
    if (!v || !v.group || v.members.length < 2 || v.leader === current.id || v.busy || !lead || lead.busy || !(h.states[v.leader].attributes.supported_features & 131072)) return null;
    return {
      leader: v.leader,
      name: h.states[v.leader].attributes.friendly_name || v.leader,
      key: JSON.stringify([h.user, v.owner, v.revision, v.group, v.members, current.id])
    };
  };
  const updateMedia = (current) => {
    const context = mediaContext(current);
    if (!context) {
      dropMedia();
      return;
    }
    if (mediaLink?.key === context.key && mediaLink.binding === current) {
      const label = `Media controls on ${context.name}`;
      if (mediaLink.node.textContent !== label) mediaLink.node.textContent = label;
      return;
    }
    dropMedia();
    const node2 = document.createElement("ha-button");
    node2.setAttribute("data-loxone-media-leader", "");
    node2.textContent = `Media controls on ${context.name}`;
    node2.style.cssText = "display:flex;max-width:100%;margin-block:12px;--ha-button-height:44px;white-space:normal";
    const link = { node: node2, key: context.key, binding: current, active: true };
    mediaLink = link;
    node2.onclick = () => {
      const now = mediaContext(current);
      if (!link.active || mediaLink !== link || !node2.isConnected || !now || now.key !== link.key) return;
      current.instance.dispatchEvent(new CustomEvent("hass-more-info", { bubbles: true, composed: true, detail: { entityId: now.leader } }));
    };
    current.instance.shadowRoot.append(node2);
  };
  const reconcile2 = () => {
    scheduled = false;
    if (stopped) return;
    const next = document.querySelector("home-assistant");
    if (root !== next) {
      drop();
      root = next;
    }
    if (cardRoot !== root) {
      dropCards();
      if (root?.isConnected) {
        cardRoot = root;
        cardRoot.addEventListener("click", cardClick, true);
      }
    }
    for (const o of observers) o.disconnect();
    observers = [];
    if (!root?.isConnected || !root.shadowRoot) return;
    const watch = (target) => {
      const o = new MutationObserver(schedule);
      o.observe(target, { childList: true, subtree: true, attributes: true, attributeFilter: ["disabled", "open", "class"] });
      observers.push(o);
    };
    watch(root.shadowRoot);
    const dialog = root.shadowRoot.querySelector("ha-more-info-dialog");
    let instance;
    if (dialog) nativeTree(dialog, (el) => {
      if (el.shadowRoot) watch(el.shadowRoot);
      if (el.localName === "more-info-media_player") instance = el;
    });
    const id = validContext(root.hass, instance), buttons = instance?.shadowRoot?.querySelectorAll("ha-icon-button#grouping-button");
    const button = buttons?.length === 1 && !buttons[0].disabled ? buttons[0] : null;
    if (!id || !button) {
      drop();
      return;
    }
    if (binding?.instance === instance && binding.button === button && binding.id === id) {
      updateMedia(binding);
      return;
    }
    drop();
    const current = { instance, button, id };
    current.listener = (event) => {
      const activeId = validContext(root?.hass, instance);
      if (binding !== current || !activeId || !root?.isConnected || instance.shadowRoot?.querySelectorAll("ha-icon-button#grouping-button").length !== 1 || instance.shadowRoot.querySelector("#grouping-button") !== button || button.disabled || !event.composedPath().includes(button)) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      instance.dispatchEvent(new CustomEvent("show-dialog", { bubbles: true, composed: true, detail: { dialogTag: "loxone-group-manager-dialog", dialogImport: () => Promise.resolve(), dialogParams: { entity: activeId, preselectEntity: activeId } } }));
    };
    binding = current;
    instance.addEventListener("click", current.listener, true);
    current.controller = { hostUpdated: schedule, hostDisconnected: schedule };
    instance.addController?.(current.controller);
    updateMedia(current);
  };
  const schedule = () => {
    if (!scheduled && !stopped) {
      scheduled = true;
      queueMicrotask(reconcile2);
    }
  };
  const start = () => {
    if (!disposed) {
      stopped = false;
      reconcile2();
    }
  };
  const stop = () => {
    stopped = true;
    drop();
    dropCards();
    for (const o of observers) o.disconnect();
    observers = [];
  };
  const api = { start, stop, dispose() {
    disposed = true;
    stop();
    window.removeEventListener("pagehide", stop);
    window.removeEventListener("pageshow", start);
    delete window[SINGLETON];
  }, get binding() {
    return binding;
  } };
  window[SINGLETON] = api;
  start();
  window.addEventListener("pagehide", stop);
  window.addEventListener("pageshow", start);
  return api;
}
var LoxoneGroupManagerDialog;
function initializeNativeGroupManager() {
  initializeGroupManager();
  if (customElements.get("loxone-group-manager-dialog")) {
    LoxoneGroupManagerDialog = customElements.get("loxone-group-manager-dialog");
    installNativeMoreInfo();
    return LoxoneGroupManagerDialog;
  }
  LoxoneGroupManagerDialog = class LoxoneGroupManagerDialog extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this.shadowRoot.innerHTML = '<style>ha-button[data-action=close]{--ha-button-height:44px}</style><ha-dialog><loxone-group-manager></loxone-group-manager><ha-button slot="footer" data-action="close">Close</ha-button></ha-dialog>';
      this._dialog = this.shadowRoot.querySelector("ha-dialog");
      this._manager = this.shadowRoot.querySelector("loxone-group-manager");
      this._dialog.flexContent = true;
      this._dialog.headerTitle = "Audio groups";
      this.shadowRoot.querySelector("[data-action=close]").onclick = () => this.closeDialog();
      this._dialog.addEventListener("closed", () => {
        this._open = false;
        this._dialog.open = false;
        this._manager._epoch++;
        this._manager._cancelGesture();
        this.dispatchEvent(new CustomEvent("dialog-closed", { detail: { dialog: this.localName }, bubbles: true, composed: true }));
      });
      this._dialog.addEventListener("keydown", (e) => {
        if (this._manager._pending && e.key === "Escape") {
          e.preventDefault();
          e.stopImmediatePropagation();
        }
      }, true);
      this._dialog.addEventListener("wa-hide", (e) => {
        if (this._manager._pending && e.composedPath()[0] === this._dialog.shadowRoot?.querySelector("wa-dialog")) e.preventDefault();
      }, true);
    }
    set hass(hass) {
      this._hass = hass;
      this._dialog.hass = hass;
      if (this._open) this._manager.hass = hass;
    }
    get hass() {
      return this._hass;
    }
    showDialog(params = {}) {
      this._entity = params.entity;
      this._open = true;
      this._manager._cancelGesture();
      this._manager._mode = params.mode === "create" ? "create" : "overview";
      this._manager._adding = null;
      this._manager._selected.clear();
      this._manager._createOrigin = null;
      this._manager.hass = this.hass;
      if (typeof params.preselectEntity === "string" && params.preselectEntity === params.entity)
        this._manager._createOrigin = { entity: params.entity, auth: this._manager._auth() };
      if (params.mode === "create") this._manager._enterCreate();
      else this._manager.render();
      this._dialog.open = true;
    }
    closeDialog() {
      if (this._manager._pending) return false;
      this._open = false;
      this._dialog.open = false;
      this._manager._epoch++;
      this._manager._cancelGesture();
      return true;
    }
    disconnectedCallback() {
      this._manager._epoch++;
      this._manager._cancelGesture();
      this._manager._cancel?.(new Error("Dialog disconnected."));
      this._open = false;
      this._dialog.open = false;
    }
  };
  customElements.define("loxone-group-manager-dialog", LoxoneGroupManagerDialog);
  installNativeMoreInfo();
  return LoxoneGroupManagerDialog;
}

// pyloxone-audio/leader-group-entry-20261107/frontend/src/group-control-card.js
var LoxoneGroupControlCard;
afterNativeBootstrap(() => {
  initializeNativeGroupManager();
  if (customElements.get("loxone-group-control-card")) LoxoneGroupControlCard = customElements.get("loxone-group-control-card");
  else {
    LoxoneGroupControlCard = class LoxoneGroupControlCard extends HTMLElement {
      constructor() {
        super();
        this.attachShadow({ mode: "open" });
        this.shadowRoot.innerHTML = '<style>ha-card{padding:16px}ha-button{--ha-button-height:44px}ha-button[hidden]{display:none}.summary{margin:0 0 12px;padding:0;list-style:none;overflow-wrap:anywhere}.summary li+li{margin-top:8px}.actions{display:flex;flex-wrap:wrap;gap:12px}</style><ha-card><ul class="summary" aria-label="Confirmed audio groups"></ul><div class="actions"><ha-button data-action="open">Manage audio groups</ha-button><ha-button data-action="create">Create Group</ha-button></div></ha-card>';
        this.shadowRoot.querySelector("[data-action=open]").onclick = () => this.open();
        this.shadowRoot.querySelector("[data-action=create]").onclick = () => this.open("create");
      }
      // Older entity/presentation fields are accepted as presentation metadata only.
      // They never manufacture a group or a mandatory independent room.
      setConfig(config) {
        if (!config || typeof config !== "object") throw new Error("Card configuration required");
        this._config = { ...config };
      }
      set hass(hass) {
        this._hass = hass;
        const o = overview(hass), known = hass?.connected !== false && !!hass?.user?.id && o.views.size > 0;
        const labels = o.groups.map((v) => hass.states[v.leader].attributes.friendly_name || v.leader);
        const summary = known ? o.groups.map((v, i) => `${labels[i]}${labels.filter((n) => n === labels[i]).length > 1 ? " (" + v.leader + ")" : ""} \xB7 ${v.members.length} rooms`) : [];
        if (known && o.incomplete) summary.push("Native grouping incomplete: some rooms are unavailable or unknown.");
        else if (!summary.length) summary.push(known ? "No confirmed audio groups." : "Confirmed native grouping unavailable.");
        const signature = JSON.stringify(summary);
        if (this._summary !== signature) {
          const list = this.shadowRoot.querySelector(".summary");
          list.replaceChildren(...summary.map((text) => {
            const li = document.createElement("li");
            li.textContent = text;
            return li;
          }));
          this._summary = signature;
        }
        const manage = this.shadowRoot.querySelector("[data-action=open]");
        manage.hidden = !known || !o.groups.length && !o.incomplete;
        manage.disabled = !known;
        this.shadowRoot.querySelector("[data-action=create]").disabled = !known;
      }
      get hass() {
        return this._hass;
      }
      getCardSize() {
        return 1;
      }
      static getStubConfig() {
        return {};
      }
      open(mode = "overview") {
        if (!this.isConnected || this.hass?.connected === false || !this.hass?.user?.id) return;
        this.dispatchEvent(new CustomEvent("show-dialog", { bubbles: true, composed: true, detail: { dialogTag: "loxone-group-manager-dialog", dialogImport: () => Promise.resolve(), dialogParams: { mode } } }));
      }
    };
    customElements.define("loxone-group-control-card", LoxoneGroupControlCard);
  }
  window.customCards = window.customCards || [];
  if (!window.customCards.some((c) => c.type === "loxone-group-control-card")) window.customCards.push({ type: "loxone-group-control-card", name: "Loxone audio groups", description: "Create and manage actual native groups; no fixed room required", preview: true });
});
export {
  LoxoneGroupControlCard,
  project
};
