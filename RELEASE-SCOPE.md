# 0.1.1 release scope

The current release retires the optional HA-Spotify provider/session/binding
bridge; preserves native Spotify/account/control/Browse/manual seek and shared
fences; lists usable room-native previous content rather than folders; and adds
the corrections and controls described below. Line-In last and standard Source
UI remain. Volume lag is unresolved. See SPOTIFY.md for current ownership,
POSITION-RESTORE.md for limits and TEST-DISPOSITIONS.json for case provenance.
No Core/frontend patch or second integration is introduced. Upstream contact and
further household changes are not authorised by this release guide.
The library, adapter, Jo patch and complete preview must be used as one pinned
versioned release pair. Old 0.1.0 artifacts remain immutable.

Current 0.1.1 also includes native Shuffle/Repeat, exact per-item Spotify start,
same-track saved return/last-good protection and bounded seek readiness. All rooms
share the implementation with independent RAM-only bookmarks. Independent review,
common private HAOS adoption and one-room owner return confirmation are complete.
Public publication/installation is governed by PUBLISHING.md; upstream adoption,
universal queue/acoustic behaviour and restart persistence are not claimed.

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
