# Maintainer: review the 0.1.2 reference adapter

This versioned reference preserves the independently accepted 0.1.2 runtime,
already installed locally for normal-use testing, and passed independent release-
preparation review. Hosted CI/public dependency acceptance and physical/UI outcomes
are separate. No upstream adoption or maintainer contact is implied.

## Two accurately labelled review patches

- **Small incremental patch:** `audio-0.1.1-to-0.1.2.patch`, based on the published
  PyLoxone-Audio 0.1.1 AUDIO adapter at `222ce5640c56d9168b509a0d5f161ca21b704f14`.
  Only two host files: `media_player.py` **+12/-0** and `manifest.json` **+1/-1**.
  The entity adds opt-in reconciler ownership plus independent PLAYING feedback
  and stale projection clearing; the manifest selects the broader library fix.
  This assumes the previously supplied audio adapter. **Jo has not adopted it**
  by virtue of this comparison. It is not a two-file patch for stock PyLoxone.
- **Cumulative stock-host patch:** `audio-0.1.2-on-0.10.2.patch`, against exact
  JoDehli/PyLoxone stock 0.10.2 commit `3db77b81f69c77cc814675d191061533b464df5e`.
  Includes the complete existing audio adapter, with FILE-GUIDE.json what/why/tests
  and base/assembled digests. The old 0.1.1 patch is retained historical context.

Verify/apply each in a fresh copy of its stated baseline with `git apply --check`
then `git apply`; both must match all assembled BASE.json files. Inspect
`INCREMENTAL-0.1.2.md` for exact paths and reproduction steps.

## Required setup and paired installation

Use **both PyLoxone-Audio 0.1.2 and its matching adapter** on the pinned PyLoxone
0.10.2 base (`3db77b81f69c77cc814675d191061533b464df5e`). A wheel-only update does
not wire independent Miniserver PLAYING, stale-attribute clearing or reconciler
ownership. The integration domain/version/config entries and existing requirements
remain unchanged except the exact library pin `PyLoxone-Audio==0.1.2`.

In the existing entry:

1. Set **Audioserver host** to the bare native hostname/address.
2. Enable **Use Audio Server player play/pause (experimental; off by default)**
   (`audioserver_playback: true`). This narrow CURRENT label also gates status
   recovery, Browse/Search, source return, native seeking/modes and announcements.
3. Save and verify these settings before enhanced-feature acceptance. This work
   does not rename the gate, change its default or alter saved options.

With the option OFF, configured metadata stays receive-only and expired active
attributes become unknown without creating a command client. Existing Miniserver
controls remain. **Audio diagnostics** is separate, optional and default OFF;
logging does not enable playback or recovery. No HA Spotify login/binding/API,
custom card, Core/frontend override or second integration is required.

## Ordered inspect / reproduce / adopt checklist

1. **Inspect exact inputs.** Read [METADATA-FRESHNESS.md](../../../METADATA-FRESHNESS.md),
   `METADATA-DELTA-0.1.2.json`, `FILE-GUIDE.json` and `../BASE.json`.
   The delta identifies the small 0.1.1→0.1.2 runtime correction; the full patch
   includes all existing audio adapter work, not just this correction. Preserve
   historical R99/native-mode/diagnostics deltas as historical evidence.
2. **Reproduce the focused host assembly.** In a fresh isolated copy of the EXACT
   upstream 0.10.2 commit, run `git apply --check` then apply
   `audio-0.1.2-on-0.10.2.patch`. Compare all assembled file hashes with BASE.json.
   The binary-capable patch preserves stock unrelated files and includes the
   complete adapter, not a separately installable integration. The old 0.1.1
   patch is retained history, not a patch for this candidate.
3. **Exercise real owning tests.** Use a provisioned Python 3.14 environment with
   declared dependencies and HA test plugins. Recorded offline environment is
   Python 3.14.7 / HA 2026.9.1, not universal compatibility.

```sh
python tools/test_project.py library --work-dir /path/to/new-source-library
python tools/test_project.py adapter --host-base /path/to/exact-0.10.2 --work-dir /path/to/new-source-adapter
python tools/test_project.py library --library-root /path/to/exact-installed-wheel --work-dir /path/to/new-wheel-library
python tools/test_project.py adapter --library-root /path/to/exact-installed-wheel --host-base /path/to/exact-0.10.2 --work-dir /path/to/new-wheel-adapter
```

Inspect actual imports, complete JUnit case identities/outcomes, unchanged-input
flags, exits and warning gates, not just totals. Portable tests reject HA imports;
external sockets are blocked while synthetic AF_UNIX/crypto boundaries remain
real. Parent regression assertions remain immutable. Run actual preview
install/update/rollback/refusal fixtures from the
[tester guide](../../../preview-build/README.md).

4. **Review freshness and ownership.** A connected socket is not fresh application
   data. Active samples expire at 30s or trustworthy track end; known pause/idle
   data are not age-polled. Independent Miniserver playback/volume stays truthful.
   Sparse data and known zero/False survive; empty player rows cannot postpone
   recovery. Unknown metadata must not authorise seek, false exact-track success
   or replace last-good room/source records. Review continuing PLAYING, overnight
   wake, silent-open streams, wrong/unusable status, auth delay/change, passive-only,
   reconnect, two entries, room fairness, intent/fence/unload races and cleanup.
   Status reads share existing authenticated transport: serial, >=1s spacing,
   15s whole deadline and capped per-player backoff. They cannot send playback,
   source, seek, volume or mode fallback. No RFC ping policy/state engine is added.
   Suspend the read and inject repeated empty same-player frames before allowing
   its useful reply: publication must succeed while noise continues. Pair this
   with useful same-track, sparse zero/False, account/context and newer content
   followed by empty frames: those observations must still veto the old reply.
   `test_metadata_inflight_recovery_ha.py` exercises both through real HA.
5. **Preserve established functionality.** Keep native account/player/room/source
   identity, R99 overlapping-source ownership, exact per-item noshuffle,
   announcement/source fences and uncertainty/no-replay semantics. Source return
   keeps one best-effort optional position restore, not a source-success gate or
   competing queue controller. Retain metadata/artwork, native mode permissions,
   Browse/search, volume behaviour, configuration and unrelated integrations.
6. **Obtain independent review and rebase deliberately.** This is a VERSIONED
   reference snapshot, not an evergreen full-file overlay. A fresh reviewer must
   inspect/run the exact candidate and return findings without editing it. Before
   later upstream adoption compare the actual current host, port the focused delta
   preserving intervening fixes, and rerun applicable host/source/wheel tests. After
   upstream adoption the host repository owns its evolving adapter; publishing a
   library alone does not update the host's pinned dependency.
7. **Adopt / release separately.** Do not deploy or publish from these offline
   receipts. Normal external setup needs the exact approved public pin to resolve,
   preserved entries/IDs/credentials/options, supported backup and rollback, actual
   Core imports and the Required setup above. Retain HACS overwrite risk. Owner UI,
   sound, current-track recovery and control continuity remain separate evidence.
   Follow [release gates](../../../preview-build/PRE-RELEASE.md) before any approved
   publication; verify downloaded artifacts, public named-pin installs and hosted
   CI rather than relabelling local tests as public success.

## Function map for this increment

| Owner | Function | User-visible effect |
|---|---|---|
| Library `metadata.py` | `get`, `set_playing`, `_remaining`, `_check_freshness` | Stale active track/timing becomes unknown, not stale PLAYING metadata |
| Same coordinator | `_async_reconcile`, `async_add_reconciler`, `async_stop` | Bounded opt-in status recovery and entry-owned cleanup |
| Library `native.py` | `async_player_status`, `_async_request` | Existing exact-player read with current authentication/intent guards |
| Existing receiver/listener | `async_refresh_snapshot` | Reject meaningful intervening feedback/generation changes; empty rows cannot veto useful recovery |
| Adapter `media_player.py` | `async_added_to_hass`, `event_handler`, existing metadata updater | Supply independent playing state, register eligible reads, clear stale projected attributes |
| Host manifest/BASE | exact pin and hashes | Deliver a matching library/adapter installation unit |

## Separate complete tester handoff and limits

The maintained [preview-build](../../../preview-build/README.md) provides the
complete 0.1.2 ZIP, exact provenance/checksums and exercised filesystem
install/update/rollback route from stock or the exact published 0.1.1 predecessor.
Do not give a tester only the wheel or patch. The original physical receive cause
is unproved; software recovery does not establish physical-firmware reliability,
rendered UI, queue/persistent modes or all-room compatibility. Bookmarks remain
RAM-only; no grouping or persistence feature is added.

Apache-2.0, upstream notices/authorship and Sebastian (@SebastianEitzert) credit
remain. Development is human-directed and OpenAI-supervised; no Qwen contribution
is claimed for this lifecycle/protocol chunk. Private household evidence, access
scripts and development capture remain outside publishable runtime/artifacts.

## Current limits and handoff action

Read [KNOWN-ISSUES.md](../../../KNOWN-ISSUES.md) before testing. Missing qualified
sessions and transient native seek-support loss remain unresolved source-return
cases; one shuffle-ON same-track/position success does not close them. No new
provider/grouping/persistence/mode feature or historical cause is claimed.

Jo: inspect the two baselines, reproduce assembly/tests, then port only against
your actual chosen upstream revision and coordinate the dependency pin.
Sebastian: when separately offered an approved available preview, use its
start-here guide and report normal playback/track changes and source returns
with expected versus observed content/position separately. Neither action is
requested by an automatic post or remote draft; outreach remains local-only.
