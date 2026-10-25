# Versioned PyLoxone adapter: library 0.1.0 / host 0.10.2

This is a reviewed reference delta for the exact public JoDehli/PyLoxone release
0.10.2 commit `3db77b81f69c77cc814675d191061533b464df5e`, not unreleased master
and not an evergreen whole-file updater. Jo's later merged upstream files are
authoritative. Rebase/review the audio delta when the host changes; never copy
old full files over unrelated upstream fixes.

`BASE.json` records every exact upstream component file, 25 audio overlay files,
and the complete expected assembly. Only `const.py` and `manifest.json` overlap
the 0.10.1 -> 0.10.2 component changes: the assembly keeps `Platform.TEXT`, host
version 0.10.2 and all original requirements, adding `PyLoxone-Audio==0.1.0`.
The other 14 upstream-changed generic files are byte-identical to 0.10.2,
including its owning entrypoint, TextInput, WebSocket and entity fixes.

There remains ONE `loxone` integration/setup/native room entity set. Host options,
room/player mapping, services, callbacks and provider auth ownership stay in the
adapter; native transport, metadata/source policy and neutral catalogue models
belong to the portable library. Existing API tokens are supplied on demand by
the owning coordinator. HA's Spotify integration is **optional**, not an adapter
setup dependency. Native Loxone Spotify playback, metadata, controls and native
Browse/Search do not require it. An explicitly configured room binding can reuse
HA Spotify's existing OAuth session to read the user identity (`GET /v1/me`) and
current receiver (`GET /v1/me/player`), then resume through the native Loxone
`serviceplay/spotify` command. This live-session return does not seek to a saved
position; Spotify determines where its session resumes. The active selector does not write Spotify API
playback state, capture its queue, restore an exact position through Spotify, or
transfer another receiver's playback. No separate credential store is added.
Missing optional capability preserves a valid native path quietly; a positively
observed account/receiver conflict is not downgraded to optional absence.
See [the full capability/function map](../../SPOTIFY.md), including the explicit
binding fields and retained capture/restore helpers that are not called by the
current source selector. The optional listener
and command connections close with that entry; failures do not disable unrelated
Miniserver controls. Normal warning/error translation remains, development
tracing does not ship. See the call graph and API documents.

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
