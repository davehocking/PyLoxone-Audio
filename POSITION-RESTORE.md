# Native saved-position readiness — inherited 0.1.1 behaviour

> 0.1.2 preserves this feature, not a new source-return/mode correction. It is
> prepared but unreleased. See [0.1.2 release notes](RELEASE-NOTES-0.1.2.md) and
> [remaining return/position limitations](KNOWN-ISSUES.md). Historical 0.1.1
> acceptance below must not be read as universal 0.1.2 return acceptance.

## Functional correction and limits

After confirmed Spotify or Local Library source return, the common library path
now allows **at most two seconds** for the same target's explicit native seek
capability. Already-ready targets do not wait. There is at most one optional
native seek, not a retry. Timeout retains confirmed source playback. All rooms
use the same code/options; their tracks, accounts and bookmarks stay independent.

The matching library and adapter passed independent source and exact-wheel review, and the common pair was installed on Home Assistant OS (Core 2026.10.4, Python 3.14.9). On 28 October 2026 the owner accepted two normal-use Local Library → Spotify returns to the same track near its saved position, supported by integration command and native content/position feedback. This is one-room confirmation, not all-room acoustic, whole-queue, persistent shuffle or restart-recovery proof.

No playback option label/default, diagnostics preference or volume policy changed.
Enhanced functions require the Audio Server host and current playback option; see
[Required configuration](README.md#required-audio-server-configuration).

## Verified defect versus historical cause

The exact accepted predecessor is
`fe1f226e10a02793eb167cc718cecab3cab2c553`. Its
`pyloxone_audio/sources.py:async_select_catalogue` checked capability once after
source confirmation. Same-target positive capability arriving later could not
restore the skipped bookmark. The same real Home Assistant `select_source`
service regression, through actual native authentication/request handling and a
synthetic socket's SEND boundary, fails on that exact baseline and passes on the
successor. Missing, zero and nonzero-without-bit32 startup masks are explicit
synthetic alternatives, not an assertion about an earlier firmware payload.

The owner-supplied diagnostics showed two `seek_unsupported` decisions followed
about half a second later by same-content positive support. They did **not**
contain the raw historic native mask, so absent/null/zero/parser origin remains
unproved. A false diagnostic boolean cannot recover that mask. The earlier
25 October 2026 20:47:02.839 UTC fixed warning also proves a handled optional
restore failure, not its precise exception/authentication/reply/guard cause.
Removing the old HA-Spotify bridge was not itself a position fix.

## Source ownership and algorithm

The readiness increment changed the shared library path. Later exact-track and
overlap protection also affect the matching reference adapter. Current ownership:

1. `media_player.py:async_select_source` owns the per-entity source generation and
   task, cancels superseded work, and calls the room catalogue. Removal/unload and
   later controls retire that ownership.
2. `AudioCatalogue` preserves qualified native exact-room history. Its selection
   target carries that room's saved session into `async_select_catalogue`; other
   rooms' activity must not replace it.
3. `sources.py:async_select_catalogue` first settles one source dispatch plus fresh
   exact-room/provider/account and saved exact-track confirmation via `SourceEnvironment` and
   `async_observed_change`. Confirmation is not a promise of seek readiness.
4. All non-capability restore preconditions must hold: live request, correct
   player/source/track/account, playing idle-event state, valid sampled position
   before the current duration minus one second and no uncertainty fences.
   Only if capability alone is missing, `_RESTORE_READINESS_TIMEOUT = 2.0`
   bounds an event-driven listener using the loop's monotonic clock. The source
   confirmation timeout belongs to the earlier operation and has already ended;
   it is not an available remaining deadline. No sleeps/polling or per-room knobs
   were added to runtime code.
5. Current `playback_restrictions & 32` must become positive on the same valid
   snapshot. An intervening invalid target revokes this visit permanently, even
   if it changes back before authentication completes. No earlier track's
   positive capability is retained. Unrelated updates do not reset the deadline.
6. `AudioServerCommands.async_seek` retains the same current-target predicate and
   actual `_async_request` post-authentication checks before SEND. The readiness
   listener stays attached through that request and is removed in `finally`,
   including timeout, cancellation and failure. At most one seek is attempted.
7. A handled `AudioCommandError`, `ValueError` or `TimeoutError` cannot undo
   confirmed source success. No blind replay, progress-success gate or substitute
   track/queue is introduced. An echo is not observed position progress.

Manual seeking remains separate and unchanged. Unsupported radio/input position
restoration remains unsupported; this does not add seek support to every source.

## Offline evidence map

- `tests/adapter/test_seek_readiness_ha.py`: twelve synthetic room identities,
  Spotify/Library, three delayed startup masks; exact source/seek order and room
  bookmark, already-ready and permanently-unsupported controls; real HA/native
  boundary, not a replaced command helper. Interleaved distinct bookmarks and
  cancel-one/complete-other controls. Waiting and post-auth track/account/source,
  pause/stop/event/duration/disconnect/fence invalidation, target reversion,
  cancellation/removal/unload/newer actions, unchanged radio unsupported path and
  busy unrelated frames with a fixed deadline. Synthetic credentials only.
- `tests/library/test_restore_readiness.py`: portable no-HA readiness plus invalid
  or missing bookmark, wrong player, lost snapshot and unavailable-owner guards.
- Existing native wire/source-return/manual-seek/reconnect/diagnostics suites and
  all prior assertions remain. `test_position_limitations_011_ha.py` retains the
  six error/timeout/invalid-reply characterisations: one optional attempt, confirmed
  source retained, no replay or false position claim.
- Exact source and freshly installed wheel use the guarded project runners;
  actual imports, case identities, raw commands/exits and warning evidence belong
  to the accompanying frozen engineering handoff. A preview is a tested reference
  adapter plus an exact library dependency, not a second integration.

The owner’s two accepted one-room returns have matching saved/requested/native
content and near-saved position feedback. Whole-queue preservation, universal
external-app resumption, restart persistence and an audible-volume latency fix
remain unproved. A reply echo alone is not physical position proof. Further
household tests and upstream contact require their own agreed scope.
