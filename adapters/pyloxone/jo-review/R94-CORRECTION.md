# Native modes correction R94-01

This adapter-only successor to `3dd02f5d554f34bb905644a9915c61e1eb229c08`
closes the unobserved interval while a new native Shuffle/Repeat request awaits
cancellation and socket cleanup of its predecessor. Its original exact-player
validity listener is installed before that first await, retains transient native
invalidation even after matching feedback returns, and is removed if takeover
fails or is cancelled. Generation ownership is checked after acquisition, not
mistaken for invalid native state before acquisition. Existing serialization,
newest-action, auth, lifecycle and source/bookmark/artwork/no-retry guards remain.

Only `LoxoneAudioZoneV2._async_set_audio_mode` changes at runtime. There is no
new provider bridge, source-start shuffle policy, playback command or room flag.
The library wheel remains exactly
`9b5c2e7c8558abb18643cedbb65ac82b96ab17d66203cdc6f4596e2663a127ce`.
Version `0.1.1` alone does not identify this corrected adapter.

## Reproduce and review

- `tests/adapter/test_audio_modes_lifecycle.py` promotes review94's14 synthetic
  real-HA controls. Every test-function AST/assertion is unchanged; only Ruff
  formatting, fixture-shadow annotation and an unused import differ. Actual
  overlapping standard HA requests with delayed native socket cleanup cover
  Shuffle and Repeat; stable overlap must still send one newest mode request.
- `tests/adapter/test_audio_modes_takeover.py` adds four failure/cancellation
  cases proving original native observation is present during takeover and its
  temporary subscription is removed without any native socket/write.
- The external, unchanged review94 probe is retained and rerun separately in
  source and exact-wheel contexts. The original records remain sealed; no
  assertions are weakened to fit the correction.
- Run the unchanged `tools/test_project.py` source and exact-wheel library and
  adapter commands in the main maintainer checklist. Use this revision's BASE,
  full upstream patch, FILE-GUIDE and complete preview together. The common
  native setup gate/default and diagnostics OFF default are unchanged.

This is historical engineering-correction provenance. Independent complete-contract
review and common private adoption subsequently completed. Synthetic loss/cleanup
schedules do not prove that physical firmware emitted them or caused a historical
wrong-track return. Current exact-item source-return behaviour is documented in
EXACT-TRACK-RETURN.md; public availability requires the actual production gate.
