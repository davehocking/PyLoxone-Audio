# PyLoxone-Audio 0.1.2 — API and compatibility

The 0.1.2 metadata-freshness correction passed independent engineering and
release-preparation review. The matching runtime pair is installed locally for
normal-use testing. Actual publication and sustained physical/UI outcomes are
separate; verify the matching release and production-gate receipts.

A separately installable Apache-2.0 Python library containing the concrete native
audio implementation used by one existing PyLoxone integration. This is not a
second integration, new login, facade-only prototype or claim of upstream automatic
adoption. Public availability is verified separately by the release production gate. See NOTICE.md for attribution/provenance.

## Concrete public API and ownership

The explicit exports in pyloxone_audio/__init__.py are the public API:

- AudioServerCommands(host, current_credentials) owns bounded native command
  authentication, correlation, cancellation, close and uncertain-write fences.
  The callback supplies the current username/token; there is no token persistence.
- AudioServerListener and AudioEventReceiver receive/parse exact-player metadata;
  AudioZoneMetadata is the neutral snapshot. AudioMetadataCoordinator supports
  exact-player subscriptions, optional host task scheduling, start and awaited stop.
- AudioCatalogue(commands, player_id), CatalogueTarget, ConfiguredSource and
  AudioFavourite own discovery, opaque browser targets, last-good source history,
  configured favourites, provider/account qualification and neutral search values.
- MediaNode, SearchResult and MediaKind contain no HA entity or UI dependency.
- async_select_catalogue, async_select_favourite, async_select_radio_station and
  async_native_catalogue_noop own source dispatch, settlement and fresh exact-room
  provider feedback. Browser selection remains strict exact-item proof. Source
  return for a saved exact item requires matching track feedback, and may attempt
  at most one optional best-effort position restore after bounded seek readiness. Optional failure does not
  undo confirmed playback; a fixed warning is emitted, never exception payloads.
- async_source_route owns native/retained routing and safety decisions; SourceRoute
  and SourceContentRequiredError describe its outcomes. Hosts provide lifecycle/
  newest-request liveness callbacks and snapshot bootstrap. There is no HA-provider
  bridge callback. Native identity checks, uncertain-write fences and cancellation
  remain; no blind replay/retry or substitute content is introduced.
- manual_seek_supported, manual_seek_position, native_track_identity,
  ManualSeekQualification and async_seek_track retain strict current-track/manual
  seek capability, account/identity, echo and observed-progress qualification.
- passive_history_eligible and confirmed_library_session own reusable native
  history eligibility. Genuine ordered observed feedback is distinct from intent.
- async_send_prepared_announcement handles prepared bounded WAV bytes through
  the native event operation; the host supplies an existing lazy HTTP session.
- audioserver_uri and parse_audio_events retain their concrete native semantics.

SourceEnvironment(clock=callable) is immutable per-consumer clock configuration.
Pass environment= to source/seek/routing functions when injecting a clock.
The callable must return aware UTC datetimes in the metadata.received_at domain.
The default is the library's aware UTC clock, not HA or another consumer's state.
Its async_observed_change method executes the concrete native settlement algorithm;
asyncio deadlines remain monotonic. No process-wide clock replacement is required.

The host retains HA setup/entities/registries/services, newest-request tasks and
unload cancellation, existing native authentication, error translation, artwork and
HA media/TTS preparation. It must keep liveness checks valid across awaits, drain
owned tasks before teardown and close commands before metadata/token owners.
ManualSeekQualification must be checked against actual current native metadata
and the host revision/duration, not merely a cached UI value. Optional native
completion requires settled dispatch and fresh exact-room/provider/account proof.

## Native modes

`AudioRepeatMode` (OFF=0, ALL=1, ONE=3) and `audio_mode_supported` are public
HA-independent exports. `AudioZoneMetadata` adds nullable `shuffle`, typed
`repeat` and connection-qualified `shuffle_switch_supported` state.
`AudioServerCommands.async_set_shuffle(player_id, bool, *, is_current=...)` and
`async_set_repeat(player_id, AudioRepeatMode, *, is_current=...)` send exactly one
explicit native player request through existing authentication/serialization and
strictly validate its reply. The host qualifies fresh native permissions/state
and maintains its liveness callback; no Spotify bridge/API or optimistic metadata
write is involved. See [NATIVE-MODES.md](NATIVE-MODES.md) for firmware, partial
repeat capability, standard HA mapping and unknown/lifecycle semantics.

## Optional structured diagnostics (new 0.1.1 increment)

`pyloxone_audio.diagnostic_events` defines the version1 fixed-field schema,
`DiagnosticEmitter`, `diagnostics_enabled` and exception-isolating
`diagnostic_event`. `AudioServerCommands(..., diagnostics=None)` and
`AudioMetadataCoordinator.diagnostics` accept an optional observer. Its `enabled`
must be literally true; its synchronous `emit(stage, **fields)` must only enqueue,
never await/write files. Callers gate detailed construction before invoking it.
The emitter allowlists fields/routes and keyed pseudonyms before calling its sink.
Foreign observer exceptions are isolated. Authentication data never enters events.

The HA adapter supplies `EntryAudioDiagnostics`/`RollingJournal`, one diagnostic
switch and the existing admin config-entry download. These are host internals,
not a portable HA/storage dependency or a second integration. Separate HA Store
preference/salt avoids reload-on-options. See [DIAGNOSTICS.md](DIAGNOSTICS.md) for
the supported enable/export workflow, exact bounds and evidence/privacy limits.

This narrowly supersedes the earlier blanket instrumentation exclusion. The old
`pyloxone_audio.diagnostics`, `SourceDiagnostics`, `trace_source_action`, raw
snapshot logging and `last_source_failure` API remain removed, not compatibility
stubs. No source/playback, authentication, fence, clock or retry policy changes.

## Tested boundary and installation

Only the canonical Python 3.14.7 / HA 2026.9.1 / websockets 15.0.1 /
pycryptodome 4.0.1 / aiohttp 3.14.3 environment is exercised here. The metadata
requires Python >=3.14 but is not a wider tested compatibility promise. HA-free
portable runs explicitly reject HA imports. External I/O in tests is synthetic;
AF_UNIX wire tests use actual websocket/crypto implementations with TCP blocked.
No all-version/firmware/room or universal physical playback claim follows from these tests.

For Python consumers, the matching pair pins `PyLoxone-Audio==0.1.2`.
Do not substitute 0.1.1 or infer public availability from version text alone.
The production gate must verify normal public-index wheel AND sdist resolution,
dependencies, imports and runtime digests after publication. Local artifact tests
are not that gate. The matching host manifest pins 0.1.2 while retaining domain `loxone`,
name PyLoxone and integration version 0.10.2. For HA, use the complete matching
adapter/preview and normal host dependency handling, not a manual live pip step.

The matching library and adapter passed independent source and exact-wheel review, and the common pair was installed on Home Assistant OS (Core 2026.10.4, Python 3.14.9). On 28 October 2026 the owner accepted two normal-use Local Library → Spotify returns to the same track near its saved position, supported by integration command and native content/position feedback. This is one-room confirmation, not all-room acoustic, whole-queue, persistent shuffle or restart-recovery proof.

For public availability, use the matching GitHub release, PyPI version and release verification receipts. Source, tag or uploader success alone is not the production gate. Existing Home Assistant installations do not automatically update.

## Intentional 0.1.1 retirement

The optional SpotifySessionBridge, SpotifyNativeSession,
NativeSessionUnavailableError, NativeResumeOutcome, async_optional_native_resume
and async_resume_native_session API and its bridge parameter are removed together
with the HA-only controller. Consumers using those optional interfaces must update
alongside the matching 0.1.1 adapter pin; no compatibility facade silently retains
provider access. The native command/authentication/metadata/Browse/manual-seek API
remains. previous_source_labels is the room-local playable-content view; configured
presence is still source_descriptors, not evidence of selected/played content.
See SPOTIFY.md and POSITION-RESTORE.md for the current function map and limits.

## 0.1.2 freshness and host obligations

`AudioZoneMetadata.has_observation`, receiver per-player meaningful revisions and
`AudioMetadataCoordinator.get`/`set_playing` separate fresh native information
from independently reported activity. The adapter supplies Miniserver PLAYING,
clears withheld projected metadata and owns `async_add_reconciler` registration
and removal. Recovery uses `AudioServerCommands.async_player_status` and the
existing listener's `async_refresh_snapshot`, not a media-control fallback.

Expired active data becomes unknown after 30 seconds or a trustworthy track end.
Recovery is opt-in, serial per entry, >=1 second between starts, <=15 seconds per
read and capped 300-second per-player failure backoff. Exact player, stream,
meaningful-feedback revision, credentials, intent and ownership must still match
before publication. Idle/paused rooms are not polled simply for age. Continuous
empty rows can clear presentation again; useful read publication is not a promise
of uninterrupted metadata under arbitrary unusable traffic. See the full
[freshness contract](METADATA-FRESHNESS.md) and [remaining return limits](KNOWN-ISSUES.md).
