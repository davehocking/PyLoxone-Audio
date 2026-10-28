> **0.1.1 matching reference adapter.** Independent review and private common
> adoption are complete; public availability requires the release production gate.
> No upstream approval or automatic installation is implied. Start with the
> [tester guide](../../preview-build/README.md) or the
> [Jo inspect/reproduce/test/rebase/adopt/release guide](jo-review/README.md).
> The optional HA-Spotify bridge is removed; normal native Loxone Spotify remains.
> POSITION-RESTORE.md records bounded readiness and one-room owner confirmation.

# Versioned PyLoxone adapter: library 0.1.1 / host 0.10.2

This is a candidate reference delta awaiting independent review for the exact public JoDehli/PyLoxone release
0.10.2 commit `3db77b81f69c77cc814675d191061533b464df5e`, not unreleased master
and not an evergreen whole-file updater. Jo's later merged upstream files are
authoritative. Rebase/review the audio delta when the host changes; never copy
old full files over unrelated upstream fixes.

`BASE.json` records every exact upstream component file, the scoped audio overlay,
and the complete expected assembly. Only `const.py` and `manifest.json` overlap
the 0.10.1 -> 0.10.2 component changes: the assembly keeps `Platform.TEXT`, host
version 0.10.2 and all original requirements, adding `PyLoxone-Audio==0.1.1`.
The new diagnostics increment adds small owning-entrypoint/switch/download and
audio-only existing Miniserver send hooks, preserving the0.10.2 fixes. BASE.json
and Jo's file guide identify exact changed/unchanged bytes, not a whole-file copy
from an older release. TextInput and unrelated entity functionality remain.

There remains ONE `loxone` integration/setup/native room entity set. Host options,
room/player mapping, services, callbacks and provider auth ownership stay in the
adapter; native transport, metadata/source policy and neutral catalogue models
belong to the portable library. Existing API tokens are supplied on demand by
the owning coordinator. HA's separate Spotify integration is neither required
nor consulted. 0.1.1 removes its optional room-binding/session/OAuth/provider API
bridge. Legacy options are ignored without changing that independent entry.
Native Loxone Spotify playback, metadata, controls, Browse/Search, account checks,
qualified room-native return and supported manual seek remain. A source can be
retained from actual same-room native observations, not only HA play requests;
a label/title/folder/phone-only event is not a usable target. The standard Source
selector includes only usable previous content, with configured Line-In last.
There is no new history database or custom frontend. One optional native seek
remains conditional/nonblocking, with one-room owner confirmation rather than a
universal position guarantee. Bookmarks remain RAM-only across restart. See [the active function map](../../SPOTIFY.md) and
[bounded position findings](../../POSITION-RESTORE.md). The optional listener
and command connections close with that entry; failures do not disable unrelated
Miniserver controls. Normal warning/error translation remains, development
private tracing does not ship. New supported default-off structured diagnostics
is explicitly included: one entry switch, local24h age retention with fixed bounds,
no reload/control on toggle, and sanitised admin download replacing raw-house
diagnostics. See [workflow/privacy/limits](../../DIAGNOSTICS.md).

From the library repository root:

    /path/to/test-python tools/test_project.py library --work-dir /path/to/new-library-check
    /path/to/test-python tools/test_project.py adapter --host-base /path/to/exact-upstream-0.10.2 --work-dir /path/to/new-adapter-check

The runner validates hashes, assembles a new external host and runs real owning
HA paths with socket-blocked synthetic external I/O. Portable tests reject HA
imports. Source and exact-wheel runs record actual import paths. The project
owns library and audio adapter tests; generic host regressions remain separate
external compatibility evidence, not vendored library tests.

For users/testers, `../../preview-build/` contains the COMPLETE installable
integration ZIP, deterministic builder/verifier, guarded filesystem install/
update/rollback and dependency/native-UI/report instructions. Manual overlay
assembly or waiting for Jo's merge is not necessary. The library wheel AND sdist
exclude assembled preview material. The library repository archive retains it.
`jo-review/` contains the focused 0.10.2-based patch and per-file WHAT/WHY/tests.
Normal external use requires the exact library pin to be available on PyPI;
verify its project/version page and matching GitHub release before installation.
The preview's embedded provenance records original offline validation, not live
publication status. No upstream merge/adoption is implied by this reference.
