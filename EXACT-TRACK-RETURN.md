# Exact remembered-track return — 0.1.1

The matching library and adapter passed independent source and exact-wheel review, and the common pair was installed on Home Assistant OS (Core 2026.10.4, Python 3.14.9). On 28 October 2026 the owner accepted two normal-use Local Library → Spotify returns to the same track near its saved position, supported by integration command and native content/position feedback. This is one-room confirmation, not all-room acoustic, whole-queue, persistent shuffle or restart-recovery proof.

For public availability, use the matching GitHub release, PyPI version and release verification receipts. Source, tag or uploader success alone is not the production gate. Existing Home Assistant installations do not automatically update.
Use the exact matching release wheel, adapter, preview and checksums; historical
same-version development artifacts are not interchangeable.

## What this correction does

- Individual Spotify **track and podcast-episode** starts include the native
  per-start `/noshuffle` argument, after any validated parent/cursor. Configured
  account, exact item and optional parent/zero-based index stay unchanged.
  Account-qualified item identifiers are retained, not stripped.
- When returning to a saved exact Local Library/Spotify item, feedback from the
  same provider/account but a **different track is not success**. It cannot
  trigger the old track's position seek or replace the preceding last-good item.
  The player still displays the track actually reported by Loxone.
- Continuing feedback from that rejected return retains the prior bookmark.
  A later explicit return attempts that retained item instead of treating the
  wrong currently-playing track as a provider-only no-op. No automatic retry is
  added. A matching return, a new explicit Browse selection, or independently
  corroborated later different playback can update the record normally.
- After matching playback, at most **one best-effort** position attempt retains
  existing bounded capability readiness, authentication, room/account/track,
  lifecycle, event/fence and newer-action checks. An unsupported/failed optional
  seek does not turn matching confirmed playback into source failure.
- A positively qualified current native Spotify session can still use native
  empty-content resume. Unknown/history-only context return retains its existing
  provider contract; exact remembered-item confirmation does not invent an item
  for a context. Local Library commands, context starts, radio, Line-In,
  explicit native Shuffle/Repeat setters and their capability rules are unchanged.

There is no Spotify API, compensating Shuffle/Repeat write, queue controller,
new setting, delay-only fix, cursor arithmetic change, fallback item, cross-room
policy or persistence implementation. The existing playback setup gate remains
required (see the main README).

## Function-to-feature map

| File/symbol | Change and regression coverage |
| --- | --- |
| `pyloxone_audio/native.py:AudioServerCommands.async_play_catalogue` | Type-specific per-item flag; `tests/library/test_exact_track_start.py` checks tracks/episodes, qualified IDs, no parent and cursors 0/13/63, plus context/other-route negatives |
| `pyloxone_audio/sources.py:_source_matcher`, `async_select_catalogue` | Saved exact-item match before confirmation/optional seek; preserve ordered source/track/account restore reasons |
| `pyloxone_audio/selection.py:async_source_route` | Owning adapter may suppress current-session no-op after a rejected exact return; ordinary native session routing unchanged |
| `adapters/pyloxone/overlay/custom_components/loxone/media_player.py:LoxoneAudioZoneV2._update_audio_metadata`, `async_select_source`, `_async_play_radio` | One room-local rejected-return marker, using the existing saved session and passive qualification. Protect last-good without changing truthful metadata; release on qualified replacement/explicit success |
| `adapters/pyloxone/overlay/custom_components/loxone/audio_diagnostics.py:_safe_event` | Persisted strict schema retains the aliased Spotify flag; recovery/extra-tail/non-Spotify negatives in owning-HA tests |
| `pyloxone_audio/diagnostic_events.py:DiagnosticEmitter.route` | Recognise only the fixed per-item flag, preserving keyed account/content/parent aliases; unknown tails still refused |
| `tests/adapter/test_exact_track_return_ha.py` | Real owning HA service/coordinator/authenticated native transport, synthetic I/O: 30.021s/index13 shape, wrong feedback even with new flag and reported shuffle false/true, delayed correct feedback, account/room negatives, explicit retry/Browse, late matches and independent replacement |

Existing full-suite lifecycle/authentication/cancellation, all-room isolation,
mode, manual seek, announcement, setup/unload and no-uncertain-replay controls
remain part of acceptance. See the maintainer's `EXACT-TRACK-DELTA.json` and
`EXACT-TRACK-TEST-MIGRATIONS.json` for exact file/expectation dispositions.

## Source evidence and limits

The pinned official Loxone 17.2.2 client, retrieved 26 October 2026 from the official
Linux release AppImage, uses `playItem -> shouldShuffleAudioItem ->
ServicePlayScheme`; individual track/episode types choose `noshuffle`, serialized
**after** `parentpath/<parent>/<zero-based-index>`. The retained bundle SHA-256 is
`76f4ff34c3156cf9109524c37640d33352968fc7dc7477af6866a9983f5abacf`.
This is command/caller parity, not proof of the physical firmware's selection
algorithm or a persistent shuffle/queue-preservation guarantee. The motivating
wrong-track observation included reported shuffle **false**, so it is not
explained simply by a shuffle-on switch.

Wrong-feedback fixtures are deliberately independent of the flag. A simulator
that returns the right item when it sees the flag cannot prove the hardware cause.
Those offline fixtures use no device credentials or household commands. Later
owner-operated one-room returns supplied matching content/position confirmation;
parent/queue, universal audible position and persistent-mode effects remain unproved.

The receiver cannot establish an external command's issuer from identical
same-item feedback. Continuing the rejected item alone does not establish a new
independent selection. Explicit Browse can deliberately choose that item; later
qualified different playback also replaces the marker. This is a bounded
interpretation of observed identity, not invented causal device evidence.

## Review and adoption

1. Inspect the exact delta, test-migration map and retained original failed receipts.
2. Reproduce canonical source and exact installed-wheel suites with blocked TCP,
   strict runtime/resource warning gates, case parity and import evidence.
3. Verify the complete preview against its provenance; exercise the unchanged
   builder/install/update/rollback tests. Preview material stays out of Python
   wheel/sdist. Do not use older same-version artifact hashes.
4. Preserve the completed independent exact-correction review and common adoption
   evidence. Re-review changed runtime; historical mode/seek reviews alone do not
   approve future changes.
5. Keep software tests, installed-byte verification, one-room owner acceptance and
   the public production gate separate. Upstream adoption/contact is not implied.

Restart persistence is a separate design and is intentionally not bundled here.
