# Changelog

## 0.1.1 — 2026-10-28

- Retire the optional HA-Spotify provider/session/binding bridge; preserve native
  Loxone Spotify, the independent HA Spotify integration and existing safety guards.
- Show usable exact-room previous content in HA’s standard Source selector,
  including qualified native/external playback. Folder visits alone do not qualify;
  configured Line-In inputs remain last. Previous-source/bookmark state is RAM-only.
- Add native Shuffle on/off and Repeat Off/All/One in standard More info controls
  when actual player permissions and firmware qualify. Display native feedback,
  including unknown/disconnected state, rather than optimistic requested modes.
- Match official individual Spotify track/episode starts with `/noshuffle` after
  validated parent/cursor. Require same-track feedback for saved exact-item returns;
  preserve last-good content on wrong-track feedback and overlapping Source actions.
  This is not a persistent shuffle/queue guarantee or proof of the historical cause.
- After confirmed same-track Spotify/Local Library return, allow at most two seconds
  for seek support, then at most one optional native saved-position attempt.
  Already-ready tracks do not wait. Timeout keeps confirmed playback; changed
  track/account/action, lifecycle and uncertainty guards remain. No per-room setup.
- Add a separate default-OFF Audio diagnostics switch, bounded local rolling 24-hour
  sanitised events and admin download. Preference durability/coverage/omissions and
  failure health are explicit. Toggling does not reload or change playback; no upload.
- Independent source/exact-wheel and owning-HA review precedes common HAOS adoption.
  On 28 October the owner accepted two same-track/near-saved-position returns from
  Local Library to Spotify in one room, with supporting native feedback. This does
  not establish all-room acoustic, whole-queue or restart persistence acceptance.
- Refresh complete preview, exact-base maintainer pack, installation/update/rollback
  and release guides; keep them separate from library wheel/sdist runtime.
- Enforce the standing production gate: upload tested wheel/sdist, verify actual
  public PyPI files/digests, and resolve fresh normal-index named-pin wheel AND
  sdist installations with dependencies, imports and exact runtime checks.
- Keep current Audio Server host/playback option label/default/gate unchanged.
  Diagnostics is separate. Intermittent audible volume lag remains unresolved.

Published 0.1.0 artifacts remain immutable. The notes below preserve that release’s
historical preparation, not the current 0.1.1 publication or adoption status.

## 0.1.0 — first release (2026-10-25)

Freeze the owner-agreed native audio/source feature set from the independently
accepted offline extraction. Preserve transport authentication/identity, fences,
clock isolation, cancellation/lifecycle, strict browser/manual seek, source return,
last-good history, native Spotify session handling and one optional best-effort
position restore. No added playback feature or architecture replacement.

Exclude development-only detailed diagnostic contexts, snapshots, collectors,
stage/operation instrumentation, HA trace decorators and last_source_failure
publication from the library and local host adapter. Retain ordinary useful fixed
warnings and error propagation/translation without exception/provider payloads.
The pre-release diagnostics API and diagnostic-only observation-operation label
are removed, not retained as compatibility stubs.

Set library metadata to PyLoxone-Audio 0.1.0 and prepare the existing integration's
local requirement PyLoxone-Audio==0.1.0. This does not change the integration's own
version/domain/name. Local wheel, sdist and host assets are not public releases.
Historical 0.0.0.dev0 receipts remain separately preserved and are not relabelled.
