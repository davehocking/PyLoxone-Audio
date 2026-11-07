# Audio diagnostics and native Home Assistant tools

For library 0.1.3 and reference adapter 0.10.3.dev18. Start with the
[installation guide](preview-build/README.md).
New users default OFF; existing saved preferences are preserved. Install the
matching adapter/library pair: installing only the wheel does not add the switch.
The event schema remains version1 with an extended fixed allowlist; defaults and
storage/age bounds remain unchanged. The 0.1.3 library and reference adapter add source-independent incident correlation and noise control.
Diagnostics neither enables the Audio Server client nor repairs playback. Set the
Audio Server host and existing experimental playback option separately; see
[Required setup](README.md#required-setup).

Defaults, switch preferences, retention, storage/export bounds and schema version1
remain unchanged. Its narrowly extended allowlist records native aliased
`shuffle/enable|disable`, `repeat/0|1|3`, standard HA `shuffle_set`/`repeat_set`
requests and validated feedback fields `shuffle` (literal boolean) and `repeat`
(`off|all|one`). Unknown mode fields are omitted, never inferred as off; malformed
routes/enums/booleans remain rejected. A command reply does not by itself prove audible playback.
No raw mode payload, credential or provider state is exported.
During a bounded readiness wait, `seek_unsupported` is a
current decision, not proof the source can never seek. A later `eligible` requires
positive capability on the same valid target; a source-transport `timeout` with
`seek_unsupported` means playback was retained without a seek. No historical raw native capability mask can be reconstructed from a false
diagnostic boolean. The report records mask presence, validity and its exact
nonnegative value, distinguishing missing/invalid from a legitimate zero.

## Source-independent incident timelines

These additions apply to every supported source and room, not just TuneIn.
`operation_started` and `operation_finished` bracket the actual owning HA method,
including its final cleanup and validation. Its terminal `outcome` is `returned`,
`error`, `cancelled` or `timeout`; `returned` means the method returned, NOT that
sound was heard. A scoped, keyed `operation_id` links its child commands, while
each native request keeps a distinct keyed `request_id`. Inherited background
tasks cannot keep using an operation after that operation has ended.

Each shared native request records `request`, `lock_acquired`, `connection_opened`,
`authenticated`, `send_attempt`, `send_completed`, `reply`/`source_confirmed` and
`request_finished` after socket cleanup. UTC/monotonic timestamps and `elapsed_ms`
separate preparation, lock wait, connection/authentication, send/response and
cleanup time. Before/after snapshots include known native timing/capabilities,
room volume and eligible group identity/revision/count. `state_published` records
the existing owned HA entity's state event, not browser paint or acoustic output.
No logging hook changes commands, retries, guards, credentials or deadlines.

Routine same-state progress and bookmark records are sampled every30seconds.
An audio action opens a45second higher-detail window, at most one unchanged
sample every0.25seconds per player/transport/event kind. Identity, state, volume,
capability changes and position discontinuities bypass that sampling. Sampler
state itself is bounded. `sampled_routine_records` counts intentional suppression,
not a storage failure. Queue overflow prefers routine loss over command/changed
state loss; `dropped_queue` counts all overflow losses and
`dropped_important_queue` identifies actual important-record loss.

Bounded downloads select newest important command/decision/changed-state records
before routine samples, then return selected rows in their original order.
`export_selection: important_then_recent`, `export_omitted_records` and
`export_omitted_important_records` disclose that policy and any incomplete
selection. This is NOT a guarantee that every journey survives age/disk pressure
or fits one download. A reply can precede a later native or owning-HA failure.

For a slow start, correlate HA entry → native send → native feedback → HA state
publication/return. Note approximate first audible sound separately: none of
these software markers proves the first audible sample. Existing old reports
cannot acquire these new fields retroactively. No new reproduction is requested
by this documentation, and upgrading does not enable collection or private tracing.

## Tester workflow

1. In Home Assistant **Settings > Devices & services > Entities**, filter to your
   Loxone integration entry and find **Audio diagnostics**. It is a diagnostic
   entity, hidden from automatic dashboards, not disabled. Turn it **on**. With
   several entries each has its own switch and independent report.
2. Reproduce the problem through your usual native UI or controlling app. Note
   local time/timezone, the room, source sequence, expected result and what you
   actually saw/heard. Do not repeatedly trigger a failure merely to fill a report.
3. Open **Settings > Devices & services > Loxone**, use the relevant entry's
   three-dot menu and **Download diagnostics**. This uses HA's existing
   administrator-only config-entry diagnostic download, not a new public endpoint.
4. If you enabled collection only for this report, turn **Audio diagnostics off**.
   Otherwise preserve your chosen existing preference. That stops new collection, not the integration
   or playback. No reload, new connection, Core restart, media command or bookmark
   reset occurs when switching it on/off. The explicit setting survives ordinary
   restarts once persistence is confirmed; new installs/upgrades without a valid
   saved setting start **off**. OFF stops emission immediately, before storage I/O.
   Check the switch/report health: `pending_preference` is the latest unconfirmed
   requested bool (or null when confirmed), and `preference_restart_risk` is true
   while pending. `storage_unavailable` plus a sticky `storage_failures` count
   reports failed, mismatched, deferred or cancelled persistence. A successful
   journal flush/export does not clear that pending preference error.
5. Review the downloaded JSON before attaching it to your agreed issue/report
   channel. Nothing uploads automatically. Include the exact version/ZIP hash,
   HA/PyLoxone/library versions, symptom time/timezone, steps and audible versus
   displayed result. Locally match a room to its `room`/`player` aliases if needed;
   do not post original household IDs, private account details or unreviewed
   identifying material.

## HA 2026.11: choose the right evidence

Keep using **Audio diagnostics** and the existing **Download diagnostics** action
for sanitised internal audio evidence. The following native tools supplement it;
they neither replace it nor turn it on. No extra integration, remote-execution
service or automatic upload is installed.

| Question | Supported tool | Important limit |
| --- | --- | --- |
| Why did integration setup or dependency installation fail? | Loxone integration's **Logs** link / **Settings > System > Logs** | Ordinary retained logs; not an audio wire trace |
| Which HA action was called, with what target and context? | **Settings > Tools > Action history** | Depends on Recorder coverage; call/payload is not success |
| Was an internal audio command sent, replied to, or refused? | Opt-in **Audio diagnostics** download | Only collected coverage; reply does not by itself prove final service success or sound |
| What objects are in this running Core? | Already-configured native **Debug console**, administrator only | Full Python execution, not a read-only sandbox; input is logged |

### Native integration logs: retain the normal level

Open **Settings > Devices & services > Loxone**, then the integration page's
three-dot **Logs** link (or use **Settings > System > Logs**). Inspect existing
errors at the incident time first. In this adapter, the supported manifest logger
registration includes `pyloxone_audio` alongside the integration's own logger;
the native integration-scoped log reader/download can therefore include relevant
library warnings. Registration and viewing do **not** change any logger level.
The filter is integration-wide, not a privacy boundary between multiple entries.

In frontend 20261028.4, the integration page's **Show logs** live-dialog button is
inside its **debug logging enabled** banner. Do **not** enable debug merely to
reveal that button. The native log subscription/download itself does not require
DEBUG, but the visible route and available download controls depend on HA's
version and log-reader setup. If the normal screen does not expose a desired
live view, retain the ordinary logs; do not install a replacement log bridge.

**Raw HA logs are not sanitised by Audio diagnostics.** Upstream Miniserver
connection DEBUG logs can include commands/authentication-sensitive material,
and WebSocket DEBUG can expose frames. This workflow does not enable either,
does not claim every third-party warning is secret-free, and does not prescribe
blanket integration DEBUG. Review any native log download independently before
sharing. Changing native logging or its persistence is a separate explicit
operator choice, not the Audio diagnostics switch. Native persistent/once-only
logging settings are also independent of the collector's saved ON/OFF preference.

### Action history: correlate calls, not outcomes

Open **Settings > Tools > Action history**, select the incident interval and
inspect the room's `media_player` action/target. Availability and retention depend
on Recorder and its filters; an empty result is not proof no command was sent.
The native history can contain raw entity IDs, user IDs, action data and context;
it is not copied into the sanitised audio report. Review it before sharing.

In the supported audio report, `ha_service_request.request_id` is an entry-keyed
alias of that HA call's context ID. It is **not** the raw context ID, and internal
Audio Server/Miniserver requests have independently generated IDs. Do not assume
they share one request ID or attempt to export the pseudonym key to join them.
Use incident UTC time, exact locally known room, operation and ordering; preserve
uncertainty when concurrent actions cannot be distinguished. Neither a recorded
HA call nor an internal native reply establishes final owning-service success,
physical playback, or an optional seek. Post-await guards/cleanup can still reject
a service after its reply, with no second low-level error marker.

### Debug console is not part of this workflow

Do not enable a Debug console or run in-process Python to collect this report.
That facility is full execution, not a read-only diagnostic view. This handoff
uses the supported switch/download and ordinary logs; no console setup, raw
capture or logging-level change is required.

### Developer/tester handoff

Record exact Core/frontend/adapter/library versions and the tested artifact hash.
The report's `environment.pyloxone` comes from HA's loaded integration manifest,
not a fixed upstream-base label; it is descriptive metadata, not a source-byte
fingerprint. The outer HA envelope may contain identifying system information.
Retain raw native evidence privately, share only reviewed bounded excerpts, and
keep it separate from the supported sanitised audio report. No automatic upload
or new source/play/seek/group action is performed by any diagnostic tool here.
No external observer is required for the supported diagnostic workflow.

The workflow's regression tests run native log subscription/admin checks,
Recorder Action history/context and an explicitly configured console only in a
disposable network-isolated HA fixture with synthetic data. They do not enable
console/logging/capture on a household, prove deployment, or validate sound.
The existing owning tests continue to cover default OFF, ON/OFF, durable
preference/readback, failed OFF restart risk, age/cap/export bounds, unload and
playback fail-isolation. A failed native setup needs its own recovery; enabling
diagnostics cannot make a missing dependency installable.

## Reading a report and preparing a useful bug report

- Check `enabled` and `status`: `collecting` means the feature was enabled when
  exported. It is independent of the integration's existing experimental
  play/pause option, which gates native Audio Server playback features rather
  than diagnostic recording. Turning diagnostics on does not enable those controls.
- Check `coverage_oldest_utc`, `coverage_newest_utc` and `export_oldest_utc` against
  the incident time. The report cannot reconstruct commands from before collection
  started. A short window immediately after enabling is normal.
- Check `dropped_queue`, `dropped_storage`, `export_omitted_records`,
  `storage_failures` and `observer_failures`. Nonzero counters qualify what can be
  inferred; zero counters do not prove every external/native event was received.
- `complete_24h: false` is deliberately conservative, not by itself a fault.
  Retention is up to 24 hours; it is not a promise of uninterrupted or complete
  reception, and the bounded download may be shorter than the stored window.
- Follow the same request/player/source aliases through `request`,
  `send_attempt`, `send_completed` and `reply` or an error/timeout. Use
  `session_saved` and `restore_decision` to distinguish a missing bookmark, an
  ineligible seek and an actual seek attempt. A `restore_echo` is not proof the
  loudspeaker playback moved; report what was heard separately. An optional seek
  with authentication/error but no `send_attempt`/`send_completed` was not sent;
  do not describe it as a server-rejected dispatched seek. Transient
  `seek_unsupported` and `missing_session` remain [known return limits](KNOWN-ISSUES.md).
- Include the local incident time and timezone, intended room/source, exact
  versions/build, normal UI steps, and expected versus observed behaviour.
  Review the complete JSON before attaching it manually. Do not post private
  room/account mappings, credentials or unrelated raw exports.

Turning collection off preserves unexpired evidence, so a report can also be
downloaded after disabling it. Do not assume `enabled: false` means a retained
timeline is empty. Check the actual event times and collection status instead.

## Retention and limits

Collection continues while on: **24 hours is a rolling maximum record age, not a
collection timeout**. Off retains unexpired evidence for reporting and preserves
configuration. Disabled housekeeping runs approximately every 60 seconds;
export filters expiry too. Timestamps use UTC/elapsed seconds, including DST.
Already expired records are not recovered after restart or a coverage gap.

Preference saves use HA's existing Store and public readback, checking the exact
requested bool and this entry's pseudonym key without exporting the key. The
existing housekeeping writer retries the latest pending request at most once per
60 seconds (monotonic backoff), outside the journal lock. It never replays an old
ON over a newer OFF; closing retires retry ownership. HA stopping/deferred writes
are not treated as durable confirmation. Once storage recovers and save/readback
succeed, pending clears and ordinary `off`/`collecting` health returns. While a
failed OFF remains unpersisted, an actual restart can restore the earlier saved
ON. Storage that cannot write cannot promise durable OFF: resolve the reported
disk/permission problem and confirm pending has cleared before relying on restart.

Per integration entry:

- Queue: at most **256 events**; overflow prefers losing routine rows. If only
  important rows remain, the oldest important row is lost and counted explicitly.
- Sanitised event: at most **2 KiB**; no unbounded raw frames or DEBUG logs.
- Timeline: at most **4 MiB**, in **256 KiB** segments. Size pressure rotates the
  oldest segment, potentially shortening coverage to much less than 24 hours.
- Atomic maintenance reserves at most one additional segment plus bounded counter
  metadata (8 KiB read bound). Preference/pseudonym-key storage is separate and
  tiny. Local files are private, outside web/static paths.
- Export: important-then-recent records within a bounded **1 MiB** audio-report budget. The
  adapter reserves **64 KiB** for HA's separate envelope. HA owns that envelope;
  unusually large platform metadata is not under this integration's control.
  Exports state their omission count rather than promising every retained record.

Coverage oldest/newest times, export oldest time, mapped/omitted room aliases,
expiry/rotation/invalid counts and queue/storage/observer failures accompany the
report. `complete_24h` is conservatively false: a timestamp range is not proof of
unbroken reception. Restarted sequence/monotonic values belong to a new process;
UTC and transport/request/player aliases provide correlation, not unique physical
causality. A reported storage failure warns once with fixed advice to check disk
space/permissions; it never includes exception text or interrupts playback.

File I/O runs in the existing HA executor, through one entry-owned writer and
serial lock. Cancellation waits for an in-progress filesystem operation before
releasing that lock. This cannot cancel a stuck OS filesystem operation. A slow
or full disk can lose diagnostics, not backpressure native playback. Stored
partial/invalid event lines are rejected; atomic replacement preserves preceding
complete records where possible. A report can honestly have no recoverable data.
Startup and ordinary maintenance (even cached/OFF maintenance) discard abandoned
`events-<numeric index>.jsonl.tmp` files with the journal's minimum 16-digit index
and `state.json.tmp`; uncommitted payloads are not evidence. Cleanup never reads
these payloads or follows symlinks, leaves unrelated names untouched, inspects at
most 256 directory entries and removes at most 64 recognised regular temporary
files per operation. Unexpected types, work limits or unlink errors report storage
failure rather than claiming recovery. Successful recovery/rotation restores the
timeline plus one atomic segment and small metadata allowance above; foreign files
or an inaccessible directory cannot be claimed bounded or successfully cleaned.

## What the evidence means

- `ha_service_request` is HA's request event for an exact registered audio entity;
  area/device-only targeting and unrelated controls are not reconstructed.
- `session_saved` samples the actual qualified room/source cache, not Recorder or
  a separately recreated bookmark. `restore_decision` reports the first evaluated
  guard reason, saved/current numeric positions/durations and initial/post-auth
  phase; unevaluated guards are not falsely described as failures.
- Audio Server `request`, `authenticated`, `send_attempt`, `send_completed` and
  `reply` distinguish authentication, the actual existing socket send await and
  a parsed native result. Source confirmation can instead settle from separately
  qualified requested-source feedback. A completed send is **not device execution**.
- `restore_echo` is a numeric native position echo, **not acoustic movement** or
  proof that playback advanced from the requested position. Optional-restore
  failure leaves confirmed source success intact; no retry is introduced.
- Miniserver sends are recorded on its existing connection **only** for discovered
  audio controls and allowlisted play/pause/stop/next/previous/volume operations.
  Encrypted command bytes/authentication remain untouched; no auth envelope enters
  the sink. Relevant numeric volume/play-state feedback is labelled separately
  from Audio Server track/source/position/event feedback and disconnects.

The same opt-in policy covers all AudioZoneV2 players discovered in that loaded
entry; there are no hardcoded household room IDs. Report aliases correlate routes,
player, room, account, content and parent context without exposing originals.
Meaningful non-secret seek numbers and semantic route structure remain exact.
No title, private announcement text, raw house structure, arbitrary frame/error,
credential, cookie, token, password or raw media URL is persisted by this feature.

HA itself adds standard system/custom-integration metadata to diagnostic downloads,
which can include installation/platform/hostname details. That HA-owned envelope
is **not** claimed to be anonymous. Review the actual entire download before
sharing; pseudonymisation of the audio portion is not universal anonymisation.

## Scope and cost

The library supplies no-op-by-default structured events and imports no HA/storage
implementation. The existing adapter owns the switch, preference, local writer
and export. There is no sidecar, second integration, new socket, global debug
setting or automatic upload. Disabled callers skip detailed diagnostic field
construction and queue/file writes; expiry of previously retained data still runs.

Storage and export limits are fixed bounds, not a promise that a busy installation
will retain a full day. Report coverage and omission counters show which interval
is available for a particular incident.
