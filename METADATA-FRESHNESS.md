# 0.1.2: native metadata freshness

This correction passed independent source/exact-wheel, owning-HA engineering and
release-preparation review. The accepted matching runtime pair was installed
and parent-verified locally on 29 October 2026 for normal-use testing. This
publication successor preserves all runtime bytes; hosted/public-index acceptance
and sustained live recovery remain separate. A connected WebSocket proves neither
application-frame delivery nor that an old exact-player sample still describes
current playback. The original physical reason for missing accepted updates has
not been established.

## Required installation unit

Use the **matching 0.1.2 library and current-host adapter together**, not a wheel-only
replacement. The adapter remains based on PyLoxone 0.10.2 at its pinned upstream
commit. Its dependency is `PyLoxone-Audio==0.1.2`; the integration domain and host
version remain unchanged. The library requires Python >=3.14, not a broader tested
compatibility promise. Check the exact release and public-index gate before
external installation; no automatic installation or upstream adoption is implied.
Old 0.1.1 preview archives are historical artifacts, not this version's adapter.

### Required setup

Set **Audioserver host** and enable **Use Audio Server player play/pause
(experimental; off by default)** (`audioserver_playback: true`) for active status
reconciliation as well as the existing Browse/Search, source return, play/pause,
seeking, native modes and announcement features. The narrow label is unchanged.
**Audio diagnostics** is separate and is not required to enable recovery.

The existing Audio Server host and playback opt-in still govern command-client
creation. This correction does not enable that option, change saved configuration
or acquire a separate provider login. With passive-only metadata, stale active
attributes become unknown; it does not silently create a command client.

## Shared policy and owning host

- The shared coordinator separates native-sample freshness from independent
  Miniserver PLAYING. It withholds expired active samples from all consumers,
  including command eligibility, instead of merely capping a displayed slider.
- Active samples expire after 30 seconds, or earlier at a trustworthy native
  playing track boundary. Structurally empty exact-player frames cannot keep old
  content fresh. Idle/paused rooms are not polled simply because time has passed;
  an active wake requalifies old state. STOP must not resurrect a withheld row.
- The HA entity reports independent PLAYING, clears expired projected attributes,
  and registers an entry-owned reconciler only when the existing option provides
  native commands. It does not change truthful Miniserver playing/volume state.
- Recovery uses the existing authenticated native player-status read, not a
  playback/source/seek/mode operation, another cache or a new receiver service.
  It publishes only through the original receiver's normal update path.
- An entry serialises reads, spaces starts by at least one second, bounds each
  recovery by 15 seconds and caps per-player failure backoff at 300 seconds.
  Successful but already-ended tracks cool down rather than starving another
  room. These are software policy bounds, not physical-firmware guarantees.
- A read is discarded after intervening meaningful exact-player feedback, stream generation
  change, changed credentials, source intent, ownership/fence changes or unload.
  Wrong-player or unusable status cannot certify current content. Timers/tasks
  are cancelled with the entry. No automatic media-control retry is introduced.
- A bare player row or one whose optional fields all fail parsing cannot veto a
  useful status result while the read is pending. A per-player feedback revision
  remembers intervening useful observations even if a later empty row replaces
  the raw cache. Same-track updates, artist/album-only data, numeric zero, explicit
  shuffle false and account/context identity still veto an older read. Generated
  timestamps, greeting capabilities and the parser's default inactive-event flag
  alone do not. No old capabilities or content are merged into a newer row.
  Continued empty traffic may make presentation unknown again; this correction
  proves useful read publication, not that an empty frame contains track data.
- Explicit opted-in source selection can requalify an expired existing sample;
  it still requires the established source/account/identity/ownership guards.
  Unqualified status cannot overwrite a populated last-good source record.

## Evidence and limits

The parent regression and added reconciliation tests reach actual HA setup,
entities, event receiver and lifecycle with synthetic external I/O. Controls cover
continued PLAYING across track changes, track end, overnight wake, passive-only
unknown state, rejected seek, authentication changes through synthetic encrypted
wire I/O, newer intent/feedback, reconnect, two entries, room fairness, capped
backoff and unload. They are not a live household or physical-server test.

The exact final source/wheel case inventories, imported paths, unchanged-input
receipts, build/preview hashes and independent review belong to the engineering
handoff. A focused green test run alone is not full acceptance. Public release,
normal index resolution and any physical acceptance remain separate operations.

## File map for review

- `pyloxone_audio/metadata.py`: freshness, entry timer, bounded reconciliation,
  explicit bootstrap and cleanup.
- `pyloxone_audio/native.py`: receiver snapshot refresh and status-specific
  authentication/intent continuity before dispatch and before publication.
- `adapters/pyloxone/overlay/custom_components/loxone/media_player.py`: independent
  state feedback, clearing, entity-owned opt-in registration and lifecycle.
- `adapters/pyloxone/BASE.json` and the host manifest: exact paired assembly/pin.
- `tests/adapter/test_metadata_freshness_regression_ha.py`: immutable parent repro.
- `tests/adapter/test_metadata_reconciliation_ha.py`: owning-HA recovery controls.
- `tests/adapter/test_metadata_inflight_recovery_ha.py`: delayed publication under
  continuing unusable traffic and retained sparse/newer-feedback fences.

The released known issue and owner-controlled public wording are retained in
README/CHANGELOG. No unrelated collaboration, migration, grouping or persistent
bookmark feature is included.

## Remaining source-return limitations

Metadata recovery is not a source-return redesign. A missing qualified saved
session can lead to a different content selection; optional position restoration
can be skipped if native seek support disappears during authentication. One
same-track/saved-position return with shuffle ON succeeded in later local use,
but does not close either case. No new fix, firmware cause, shuffle attribution
or version regression is established by that outcome. See [KNOWN-ISSUES.md](KNOWN-ISSUES.md).
