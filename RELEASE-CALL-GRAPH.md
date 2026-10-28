# 0.1.1 current call graph

**Current 0.1.1.** The current source path is HA media-player selection →
`selection.async_source_route` → native no-op/resume or `catalogue.async_source_return`
→ `sources.async_select_catalogue` → authenticated native command → fresh qualified
source feedback → at most one optional native seek. Qualified native room
observations can seed retained previous content without an HA play request.
Neither provider session/OAuth bridge nor HA Spotify receiver arbitration remains.
`spotify_continuity.py` retains only read-only historical-uncertainty restoration;
its shared fences are not permission for provider calls. Read SPOTIFY.md for the
function-by-function active map and POSITION-RESTORE.md for exact limitations.

The following 0.1.0 call-graph narrative is HISTORICAL. Its optional bridge path
is intentionally retired by 0.1.1; native account/transport/guard ownership remains.

# 0.1.0 release ownership and diagnostic-removal delta

Historical record below: the new default-off0.1.1 diagnostics increment narrowly
supersedes the old blanket module exclusion. `diagnostic_events.py` observes actual
native sends/source guards; `audio_diagnostics.py` owns entry storage/retention,
the native switch and the existing admin download. See DIAGNOSTICS.md. No old
unconditional tracing/failure-summary API or private watcher is restored.

This is the release-cutoff mapping, not a new architecture. Historical extraction
maps remain evidence outside the release assets. The exact file/hash mapping is
in the final release allowlist and release-source-map.json supplied for review.

## Actual owning calls retained

- The existing host setup/config entry still owns one loxone integration and
  entities, OAuth state and unload. audio.py adapts the neutral metadata
  coordinator; pyloxone_api/audioserver.py aliases the concrete native module.
- media_player.py owns entity/newest-request tasks, HA error translation and UI;
  it calls selection's source route/native resume/manual-seek qualification and
  audio_sources' source dispatch wrappers. audio_sources.py injects an immutable
  per-consumer SourceEnvironment clock, not process-wide library mutation.
- catalogue.py owns discovery, configured/native history and catalogue target
  identity; sources.py owns actual dispatch/settlement/strict browse/manual seek
  and source-feedback qualification through native.py. selection.py owns neutral
  reusable route/history/manual-seek decisions, not opaque HA implementations.
- spotify_continuity.py retains HA account/session/liveness/lock ownership and
  supplies the linked-session bridge to spotify.py's concrete resume algorithm.
  The native session remains Spotify-owned; optional position restore is at most
  one best-effort write after source confirmation, not a new progress gate.
- audio_announcement.py retains HA preparation/HTTP ownership and invokes the
  concrete bounded prepared-WAV announcement operation. Models translate at the
  existing host UI boundary; no second integration, entity or frontend is added.

## What was removed, and what was not

The package diagnostics.py and host audio_diagnostics.py are absent, including
public exports, imports, detailed context/snapshot/collector/stage/qualification/
operation machinery, decorators and entity last_source_failure publication.
The diagnostic-only native observation operation label/callback is removed.
No shipped compatibility no-op or relocated diagnostic framework replaces them.

The native on_send callback, observation futures, internal settlement state,
fences, identities, aware clocks,
current credentials, causal state observations, cancellation cleanup and actual
exceptions are functional mechanisms and remain. The decorator's ordinary fixed
warning/HA translation behavior is now explicit in the owning HA action; optional
restore failures retain fixed useful warnings. Exception/provider payloads and
household identity are not interpolated by the new warnings. The AudioZoneV2
constructor's identity-only development debug line is also removed.

SourceEnvironment is now clock configuration and concrete source execution only,
not a diagnostic sink owner. Public SourceDiagnostics/SourceDiagnosticSnapshot/
current_source_snapshot and the diagnostic-only observation label are deliberately
not compatible before the first 0.1.0 release. Real runtime imports and actual
owning HA calls are tested without either development module.
