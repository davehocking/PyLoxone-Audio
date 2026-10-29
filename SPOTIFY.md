# Native Spotify support — inherited 0.1.1 behaviour

> 0.1.2 preserves this feature, not a new source-return/mode correction. It is
> prepared but unreleased. See [0.1.2 release notes](RELEASE-NOTES-0.1.2.md) and
> [remaining return/position limitations](KNOWN-ISSUES.md). Historical 0.1.1
> acceptance below must not be read as universal 0.1.2 return acceptance.

The matching library and adapter passed independent source and exact-wheel review, and the common pair was installed on Home Assistant OS (Core 2026.10.4, Python 3.14.9). On 28 October 2026 the owner accepted two normal-use Local Library → Spotify returns to the same track near its saved position, supported by integration command and native content/position feedback. This is one-room confirmation, not all-room acoustic, whole-queue, persistent shuffle or restart-recovery proof.

For public availability, use the matching GitHub release, PyPI version and release verification receipts. Source, tag or uploader success alone is not the production gate. Existing Home Assistant installations do not automatically update.
No upstream PyLoxone adoption is implied.

## What changed

The optional bridge to Home Assistant's separate Spotify integration is retired.
There is no room-binding option, OAuth/session lookup, Spotify Web API profile,
playback or queue read/write, or HA-provider receiver arbitration in 0.1.1.
Legacy saved `audioserver_spotify_return` options are ignored on normal entry
reload. There is no automatic edit, deletion or rebinding of HA's Spotify entry.
Existing native source/announcement/manual-seek safety and read-only legacy
uncertain-write journal restoration remain; Spotify-named code was not blindly
removed.

**Do not install, disable or delete HA Spotify for this feature.** It is independent.
Configure Spotify normally in Loxone. Normal Spotify Connect remains Spotify's
way to choose a receiver; this project does not transfer another device's queue.

## What remains

- Native Loxone room controls, metadata/artwork, Browse/Search and explicit
  catalogue playback, where configured/supported and audio playback is enabled.
- An already-playing exact native source can be a no-op. A paused, positively
  qualified native Spotify session can receive a native empty-content resume.
- Returning after another source can use the exact room's last qualified native
  track/account or usable concrete recent native history. It need not have been
  started by Home Assistant: Loxone/Spotify Connect playback observed for that
  room can qualify. Another room, phone-only playback, a provider name/title or
  visiting a Browse folder does not create a resumable selection.
- Supported native manual seek and one conditional best-effort native position
  attempt after source confirmation do not require HA Spotify.

An absent previous-source option is not a subscription/setup error. First choose
and **play** content in **Browse media > Spotify · your account** (or select that
room with Spotify Connect). For TuneIn stations the actual Browse root is
**Radio**, not TuneIn. Only usable prior content appears in the standard **Source**
selector; exact configured Line-In inputs remain directly selectable and last.
No new persistent history database or custom frontend is introduced.

## Concrete active call map

Paths below are relative to this repository. Adapter modules live under
`adapters/pyloxone/overlay/custom_components/loxone/`.

| Owner/symbol | Responsibility |
| --- | --- |
| `config_flow.py` setup/options | Existing entry, optional Audio Server host/playback; no HA-Spotify binding schema or validation |
| `media_player.py: LoxoneAudioZoneV2.async_select_source` | Existing HA service, newest-request/lifecycle ownership, native snapshot bootstrap, actionable first-use error |
| `pyloxone_audio/selection.py: async_source_route` | Native current-session/no-op routing and qualification; no provider-bridge call |
| `pyloxone_audio/catalogue.py: previous_source_labels`, `remember_source`, `async_source_return` | Exact room/provider/account prior selection, qualified external observations and optional bounded parent/cursor enrichment |
| `pyloxone_audio/sources.py: async_native_catalogue_noop`, `async_select_catalogue`, `_source_matcher` | Native account checks, one settled dispatch and fresh exact-room/provider/account confirmation; strict exact-item proof for explicit Browse and saved exact-track return |
| `pyloxone_audio/native.py: async_service_accounts`, `async_spotify_handoff`, `async_play_catalogue`, `async_seek` | Authenticated native Loxone reads/commands; not Spotify Web API calls |
| `spotify_continuity.py` | Read-only bounded historical uncertainty restoration consumed by native control guards; no session controller, OAuth token or provider action |

The [exact-track correction](EXACT-TRACK-RETURN.md) requires matching track
feedback for a saved exact-item return. Different content is not successful exact
return and does not replace the preceding last-good bookmark. The actual reported
track remains visible; there is no automatic old-track replay or seek into a
different item. Unknown/history-context resume keeps its source-level contract.
Native per-item starts now use `/noshuffle` after any validated parent/cursor;
this is not a persistent queue/shuffle guarantee. Optional seek
requires saved valid position, exact track/account, native seek capability,
current request and no conflicting source/announcement fence. Failure is logged
without private payloads; confirmed source playback stays successful. There is
no position-success gate, retry loop or new cross-app arbitration.

## Evidence and limits

`test_native_only_011_ha.py` and `test_spotify_enabled_disabled_ha.py` exercise
normal setup/reload and actual HA source calls with old optional mappings and a
separate HA Spotify entry, proving no provider session use and no entry changes.
`test_external_previous_011_ha.py` starts without HA selection or usable recent
history, observes native playback, switches away, then calls actual HA
`select_source`: one qualified native dispatch and synthetic confirmation.
`test_external_previous_guards_011_ha.py` keeps changed-account/supersession guards.
Existing native account, lifecycle, cancellation, transport, Browse and manual
seek cases remain in their mixed Spotify-named modules.

These are offline synthetic proofs, not universal external resumption or queue
retention claims. Archived owner tests on 0.1.0 returned the right track at 00:00;
at least one optional seek attempt failed, but its precise transport/guard/reply
cause is not recorded. The later 0.1.1 readiness/exact-track corrections passed
independent review and common adoption, followed by the one-room confirmation
described above. This is not universal position or queue proof. See
[bounded position findings](POSITION-RESTORE.md). Intermittent
audible volume lag remains observation-only, with no speculative change.

## Native UI wording evidence

Frontend `home-assistant/frontend` dev commit
`4c9a05ef5b7d90434a83d1ab53aad032d7c8931c`,
`src/dialogs/more-info/controls/more-info-media_player.ts`, reads the integration's
`source_list` values but renders the source control using the shared
`ui.card.media_player.source` label. The integration supplies values, not a
per-entity heading override. Therefore this adapter keeps standard Source;
it does not rename a shared translation, patch Core/frontend or add a custom
card/select entity. This is pinned upstream source evidence, not an assertion
that a particular household browser runs that dev revision.
