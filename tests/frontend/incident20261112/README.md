# Compiled native Group compatibility checks

This is an OFFLINE synthetic-backend test. It never uses the household, HA credentials or an installed browser profile. The browser blocks every non-loopback request and fulfils all service messages in memory. Both stock and custom dialogs are observed using real native `:modal` visibility; a registered element or an entry card's `open()` method is not acceptance.

```
FRONTEND_NODE_MODULES=/path/to/existing/node_modules \
INCIDENT_CORE_VERSION=2026.11.1 \
node tests/frontend/incident20261112/browser.mjs \
  /fresh/owned/output /path/to/pinned/hass_frontend \
  /path/to/exact/bundle.js more-positive
```

The fixture is the existing invented `../r13/native-states.json`. Modes are `more-positive`, `card-positive`, `more-foreign`, `card-foreign`, `more-unauthenticated`, `card-unauthenticated` and `more-positive-gestures`. A fresh browser starts every case. The target is the confirmed group leader, explicitly published as playing. The first ordinary expanded More-info Group or compact media-card Group action must open the intended dialog. Unsupported versions and wrong registry/authentication retain the stock picker, without service writes.

The qualified compiled frontend distribution is `home-assistant-frontend==20261028.5`; tests under simulated older/newer Core version strings qualify the narrow version gate in that SAME compiled app, not historical versions' complete runtime compatibility. The gesture mode reuses the unchanged real mouse/CDP-touch drag oracle, with and without benign HA updates. It checks connected ranges, trusted input/change events, one release-only group service and the unchanged additive/clamp contract. This is Chromium mobile emulation, not physical iPhone/Safari acceptance. Exact emitted services can be replayed against the owning HA backend separately.
