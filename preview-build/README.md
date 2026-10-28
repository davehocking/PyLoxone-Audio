# Complete pinned PyLoxone 0.10.2 audio preview

## Sebastian / independent tester: start here

Use the matching **complete `PyLoxone-0.10.2-audio-0.1.1-preview.zip`**, its
manifest, checksums and tooling from this revision. A wheel alone does not update
HA or add an integration. This is a version-pinned preview, not an upstream release
or an instruction to contact maintainers.

The matching library and adapter passed independent source and exact-wheel review, and the common pair was installed on Home Assistant OS (Core 2026.10.4, Python 3.14.9). On 28 October 2026 the owner accepted two normal-use Local Library → Spotify returns to the same track near its saved position, supported by integration command and native content/position feedback. This is one-room confirmation, not all-room acoustic, whole-queue, persistent shuffle or restart-recovery proof.

The pair includes native modes, exact remembered-track return and protection
across overlapping Source actions. See [exact-track behaviour](../EXACT-TRACK-RETURN.md)
and [R99 ownership](../adapters/pyloxone/jo-review/R99-TAKEOVER.md). Final release
docs/metadata have new artifact hashes, but runtime matches the accepted installed
pair. Do not substitute an older internal wheel merely because it says 0.1.1.
Previous-source/bookmark memory is RAM-only, not restart persistence.

Prerequisites: the EXACT released PyLoxone **0.10.2** base (BASE.json pins
`3db77b81f69c77cc814675d191061533b464df5e`), Python **>=3.14**, and a normal HA
installation able to satisfy `PyLoxone-Audio==0.1.1` plus the preserved upstream
requirements. Offline source/wheel integration evidence is Python **3.14.7 / HA
2026.9.1**. A private HAOS installation also verified the actual Core **2026.10.4 /
Python 3.14.9** pair, and an owner-enabled diagnostic download has been observed.
These are distinct checks, not an all-HA/all-firmware compatibility matrix.
**Before installation, verify the matching GitHub release/PyPI 0.1.1 and its
production-gate receipts. Normal HA dependency handling must resolve the pin.**
Do not patch HA Core, suppress requirement processing, inject a wheel into a live
HA interpreter or replace another integration. Upstream approval/merge is separate;
a preview can be tested independently once its prerequisites and delivery are met.

The procedure below preserves the existing `loxone` integration/domain, config
entries, settings, entities and the standalone HA Spotify integration. Keep a
full restorable HA backup plus the component rollback receipt. HACS/automatic
PyLoxone updates can overwrite this preview: record that fact and do not silently
reapply an old snapshot over a newer upstream version. No entity/registry reset.

### Exact update and rollback cases

This 0.1.1 tool recognises only no component, exact stock 0.10.2, the **exact
published 0.1.0 preview** (hash inventory in PROVENANCE.json), or this exact 0.1.1
preview. It refuses dirty/unknown versions, extra files and modified receipts.
A fresh component backup made by THIS tool can restore the exact 0.1.0 predecessor;
keep its matching prior tool/receipt too. It does not migrate old receipts between
builds or roll back package caches/config entries. Never force an unknown version
through by deleting files or relabelling the manifest. Parent adoption uses its
existing actual-target/current-base checks, backups and rollback authority.

### 0.1.1 native-UI checklist (only when authorised and prerequisites met)

For a useful report, follow [Audio diagnostics](../DIAGNOSTICS.md): find the
entry's diagnostic entity **Audio diagnostics**, enable it before reproducing,
download through the existing entry **Download diagnostics**, disable it, then
review/attach the report to your agreed channel. Default OFF; explicit choice
persists without reload once save/readback is confirmed. OFF stops emission
immediately; pending preference/restart-risk attributes and storage failure health
warn when it is not yet durable. Housekeeping retries at most once per 60 seconds.
An actual restart before failed OFF persistence recovers can restore the old ON;
see DIAGNOSTICS.md and confirm pending has cleared. The24h window is retention
AGE, not an automatic stop.
Reports are bounded and may cover less; HA's own envelope can contain installation
details. The integration no longer exports raw `LoxAPP3.json` through diagnostics.
This is evidence from enabled collection, not a historical Spotify/seek repair.
The switch/admin download path passed offline checks and actual default-off HAOS
readback; an owner subsequently supplied a live enabled report with actual
send/reply/restore decisions and no reported collection/storage errors. This
does not prove every UI/device branch or that a seek changed audible playback.
Before reporting a bug, check the coverage times and loss/omission/error counters
as explained in DIAGNOSTICS.md; `complete_24h: false` alone is not an error.

Use the normal HA media-player UI and existing room controls.

For this mode increment, first verify **Audioserver host** and **Use Audio Server
player play/pause (experimental; off by default)** are enabled. In the standard
**More info** dialog, check Shuffle's on/off icon and Repeat's Off/All/One icons
against exact-player native feedback; also observe a separately authorised
external/Loxone change. Do not expect every compact card to show extended actions.
Local Library and other actually capable native sources share the same controls;
there is **no HA Spotify entity/auth/binding/API requirement**. Capability/unknown
gates and the full-repeat-cycle requirement are in [NATIVE-MODES.md](../NATIVE-MODES.md).
Do not sound rooms or change their modes merely to complete this guide without
the separately agreed owner test scope. Neither this ZIP nor offline tests proves
live icons, physical mode changes or queue continuity. The separate exact-track
correction covers individual Spotify starts and exact-return qualification.
One-room source-return confirmation does not prove physical mode/queue effects.

The selector heading
is **Source**, not a custom Previous Sources control. Record setup/reload/unload,
ordinary metadata/artwork, play/pause/stop/next/previous/mute and normal volume
response, Browse/Search, supported manual seek, announcements/restoration, and
configured Line-In last. Do not force an intermittent volume fault or act on
other rooms just to populate a checklist.

Only usable previous content for the **same exact room** should be listed, not a
Browse folder visit. First use: **Browse media > Radio** for TuneIn, **Local
Library**, **Loxone Radio**, or **Spotify · your account**; choose and PLAY content.
Qualified native/Loxone/Spotify Connect room playback can qualify without an HA
play request; provider label/title, another room and phone-only playback cannot.
If no usable return target exists it stays unlisted. Any later physical acceptance
must check requested versus observed exact track/account separately from
queue/context, persistent shuffle and audible position. A wrong-track exact
return must fail honestly, retain last-good and send no old-position seek while
showing truthful now-playing. A later explicit return/Browse remains usable.
One conditional
best-effort native seek is retained, not a guaranteed repaired position feature.
For Spotify/Local Library, a confirmed same-track return can wait up to two seconds
for seek support before that one attempt; already-ready tracks do not wait. A new
track/account/action, event, fence, pause or removal cancels the old attempt;
timeout keeps confirmed playback. There are no per-room options. If an authorised
owner test later occurs, record actual audible position separately from command
echoes and source confirmation; do not repeatedly actuate other rooms for coverage.
No optional HA-Spotify bindings/provider access remain; don't disable/delete the
separate HA Spotify entry. Volume lag remains observation-only.

Reports: exact ZIP/library/host/HA/Python versions, install/update/rollback route,
source selected, same-room steps, expected vs observed native UI and audible
outcome, source confirmation vs actual position, reload/lifecycle outcome,
sanitisable ordinary warning/timestamps and rollback result. Remove hostnames,
IPs, UUIDs, account names/IDs, titles you consider private, URLs/tokens and real
config/credentials. No debug payload dumps, login details or private captures.
Report to Dave's authorised handoff channel only after his outreach hold is lifted;
this document is not an instruction to contact Jo or Sebastian now.


This maintained directory contains a complete `custom_components/loxone` ZIP,
not instructions to hand-assemble an adapter. It is for Sebastian and other
external testers and future releases. It is not Dave's private adoption tool.

Base: JoDehli/PyLoxone release 0.10.2, public commit
`3db77b81f69c77cc814675d191061533b464df5e` (not unreleased master).
Library: `PyLoxone-Audio==0.1.1`. Before normal external installation, verify
that exact version on PyPI and obtain this bundle from its matching GitHub
release. Bundle provenance records its original offline validation, not a live
PyPI availability check. A source checkout or ZIP alone is not evidence that
the dependency has been published; do not substitute an unverified package.
No upstream adoption or universal hardware/HAOS compatibility is claimed.

## Contents and reproducibility

* `PyLoxone-0.10.2-audio-0.1.1-preview.zip`: complete integration, Apache-2.0
  LICENSE, NOTICE and embedded PREVIEW.json. No tests/config/registries/private
  evidence/access scripts are in the ZIP.
* `PROVENANCE.json`: exact upstream, adapter BASE.json digest, library runtime
  digests and complete shipping member digests. `SHA256SUMS` covers the ZIP and
  its build/install tooling/provenance. Obtain these files from the same reviewed
  repository archive; checksums do not authenticate an untrusted download.
* `preview.py`: stdlib-only deterministic builder, verifier and guarded
  filesystem installer/rollback. It never downloads packages, starts HA, contacts
  devices, or edits any configuration/registry. Python 3.14 is the tested Python.

Build/verify use Python's standard library. The guarded install/rollback commands
require Linux, libc `renameat2`, and filesystem `RENAME_NOREPLACE` support; they
fail rather than fall back to an overwriting rename. Other operating systems and
filesystems have not been tested. HA must be stopped and editors/updates quiesced.

From the library repository root, supply an extracted copy of the exact official
commit (not a modified integration directory):

    python preview-build/preview.py build --upstream /path/to/PyLoxone-3db77b8 --output /path/to/new-preview.zip
    python preview-build/preview.py verify --archive /path/to/new-preview.zip --sha256 <sha256-from-SHA256SUMS>

The builder checks the entire pinned component base, all adapter inputs and the
unchanged library runtime. Dirty, missing, extra or symlinked component inputs
fail; it does not overwrite an existing output. Generic upstream source files
are not vendored at this library's root. The ZIP is deterministic for the pinned
inputs/toolchain; do not copy the old 0.10.1 overlay over 0.10.2 or later files.

## Dependency installation: normal external use versus exact-wheel testing

Home Assistant reads manifest requirements and installs dependencies before
loading the integration. A failed dependency installation prevents setup.
The unchanged normal manifest names `PyLoxone-Audio==0.1.1`; it must remain so.

For normal external HAOS/Container users, once the exact approved public pin is
available, use the complete preview ZIP and normal HA startup/dependency handling.
There is no separate integration, second login, custom card or manual pip step.
Do NOT patch Core, use global skip-pip, change the manifest to a guessed index or
Git URL, or install into an arbitrary add-on interpreter. An add-on Python import
is not evidence of the Core interpreter/dependency path.

Before public release, developers can test the supplied exact wheel in an
ISOLATED existing HA development/test environment. For example, from this repo,
with an already provisioned Python 3.14 environment containing the declared
dependencies, pytest plugins and HA test dependencies:

    /path/to/test-python -m pip install --no-deps --no-compile --target /path/to/new-isolated-installed /path/to/pyloxone_audio-0.1.1-py3-none-any.whl
    /path/to/test-python tools/test_project.py library --library-root /path/to/new-isolated-installed --work-dir /path/to/new-library-check
    /path/to/test-python tools/test_project.py adapter --library-root /path/to/new-isolated-installed --host-base /path/to/exact-official-upstream --work-dir /path/to/new-adapter-check

`--no-deps` above is ONLY for an already provisioned isolated offline test target;
it is not a HA startup flag or a recommendation to skip dependency installation
on a user's appliance. `actual-imports.json` records the actual package/owning
host locations; `ha-rejected.json` proves the portable tests reject HA imports.
Use a new target/work directory, not a production site-packages directory.
For an isolated HA development runtime, install the exact wheel AND its declared
dependencies with that runtime's normal package manager/interpreter, verify
`importlib.metadata.version('PyLoxone-Audio') == '0.1.1'` and
`pyloxone_audio.__file__` there, and run normal HA requirement/setup checks.
A wheel carrying the same version but different bytes is not this candidate.
This document does not invent a generic unpublished-wheel HAOS installation
procedure; appliance delivery and persistence need their actual runtime path.

Current official references, checked 25 October 2026:
https://github.com/home-assistant/developers.home-assistant/blob/master/docs/creating_integration_manifest.md
https://github.com/home-assistant/home-assistant.io/blob/current/source/_integrations/backup.markdown

## Backup and clean install/update

1. Check the prerequisite above. Record HA/Python/PyLoxone/library/firmware
   versions and the ZIP SHA256. Make a full HA backup using the supported backup
   UI, download it elsewhere, and retain the previous integration and library
   version/wheel. Record existing entity IDs, areas, entry options and source
   lists privately. Do not post a configuration export.
2. Stop HA through your installation's supported controls before replacing files.
   Do not disable/recreate the integration or delete `.storage`/entity registries.
   Backups/config directories used below are placeholders, NOT household paths.
3. On a machine with Python and access to that stopped installation's config,
   from this repository run:

       python preview-build/preview.py install --archive preview-build/PyLoxone-0.10.2-audio-0.1.1-preview.zip --sha256 <verified-ZIP-sha256> --config /path/to/stopped/config --backup /path/outside/config/new-component-backup

   It replaces `custom_components/loxone`, retaining displaced files in a reported
   `.loxone-recovery-*` directory alongside it. Existing unrelated files/settings
   stay untouched. A missing component, exact stock 0.10.2 (without packaged
   tests), the exact pinned published 0.1.0 preview, or this exact 0.1.1 preview is
   accepted. Unknown/other/locally edited trees
   are refused, not overwritten. Reconcile those separately against their own
   verified backup; this is not an evergreen updater. The new backup must be
   outside config and contains the prior component plus an exact before/after
   receipt. Keep it until the preview is accepted.

   Symlinked roots/members/receipts and unsupported private entries are rejected
   without traversing their contents. Only disposable `__pycache__` is omitted.
   Any stat/directory-enumeration error aborts validation; an unreadable directory
   is never treated as an absent or clean component.
   The receipt accepts only absent, exact stock, exact predecessor, or exact candidate trees;
   editing its inventories cannot authorise erasing other changes. Atomic
   no-clobber publication never overwrites a concurrently created component.
   On a failed operation, stop and inspect the reported recovery location and
   verified external backup; do not blindly retry. Restoration is attempted only
   to an absent target. If restoration also fails, both the original (`old`) and
   staged/replacement files remain available. A post-verification failure likewise
   retains the original instead of deleting it during temporary-folder cleanup.
4. Start HA normally. Check logs for normal requirement installation and Loxone
   setup; a Python import in a different interpreter is insufficient. Confirm
   one Loxone integration and existing identities/options. New installation:
   add Loxone once in Settings > Devices & services, using normal Miniserver
   setup. Existing installations: retain the existing entry.
5. In that entry's options, enter the optional Audio Server hostname (no scheme,
   credentials or path) and explicitly enable playback only if desired.
   Native credentials/authentication still belong to the owning Loxone integration.
   HA Spotify is neither required nor consulted by 0.1.1. Its former room-binding
   option is removed and any legacy mapping is ignored, with no automatic edits
   to the independent HA Spotify entry. See [native Spotify support](../SPOTIFY.md).
   Keep existing exact room/player mappings; do not guess or
   duplicate room IDs. Native Miniserver controls remain available when
   optional audio setup fails. Invalid optional configuration must not require
   deleting the integration. Review normal warnings/errors if audio is absent.

HACS/native integration updates can replace a preview, including its audio
adapter; the base version stays 0.10.2, so version text alone is not proof.
Retain the ZIP/checksums/backup, avoid automatic replacement during a planned
test, and explicitly compare hashes before later upgrades. Jo's later merged
upstream files are authoritative: review/rebase the delta, never blindly reapply
whole old files. A new incompatible upstream version must fail this tool's checks.

## Rollback

Stop HA first. Use the SAME repository/tooling and the exact verified component
backup created for that installation:

    python preview-build/preview.py rollback --config /path/to/stopped/config --backup /path/outside/config/new-component-backup

Rollback verifies the current preview tree and backup hashes; it refuses any
intervening file edit instead of erasing it. An originally absent component is
removed; a prior stock or pinned 0.1.0 tree is restored exactly. It does not roll back Python
dependencies/configuration, so also restore the previously recorded compatible
library environment with its normal supported package/runtime mechanism, or use
your full HA backup if dependencies/settings changed. Restart normally and verify
prior integration loading, entities/settings and logs. Do not erase registries to
make counts match. Filesystem fixtures exercise this sequence, not HAOS restore.

Successful swaps also retain the displaced `old` tree in the reported recovery
directory, including any late writes through an already-open editor handle.
Rollback restores the exact component tree, not a byte-for-byte entire config
directory: these explicit recovery folders are intentionally retained. Do not
merge them into the active integration or delete them automatically. Retain them
and the backup through acceptance, then inspect/archive/remove them deliberately
while HA is stopped. This tool never recursively deletes a displaced original.

## Native-UI acceptance and useful reports (owner-operated, never auto-run)

Use the existing native media-player more-info UI. First confirm identities,
areas, configured defaults/limits and normal unrelated controls are preserved.
Check now-playing title/artwork/source and native Source/Browse/play/pause/seek
where supported; no custom card/frontend patch is required. In a safe room at a
chosen volume, use ordinary owner-operated source changes and report expected
versus heard/seen behaviour. Spotify keeps its own session/queue; normal transfer
is Spotify Connect, not HA takeover. Source success requires settled native send
plus fresh exact-room/provider/account requested-source feedback. Saved exact-track
returns require matching track feedback; context-only resumes keep source-level
confirmation. Optional one-shot position restoration is not a source-success gate.
No retry/replay/substitute media should occur on a failed request.

Check unload/reload and an ordinary HA restart during your planned session; note
availability/metadata recovery and unexpected errors. Stop on unexpected sound
or a destructive-looking failure. Do not automate playback/TTS/alarm tests.
Record exact versions/ZIP hash, source sequence, timestamps/timezone, audible and
native-UI outcomes separately, and sanitised warning/error text. Never post
passwords, tokens, account identifiers, household UUIDs, exports or captures.
Offline tests prove software paths only, not firmware/all-room/acoustic coverage.

## Offline filesystem validation

In a provisioned test environment (no HA appliance writes):

```sh
PREVIEW_TEST_UPSTREAM=/path/to/exact/0.10.2 \
PREVIEW_TEST_PREDECESSOR=/path/to/published/PyLoxone-0.10.2-audio-0.1.0-preview.zip \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -c /dev/null -q -p no:cacheprovider checks
```

These fixtures prove exact local file backup/install/update/rollback refusal and
restoration, including published 0.1.0 → candidate → predecessor. They do not prove
HAOS dependency installation, actual config backup restore or physical playback.
See the [maintainer's ordered checklist](../adapters/pyloxone/jo-review/README.md)
and [bounded position findings](../POSITION-RESTORE.md).
