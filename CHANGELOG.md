# Changelog

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
