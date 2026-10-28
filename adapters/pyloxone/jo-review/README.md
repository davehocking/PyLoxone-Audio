# Jo: review, adopt and release the 0.1.1 reference adapter

**Start here.** This is the matching 0.1.1 reference-adapter handoff for
PyLoxone 0.10.2. Independent complete-contract review, common private HAOS adoption
and one-room owner same-track/near-saved-position confirmation are complete.
Public source/package/install status is established by the release production
gate, not historical offline flags. No upstream approval or automatic adoption
is claimed; maintainer contact remains separately controlled.

**Current corrections:** [exact remembered-track return](../../../EXACT-TRACK-RETURN.md)
and [R99 overlapping Source ownership](R99-TAKEOVER.md), on the accepted native-mode
baseline. `EXACT-TRACK-DELTA.json`, `EXACT-TRACK-TEST-MIGRATIONS.json` and
`R99-DELTA.json` explain the historical runtime/test deltas; current full patch,
FILE-GUIDE, BASE and preview provenance carry final hashes. Documentation-bearing
distribution hashes can differ from older internal same-version wheels while
all library/adapter runtime bytes remain identical. Use final release checksums.
Source history/bookmarks remain RAM-only; queue/persistent-mode effects are not
proved by mode requests or replies.

## Required setup: enable the Audio Server playback option

**The current adapter requires this option to be ON for the enhanced
PyLoxone-Audio functions to work. It is not just an optional play/pause button.**

In the existing PyLoxone integration's configuration/options:

1. Set **Audioserver host** to the Audio Server's bare hostname or IP address.
2. Enable **Use Audio Server player play/pause (experimental; off by default)**
   (`audioserver_playback: true`). The quoted wording is the CURRENT UI label;
   do not assume that installing the library or entering the host enables it.
3. Save the options before testing the enhanced audio features.

Despite its narrow label, the option creates the native Audio Server command
client needed for direct play/pause, Browse/Search, source selection/return,
supported seeking, native Shuffle/Repeat and announcements. With it OFF, the library dependency can
still load and a configured host can supply metadata, while these enhanced
functions remain unavailable. Existing non-audio PyLoxone functionality and the
Miniserver-only control path are not disabled by leaving the option off.

**Audio diagnostics is a different switch.** It may remain OFF for ordinary
operation; enable it only when collecting a troubleshooting report. Turning
diagnostics on does not enable the Audio Server playback features.

Jo's review/adoption checklist must explicitly verify the host and playback
option above before interpreting missing controls or feature-test failures.
The current label understates the option's scope; consider clearer wording such
as **Enable Audio Server controls** during upstream review. This handoff does
not change the label, default, feature gate or anyone's saved configuration.

## Ordered maintainer checklist

For this increment also read [NATIVE-MODES.md](../../../NATIVE-MODES.md) and
`NATIVE-MODES-DELTA.json`. Verify current native permissions, explicit firmware
qualification, full-repeat-cycle advertisement and mode unknown/disconnect
handling. Exercise standard HA services for all synthetic rooms with Local
Library and native Spotify; no HA Spotify bridge or provider command/state is
permitted. Verify exactly one native requested mode write, external updates,
cancel/unload/error cleanup and unchanged mode setters/artwork. Review the separate
exact-track correction's bookmark and per-item-start changes explicitly.
The pinned standard frontend function proof is not live rendered acceptance.

1. **Identify and inspect.** Obtain the matching reviewed repository/manifest and
   verify checksums. Read the root README, SPOTIFY.md, POSITION-RESTORE.md and
   RELEASE-SCOPE.md. `FILE-GUIDE.json` lists EVERY adapter file with what/why/tests
   and exact base/assembled hashes. `DELTA-0.1.1.json` separately explains the small
   runtime difference from published 0.1.0; `DIAGNOSTICS-DELTA.json` maps the new
   opt-in diagnostic runtime increment against accepted0.1.1. Do not mistake the
   complete adoption patch for all-new work.
2. **Reproduce the pinned patch.** Host is JoDehli/PyLoxone released **0.10.2**,
   commit `3db77b81f69c77cc814675d191061533b464df5e`, not unreleased master.
   `audio-0.1.1-on-0.10.2.patch` is a binary-capable Git patch against that exact
   complete base. Check BASE.json first, then `git apply --check` and apply in a
   fresh isolated copy. Compare every assembled file against BASE.json. The
   preview builder independently verifies exact upstream/overlay/library inputs.
3. **Run source and actual-wheel checks.** Use a provisioned Python **3.14** test
   environment with the declared runtime dependencies and HA pytest plugins;
   canonical offline evidence is Python 3.14.7 / HA 2026.9.1. The package requires
   Python >=3.14; this is not an all-version compatibility matrix.

       python tools/test_project.py library --work-dir /path/to/new-library-check
       python tools/test_project.py adapter --host-base /path/to/exact-0.10.2 --work-dir /path/to/new-adapter-check

   Build from clean source per CONTRIBUTING-RELEASE.md, install the exact local
   wheel into a NEW isolated target with dependencies already supplied, and run
   BOTH commands again with `--library-root /path/to/installed-wheel`. Inspect
   exit codes, per-case JUnit IDs, actual-imports.json and unchanged-input flags.
   HA imports are rejected in the portable suite; TCP is blocked, synthetic
   AF_UNIX websocket/crypto paths remain real. Run preview install/update/rollback
   fixtures per preview-build/README.md. TEST-DISPOSITIONS.json accounts for exact
   baseline/candidate identities, retired bridge-only contracts and retained native
   coverage; smaller totals are not evidence of better behaviour by themselves.
4. **Review the semantics, not just green tests.** No HA-Spotify provider binding,
   OAuth/session access or provider API traffic remains. Keep native Loxone Spotify,
   accounts, metadata, Browse/Search, controls/manual seek, exact room mapping,
   source/announcement fences and unload/cancellation. Previous content must be
   usable exact-room content, including qualified native/external observations;
   Browse folders, labels and phone-only playback do not qualify. Check actual
   HA source-call external-return tests, not only advertised labels. Preserve
   Line-In last and the standard Source heading; no Core/frontend/custom card.
   Saved exact-track return now requires matching room/account/track feedback;
   provider-only feedback is insufficient. Whole-queue/universal position remains
   unproved; one-room return confirmation is described in the root README. One conditional
   best-effort native seek remains. After confirmed same-track source return,
   missing seek capability now allows at most two seconds of cancellable metadata
   readiness, not a replay/retry. Already-ready targets do not wait. Verify the
   same path/options across all 12 synthetic rooms, independent bookmarks,
   interleaved rooms and cancellation in readiness/authentication. Keep positive
   current-target bit32, all identity/duration/event/fence guards and one native
   send. A transient different target must not revive by changing back. Timeout
   retains confirmed playback. One-room confirmation is not all-firmware proof.
   Volume lag is observation-only. Existing ordinary fixed warnings remain;
   legacy private capture is excluded. Review the new default-off diagnostics
   separately: fixed schema/privacy before enqueue, actual send/completion/reply
   boundaries, ordered restore reasons, bounded persistence and real HA admin
   download. Switch toggles must not reload, reconnect, actuate or clear bookmarks.
   See DIAGNOSTICS.md and the `test_audio_diagnostics_*` / `test_diagnostic_*` suites.
5. **Rebase for your actual current branch.** Before adoption compare the ACTUAL
   current upstream tree, not merely a version string. This is a versioned
   reference snapshot, NOT an evergreen full-file overlay. Rebase the focused
   delta and preserve intervening upstream fixes. The new owning `__init__.py`,
   switch, diagnostics and Miniserver hooks are explicitly mapped in the file
   guide; TEXT platform and unrelated0.10.2 fixes remain preserved.
   Rerun relevant host regressions and source/wheel/adapter checks after a rebase;
   old pinned receipts do not prove a newer branch compatible.
6. **Adopt deliberately.** The manifest must select the exact tested
   `PyLoxone-Audio==0.1.1` with prior dependencies and integration version/domain
   intact. Complete the **Required setup** above, including the ON playback
   option, before enhanced-audio acceptance testing. Normal external HA setup
   requires that exact public pin to resolve;
   verify this release’s public production-gate receipts before external adoption.
   Do not bypass HA dependency processing, patch Core or install a second
   integration. Preserve config entries, entity IDs, areas and unrelated options.
   The removed bridge option is ignored; the separate HA Spotify entry is not
   disabled/deleted/rebound. After merge, Jo's upstream files own their evolution;
   the library project maintains its portable API and versioned reference adapter.
7. **Approve/release separately.** Record actual Jo review/approval, applicable
   device/tester outcomes and the exact adopted base/pin. Complete the release
   checklist and obtain the owner's separate external-action authority before
   pushing/tagging/uploading/contacting anyone. Verify the published normal named
   dependency, downloaded artifacts and CI, rather than calling local wheels a
   public release. Only a released PyLoxone build selecting the pin updates normal
   users; publishing a library alone does not.

## Bounded radio-history correction (R79-01)

`pyloxone_audio/catalogue.py` now qualifies recent TuneIn/Loxone Radio entries as
native station type2 with no explicit unplayable/unknown flag before treating
them as previous content. A native-looking path on a Browse folder is not a
station. `tests/adapter/test_previous_radio_usability_011_ha.py` exercises both
namespaces through the actual HA source service, including negative rows,
ordinary playable controls and qualified external room sessions that remain
usable despite bad recent-history rows. Three existing positive-radio fixture
files now supply proper station type2; their assertions and case IDs are
unchanged (see TEST-DISPOSITIONS.json). That earlier library-only correction did
not change the adapter runtime, pinned upstream base or full Jo adoption patch.
The current approved diagnostics increment DOES change the scoped adapter hooks,
patch and preview; use their current manifests rather than that historical claim.
Fresh independent OpenAI review accepted the corrected diagnostics candidate
`fe1f226e10a02793eb167cc718cecab3cab2c553`, including separately executed source
and exact-wheel owning-HA checks and closure of the JSON recovery, abandoned
atomic-write and preference-persistence findings. This is completed offline
engineering review, not Jo's review/approval. Subsequent private HAOS adoption
verified the exact pair and default-off report; owner feedback and a live enabled
export confirmed the normal collection/download journey. Later owner testing
confirmed two same-track/near-saved-position returns in one room; this is not
general firmware, whole-queue or all-room acoustic acceptance.

## Separate tester handoff

[The tester start-here](../../../preview-build/README.md) supplies the COMPLETE
matching integration ZIP, precise prerequisites, normal dependency handling,
backup/install/update/rollback and native UI/report checklist. It is independent
of waiting for an upstream merge, but external appliance use still requires a
resolvable published pin and authorised delivery. HACS updates can overwrite it.
Do not hand Sebastian only a wheel or the Jo patch.

## Attribution and evidence boundaries

Apache-2.0, NOTICE.md, upstream authorship and Sebastian (@SebastianEitzert) credit
remain. Dave directs scope; implementation is human-directed and OpenAI-supervised.
Independent review must inspect/run the frozen candidate on this same Kanban card;
it must return correctable findings rather than silently editing the implementation.
Offline synthetic tests and filesystem rollback fixtures do not prove HAOS restore,
physical playback/seek, all firmware, upstream approval or installation. Parent
local adoption retains its existing separately authorised actual-target checks,
backups and rollback; this guide does not invent another generic approval gate.
