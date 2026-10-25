# PyLoxone-Audio 0.1.0 — local release candidate

A separately installable Apache-2.0 Python library containing the concrete native
audio implementation used by one existing PyLoxone integration. This is not a
second integration, new login, facade-only prototype, published index version or
claim of upstream automatic adoption. See NOTICE.md for attribution/provenance.

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
  return does not require matching an obsolete historical track, and may attempt
  at most one optional best-effort position restore. Optional failure does not
  undo confirmed playback; a fixed warning is emitted, never exception payloads.
- async_source_route and async_optional_native_resume own native/retained routing
  and safety decisions; NativeResumeOutcome, SourceRoute and
  SourceContentRequiredError describe their outcomes. Hosts provide lifecycle/
  newest-request liveness callbacks, snapshot bootstrap and their existing optional
  linked-session bridge. UNAVAILABLE is not permission to ignore changed native
  identity or uncertain writes. No blind fallback, replay or retry is introduced.
- manual_seek_supported, manual_seek_position, native_track_identity,
  ManualSeekQualification and async_seek_track retain strict current-track/manual
  seek capability, account/identity, echo and observed-progress qualification.
- passive_history_eligible and confirmed_library_session own reusable native
  history eligibility. Genuine ordered observed feedback is distinct from intent.
- SpotifySessionBridge, SpotifyNativeSession, NativeSessionUnavailableError and
  async_resume_native_session consume the host's optional existing read-only
  linked Spotify session. Spotify owns session/queue; no queue reconstruction or
  abandoned explicit HA Spotify handover feature is added.
- async_send_prepared_announcement handles prepared bounded WAV bytes through
  the native event operation; the host supplies an existing lazy HTTP session.
- audioserver_uri and parse_audio_events retain their concrete native semantics.

SourceEnvironment(clock=callable) is immutable per-consumer clock configuration.
Pass environment= to source/seek/routing/Spotify functions when injecting a clock.
The callable must return aware UTC datetimes in the metadata.received_at domain.
The default is the library's aware UTC clock, not HA or another consumer's state.
Its async_observed_change method executes the concrete native settlement algorithm;
asyncio deadlines remain monotonic. No process-wide clock replacement is required.

The host retains HA setup/entities/registries/services, newest-request tasks and
unload cancellation, account locks/OAuth storage, error translation, artwork and
HA media/TTS preparation. It must keep liveness checks valid across awaits, drain
owned tasks before teardown and close commands before metadata/token owners.
ManualSeekQualification must be checked against actual current native metadata
and the host revision/duration, not merely a cached UI value. Optional native
completion requires settled dispatch and fresh exact-room/provider/account proof.

## Development tracing excluded

There is no shipped diagnostics module, SourceDiagnostics, snapshot/collector
API, source-stage logger, trace decorator, last_source_failure attribute or
compatibility no-op. Those pre-release development-only interfaces are intentionally
removed before this first 0.1.0 cutoff. Functional native dispatch callbacks,
source/announcement fences, clocks and cancellation remain. Ordinary fixed
warning/error logs and actual exception propagation/HA translation remain.

## Tested boundary and installation

Only the canonical Python 3.14.7 / HA 2026.9.1 / websockets 15.0.1 /
pycryptodome 4.0.1 / aiohttp 3.14.3 environment is exercised here. The metadata
requires Python >=3.14 but is not a wider tested compatibility promise. HA-free
portable runs explicitly reject HA imports. External I/O in tests is synthetic;
AF_UNIX wire tests use actual websocket/crypto implementations with TCP blocked.
No all-version/firmware/room, physical playback or adapter hardware claim follows.

For offline local installation use the supplied exact wheel with --no-index,
--find-links pointing to its local assets directory, and PyLoxone-Audio==0.1.0.
The supplied host manifest pins exactly that version, retaining integration domain
loxone, name PyLoxone and integration version 0.10.2. Existing dependencies must
already be available, or be provided independently offline; --no-deps validates
artifact identity only, not public dependency resolution. No PyPI lookup,
publication, namespace reservation, HA deployment or upstream uptake is implied.
