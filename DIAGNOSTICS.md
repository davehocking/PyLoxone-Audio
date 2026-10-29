# Opt-in audio diagnostics — inherited in 0.1.2

This separate, optional feature was introduced in 0.1.1 and is retained unchanged
in the matching 0.1.2 library/adapter pair. New users default OFF; existing saved
preferences are preserved. Installing the wheel alone does not add the HA switch.
The accepted pair is installed locally for testing; public availability is verified
by the matching release and mandatory public-index production gate.
Diagnostics neither enables the Audio Server client nor repairs playback. Set the
Audio Server host and existing experimental playback option separately; see
[Required setup](README.md#required-audio-server-configuration).

Defaults, switch preferences, retention, storage/export bounds and schema version1
remain unchanged. Its narrowly extended allowlist records native aliased
`shuffle/enable|disable`, `repeat/0|1|3`, standard HA `shuffle_set`/`repeat_set`
requests and validated feedback fields `shuffle` (literal boolean) and `repeat`
(`off|all|one`). Unknown mode fields are omitted, never inferred as off; malformed
routes/enums/booleans remain rejected. A command reply is not physical acceptance.
No raw mode payload, credential or provider state is exported.
During a bounded readiness wait, `seek_unsupported` is a
current decision, not proof the source can never seek. A later `eligible` requires
positive capability on the same valid target; a source-transport `timeout` with
`seek_unsupported` means playback was retained without a seek. No prior raw native
capability mask can be reconstructed from a false diagnostic boolean.

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
4. Turn **Audio diagnostics off**. That stops new collection, not the integration
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
   channel. Nothing uploads automatically. Include the exact candidate/ZIP hash,
   HA/PyLoxone/library versions, symptom time/timezone, steps and audible versus
   displayed result. Locally match a room to its `room`/`player` aliases if needed;
   do not post original household IDs or private account details. Do not contact
   maintainers/testers until your own agreed outreach/publication gate is met.

The switch and actual HA admin download handler have been exercised through an
offline owning-HA harness, then installed and checked on the real HAOS runtime.
An owner subsequently enabled collection and supplied an actual downloaded report
containing send/completion/reply, saved-session and restore-decision evidence.
The supplied report had no storage, observer or queue-loss errors. This validates
that live collection/export journey, not all branches or audible playback.
Menu placement may vary with HA. The private report is not a public fixture.

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

- Queue: at most **256 events**; overflow removes the oldest queued record.
- Sanitised event: at most **2 KiB**; no unbounded raw frames or DEBUG logs.
- Timeline: at most **4 MiB**, in **256 KiB** segments. Size pressure rotates the
  oldest segment, potentially shortening coverage to much less than 24 hours.
- Atomic maintenance reserves at most one additional segment plus bounded counter
  metadata (8 KiB read bound). Preference/pseudonym-key storage is separate and
  tiny. Local files are private, outside web/static paths.
- Export: newest records within a bounded **1 MiB** audio-report budget. The
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

Synthetic HA-harness measurements are retained with this candidate's development
receipts: process CPU deltas, `/proc/self/status` RSS/HWM, event rate, actual journal
bytes and export bytes/time. They are a short synthetic load, not quiet-house or
busy-house measurements, device latency proof, a per-day write forecast, or an
incremental production Core memory estimate. Limits are fixed bounds, not a promise
that a busy installation will retain a full day.

This capability cannot retrieve commands from before enablement or retroactively
diagnose earlier Spotify returns. It changes no source, queue, seek, retry, newest
request, authentication or control policy. Existing independently operated private
rolling observers/watchdogs are neither imported, replaced nor stopped. Their
records are not included in this report, and their settings remain independent.
