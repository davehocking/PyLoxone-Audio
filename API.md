# PyLoxone-Audio 0.1.4.post1 — API and compatibility

An Apache-2.0 Python library for native audio communication, consumed by the
existing PyLoxone integration. The matching reference adapter is 0.1.4
on stock PyLoxone 0.10.3. See [NOTICE.md](NOTICE.md) for attribution.

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
write is involved. Unknown mode feedback stays unknown. HA maps Repeat Off/All/One to native 0/1/3;
capability and source support govern which controls are available.

## Optional structured diagnostics

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

## Installation and host compatibility

Requires Python >=3.14. Install `PyLoxone-Audio==0.1.4.post1` for standalone consumers.
Home Assistant users need the matching component and frontend described in the
[installation guide](https://github.com/davehocking/PyLoxone-Audio/blob/main/preview-build/README.md); HA installs Python dependencies.
Keep domain `loxone`, existing entries/entities and the exact compatible pin.
Source and installed-wheel checks use synthetic external I/O and real local
WebSocket/crypto boundaries. They do not require household credentials.

## Freshness and host obligations

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
of uninterrupted metadata under arbitrary unusable traffic. See [Known issues](KNOWN-ISSUES.md) for current user-facing limitations.
