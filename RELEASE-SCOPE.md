# 0.1.2 release scope

This is a focused metadata-freshness/recovery correction on the current host,
not a new source-return, queue, persistence, grouping or provider feature. See
[release notes](RELEASE-NOTES-0.1.2.md), [freshness contract](METADATA-FRESHNESS.md)
and [known remaining issues](KNOWN-ISSUES.md). Both library and matching adapter
are required. Independent runtime engineering acceptance and local adoption are
complete, including independent release-preparation review. This publication successor
preserves runtime bytes; hosted/public-index production acceptance is a separate gate.

Inherited 0.1.1 features include native-only Spotify, room-native previous content,
native Shuffle/Repeat, exact-track/last-good protection, bounded optional seek and
default-off diagnostics. Keep one integration/setup/native entity set and the
existing Audio Server host/playback-ON prerequisite. Do not alter controls,
authentication, options, private deployment/capture or any accepted runtime bytes.
Historical 0.1.0 and 0.1.1 artifacts remain unchanged. No guide grants authority to
push, publish, contact maintainers or operate household devices.

## Historical 0.1.0 extraction record (superseded where noted above)

The new approved 0.1.1 increment additionally supplies default-off bounded rolling
audio diagnostics through the existing entry, not private capture tooling. Its
schema/switch/download, privacy and evidence limits are in DIAGNOSTICS.md. This
supersedes the historical blanket instrumentation exclusion only for that feature;
it does not diagnose past Spotify sends, repair position or authorise installation.

# Version 0.1.0 scope

Version0.1.0 freezes the owner-agreed native Audio Server feature set described
in API.md, together with its PyLoxone adapter and scoped tests. No second Home
Assistant integration, custom frontend/Core work or speculative provider feature
is introduced. Detailed development tracing and private rolling capture tooling
are excluded; ordinary useful warnings and error propagation remain.

The reference adapter targets released PyLoxone0.10.2, commit
`3db77b81f69c77cc814675d191061533b464df5e`, with the normal dependency
`PyLoxone-Audio==0.1.0`. The Python package contains only the portable library;
`adapters/pyloxone/` contains the versioned host delta, and `preview-build/`
contains the complete maintained integration preview and tester instructions.
Publishing this library does not merge its adapter upstream or automatically
update anyone's Home Assistant installation.

Initial independent offline acceptance used Python3.14 and a pinned HA test
baseline with synthetic network boundaries. Subsequent owner installation/use
is separate evidence, not a universal hardware, firmware or version matrix.
The0.1.0 publication adds clearer Spotify capability documentation, package
project links and a maintained publishing workflow without changing accepted
library/adapter runtime files or their public API.

Normal external installation requires the exact version to resolve from PyPI.
Check the actual PyPI version and matching GitHub release before installing;
a local wheel, source tree or archived offline-provenance readiness flag does
not establish public availability. Follow PUBLISHING.md for release verification
and preview-build/README.md for installation/update/rollback and native-UI tests.

Apache-2.0, NOTICE.md, upstream/Sebastian credit and honest human-directed/LLM
assistance provenance are retained. No release result authorises household
playback, credential disclosure or an upstream comment/PR on the owner's behalf.
