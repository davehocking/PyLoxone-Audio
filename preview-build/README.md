# Complete PyLoxone 0.10.2 / audio 0.1.2 preview

## Start here: status and installation unit

This matched **0.1.2 reference preview** addresses stale track/artwork/timing while
native playback continues. Use the matching complete
`PyLoxone-0.10.2-audio-0.1.2-publication-preview.zip`, provenance, checksums and
tooling from this revision. **Both the library and adapter are needed.** A wheel
alone cannot wire independent PLAYING feedback or clear stale HA attributes.

Base: released PyLoxone **0.10.2**, commit
`3db77b81f69c77cc814675d191061533b464df5e`, with normal requirement
**`PyLoxone-Audio==0.1.2`**, Python **>=3.14**. Independent runtime engineering
review used Python 3.14.7 / HA 2026.9.1. The accepted pair is installed locally
(Core 2026.10.4 / Python 3.14.9) for normal-use testing. This new documentation/
package successor preserves runtime bytes and passed release-preparation review.
Verify hosted CI/public-index acceptance separately; sustained live recovery and
all-room sound/UI are not certified by those checks.

Retained 0.1.1/earlier 0.1.2 ZIPs are unchanged historical snapshots, not the
current preview. Their embedded offline statuses describe their build time;
never install them with this revision's provenance/tooling. No further household
update is needed merely for this documentation/package successor. See [release notes](../RELEASE-NOTES-0.1.2.md).

**Before normal external installation, verify the exact package and matching
release have passed the public-index production gate.** Local
exact-wheel and named-pin tests are not a public resolver or HAOS install proof.
Do not patch Core, suppress requirement processing, inject a wheel into a live
interpreter, or substitute 0.1.1 for the 0.1.2 pin. No second integration/login,
HA Spotify bridge, custom card or frontend override is required.

### Required setup

In the existing Loxone entry, set **Audioserver host** and enable **Use Audio
Server player play/pause (experimental; off by default)**
(`audioserver_playback: true`). Despite its narrow label this creates the native
client for active status reconciliation, Browse/Search, source selection/return,
play/pause, seeking, native modes and announcements. This candidate does not
change that option, its default or saved settings. With the option OFF, metadata
remains passive: expired active attributes become unknown, without status reads.
**Audio diagnostics** is a separate optional troubleshooting switch, not a
prerequisite for playback/recovery.

Read [metadata freshness](../METADATA-FRESHNESS.md) for policy and evidence limits,
[diagnostics](../DIAGNOSTICS.md) for sanitised reports, and the
[maintainer checklist](../adapters/pyloxone/jo-review/README.md) for adoption.

## Contents and reproducibility

- The new 0.1.2 ZIP contains complete `custom_components/loxone`, licences/notices,
  contributor notes and embedded `PREVIEW.json`; no household configuration,
  registries, tests, private captures or access scripts.
- `PROVENANCE.json` pins base/overlay/library and every shipping member.
  `SHA256SUMS` covers the new ZIP and companion files. Obtain matching trusted
  files: checksums do not authenticate an untrusted download.
- `preview.py` retains the stdlib-only guarded builder/installer; only its
  pinned archive filename changes for the new successor. It never
  installs packages, runs HA, contacts devices or edits config/registries.
- The retained 0.1.1 ZIP is **historical only** and its bytes are unchanged. Its
  original provenance/tooling belongs to the 0.1.1 release, not this successor's
  current `PROVENANCE.json`. Never verify/install it using this successor's tool.

From the repository root, using the exact unmodified extracted upstream base:

```sh
python preview-build/preview.py build --upstream /path/to/exact-0.10.2 --output /path/to/new-preview.zip
python preview-build/preview.py verify --archive /path/to/new-preview.zip --sha256 <verified-sha256>
```

Outputs must not exist. The builder refuses dirty/extra/missing/symlinked inputs
or mismatched documentation hashes. The full preview is excluded from Python
wheel/sdist; it is not an evergreen overlay for a newer upstream version.

## Backup, install and update (only when separately authorised)

1. Meet the dependency prerequisite above. Record exact HA/Python/base/library,
   ZIP checksum, existing IDs/areas/options/source lists privately. Make a full
   supported HA backup, keep a copy elsewhere, and retain the previous matching
   library environment/wheel and component tooling.
2. Stop HA through its supported controls; quiesce editors and updates. Retain
   the existing `loxone` config entry, credentials, entities and settings. Do not
   delete/re-add the integration or reset `.storage`/registries.
3. On Linux with Python and filesystem access to that **stopped** config:

```sh
python preview-build/preview.py install --archive preview-build/PyLoxone-0.10.2-audio-0.1.2-publication-preview.zip --sha256 <verified-sha256> --config /path/to/stopped/config --backup /path/outside/config/new-component-backup
```

The tool accepts absent component, exact stock 0.10.2 (excluding its packaged
tests), the **exact published 0.1.1 predecessor** pinned in this provenance, or
this exact 0.1.2 candidate. It refuses other/dirty trees rather than destroying
local changes. It no longer labels the older 0.1.0 tree as this build's immediate
predecessor; reconcile unknown versions against their own backup/tooling.

The external backup records exact before/after inventories. Displaced originals
remain in reported `.loxone-recovery-*` directories, including late editor writes.
Symlinked roots/members/receipts, unsupported entries, unreadable enumeration,
modified receipts and concurrent target changes fail closed. Atomic no-clobber
replacement requires Linux libc `renameat2` and filesystem `RENAME_NOREPLACE`;
other OS/filesystems are not verified. If any operation fails, inspect the
reported recovery folder and backup; do not retry blindly or delete originals.

4. Start HA normally, allowing its normal dependency handling. Verify the actual
   Core interpreter's package version/path, loaded entry and unchanged IDs/options;
   an add-on/interpreter import is not equivalent. Existing installations retain
   the existing entry; new installations add Loxone once through normal setup.
5. Verify the **Required setup** options above before enhanced-feature checks.
   Preserve exact room/account/player identities and volume limits. HA Spotify is
   neither needed nor consulted; do not remove an unrelated Spotify integration.

HACS/automatic PyLoxone updates can overwrite the preview; the host version stays
0.10.2, so version text alone does not prove adapter identity. Keep checksums and
backups. Never reapply an old whole-file overlay over newer upstream changes.

## Rollback

Stop HA. Use this same verified tooling and the exact backup created above:

```sh
python preview-build/preview.py rollback --config /path/to/stopped/config --backup /path/outside/config/new-component-backup
```

Rollback refuses intervening edits/changed receipts. It restores the exact prior
component or removes a component originally absent; it does **not** restore Python
dependencies, package caches or config entries. Restore the previous compatible
library through that runtime's supported mechanism, or the full HA backup where
needed. Restart normally and verify entry/IDs/settings/logs. Keep displaced trees
and recovery folders through acceptance; inspect/archive them deliberately, never
merge them into the active component. Filesystem tests are not HAOS restore proof.

## Offline checks and isolated library tests

In an already provisioned Python 3.14 test environment, outside any live appliance:

```sh
python -m pip install --no-deps --no-compile --target /path/to/new-installed /path/to/pyloxone_audio-0.1.2-py3-none-any.whl
python tools/test_project.py library --library-root /path/to/new-installed --work-dir /path/to/new-library-check
python tools/test_project.py adapter --library-root /path/to/new-installed --host-base /path/to/exact-0.10.2 --work-dir /path/to/new-adapter-check
PREVIEW_TEST_UPSTREAM=/path/to/exact-0.10.2 PREVIEW_TEST_PREDECESSOR=/path/to/published-0.1.1-preview.zip PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -c /dev/null -q -p no:cacheprovider checks
```

`--no-deps` is ONLY for provisioned isolated test targets, never live HA startup.
For normal isolated dependency resolution, use the matching local distribution
with its declared dependencies and retain resolver/import receipts; neither this
nor a public package's older receipt proves the 0.1.2 public pin.
Canonical runners block external sockets, verify actual owning imports, preserve
warning gates and record full case identities/input hashes. Use fresh outputs.

## Owner-operated acceptance and remaining limits (not auto-run)

Within a separately authorised room/volume scope, verify setup options first.
Observe normal playback past a track change while PLAYING remains unchanged, then
an ordinary overnight/long-pause wake. HA should show current title/source/time or
honest unknown values, not an indefinitely advancing old track. Recovery must not
start music, select media, seek, alter volume/modes or replace a good bookmark.
Observe current-track recovery separately from physical sound and native UI.

Also check source/Browse/search, exact-track return/optional position, play/pause,
normal volume and native modes retain established behaviour. Use standard native
HA controls, not a custom card. Bookmarks remain RAM-only; queue, persistent modes,
restart continuity and every-room/firmware compatibility are not guaranteed.

For a report, optionally enable **Audio diagnostics**, reproduce normal actions,
download diagnostics, then disable it and check preference/coverage health.
Default OFF; no automatic upload. Review the entire HA envelope and remove tokens,
URLs, household IDs/accounts/titles/IPs and private configuration. Include exact
ZIP/library/base/HA/Python versions, timestamps/timezone, expected/observed track
and timing, reload/cleanup and audible/UI outcomes separately. Offline success is
not physical acceptance or permission to actuate another room, deploy or publish.

A return without a qualified saved session can choose different content. A
temporary loss of native seek support during authentication can skip the optional
position send even after the right track returns. One later same-track/saved-
position return with shuffle ON worked locally, but is not blanket acceptance.
Record those outcomes separately from current-track freshness. No firmware,
shuffle or version-regression cause is established; see [known issues](../KNOWN-ISSUES.md).
