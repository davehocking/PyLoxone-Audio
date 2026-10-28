# R99-01: exact-return qualification during newer Source actions

This records the host-adapter correction to the original exact-track candidate
`952210a5c0a16dd238a4dc12db6e9981279993de`. Independent complete-contract review
and common private adoption are now complete, followed by bounded one-room owner
same-track/near-saved-position confirmation. Public availability is established
separately by the release production gate. No upstream approval is implied.

## What and why

An older saved-item return may have received a wrong track while its exact
confirmation is still waiting. A newer Source action must retain that unresolved
qualification: provider/account equality alone cannot turn that wrong item into
success or replace the original last-good bookmark.

`LoxoneAudioZoneV2._async_begin_source_action` now calls the synchronous
`_retain_unconfirmed_source_return` **before changing generation, replacing the
owner/target or awaiting old transport cleanup**. This reuses the existing saved
session, source fence and bounded rejection marker. The superseded caller still
cannot write that marker from its `finally`; only its still-current failure path
uses the same helper. No new cache, retry, transport or queue policy is added.

The source fence distinguishes unconfirmed dispatch from already-confirmed
playback awaiting only optional seek readiness. A confirmed matching native
session therefore retains its legitimate no-op path. A third newer action,
cancellation or unload cannot erase the obligation during old socket cleanup.
Explicit Browse can choose the currently playing rejected item by exact content;
that content-qualified no-op is not the rejected provider-only Source no-op.
Subsequent independently qualified different playback can update history without
silently releasing the old transport uncertainty fence; the next explicit action
owns its ordinary release. Actual now-playing remains truthful throughout.

## Functions, tests and artifact ownership

- Changed runtime file: `overlay/custom_components/loxone/media_player.py` only.
  Changed symbols: `_async_begin_source_action`, new
  `_retain_unconfirmed_source_return`, `_async_play_radio`'s current-owner cleanup.
- `tests/adapter/test_exact_return_takeover_ha.py` exercises the real HA Source
  service, actual native authentication and synthetic external I/O: immutable
  reviewer overlap/settled behavior, awaited old-socket cleanup, third Source,
  cancellation, config-entry unload, explicit Browse, a wrong newer return,
  failed authentication, independent playback and confirmed-session overlap.
- Every original product test, strict runner, library payload, setup gate, mode
  setter, exact-item serialization and optional single-seek policy is unchanged.
  Original versioned wire/provider-only oracle migrations remain separately
  documented; R99 adds cases rather than revising their expectations.
- The engineering correction reused the exact original candidate wheel SHA-256
  `55f505ff5731d956b9a6e1105c57c5d57495de4a54c7de71652a35198bde229a`.
  The final release rebuilds documentation-bearing distributions and the preview;
  their hashes legitimately differ while all runtime members remain identical.
  Use final release checksums, not this historical engineering wheel identity.

## Reproduce and adopt

1. Read the exact correction delta, original exact-track map and migration map.
2. Apply the current full Jo patch to the pinned upstream 0.10.2 base and compare
   every assembled member with `BASE.json`; do not overlay historical full files.
3. Run canonical library and owning-HA suites from source and the exact installed
   wheel with blocked TCP, strict warnings, actual import receipts and case parity.
4. Rebuild the complete preview with the unchanged builder and run its existing
   install/update/rollback checks. Use the current provenance/checksums and follow
   `preview-build/README.md`, including its Required setup and dependency checks.
5. Preserve the completed independent review of the COMPLETE correction. The
   failed original review99 remains historical evidence, not approval. Future
   runtime changes require their own review; household adoption and upstream
   contact are separate from publication and offline tests.

This fixes the demonstrated software takeover defect. It does not establish the
cause of physical firmware track substitution, persistent shuffle/queue effects,
rendered UI or sound. The original per-item `/noshuffle` parity is retained, not
promoted into hardware proof. Restart persistence is separate and not implemented.
