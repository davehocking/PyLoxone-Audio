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
