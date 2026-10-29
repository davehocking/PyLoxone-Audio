# Versioned PyLoxone adapter: library 0.1.2 / host 0.10.2

Versioned 0.1.2 reference pair. Independent engineering and release-preparation
review and local runtime installation are complete. Verify hosted/public-index
production acceptance separately. Start with the [tester guide](../../preview-build/README.md) or
[maintainer guide](jo-review/README.md); neither implies upstream adoption.

This reference targets exact public JoDehli/PyLoxone 0.10.2 commit
`3db77b81f69c77cc814675d191061533b464df5e`, not unreleased master and not an
evergreen whole-file updater. Before upstream adoption, preserve current host
changes and port the focused delta deliberately. Jo has not adopted the supplied
0.1.1 adapter merely because an incremental patch uses it as a baseline.


`BASE.json` records every exact upstream component file, the scoped audio overlay,
and the complete expected assembly. Only `const.py` and `manifest.json` overlap
the 0.10.1 -> 0.10.2 component changes: the assembly keeps `Platform.TEXT`, host
version 0.10.2 and all original requirements, adding `PyLoxone-Audio==0.1.2`.
Inherited diagnostics adds small owning-entrypoint/switch/download and
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

## Small increment versus complete adoption

`jo-review/audio-0.1.1-to-0.1.2.patch` changes only `media_player.py` (+12/-0)
and `manifest.json` (+1/-1 pin). It assumes the published 0.1.1 AUDIO adapter,
not stock PyLoxone. The added entity lines report independent PLAYING, clear
stale attributes and own bounded recovery registration/removal. Library
metadata/receiver changes remain in the separate 0.1.2 dependency.
`jo-review/audio-0.1.2-on-0.10.2.patch` is the cumulative patch for pinned stock
0.10.2. Both apply/assembly paths must reproduce BASE.json exactly.

Required: existing **Audioserver host** plus **Use Audio Server player play/pause
(experimental; off by default)** ON. Diagnostics is optional/default OFF for new
users and does not enable recovery. See main README and KNOWN-ISSUES.md; this
metadata fix does not guarantee every Spotify source/position return.
