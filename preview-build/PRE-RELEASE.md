# 0.1.2 release gates and build-time provenance

This publication snapshot preserves the independently accepted 0.1.2 runtime,
already installed locally for testing. Independent engineering and release-
preparation reviews are complete. Embedded `published`, `deployed` and
`external_adoption_ready` FALSE flags describe archive creation, not later public
availability or the accepted runtime's existing installation. A separate final
release verification manifest records hosted/PyPI/public-index acceptance.
Historical accepted/released files remain unchanged.

Required gates for owner-authorised publication:

1. Freeze reviewed source, wheel, sdist, complete preview and focused host patch.
   Verify runtime bytes, RECORD/METADATA, pristine rebuild and sdist-rebuilt wheel.
   Preview/host material must remain excluded from library wheels/sdists.
2. Run complete portable HA-rejected and owning-HA suites against source and the
   exact wheel, with genuine imports, blocked external sockets, unchanged inputs,
   warning gates and complete inherited case/outcome parity. Preserve all REDs.
3. Exercise the actual generated preview in synthetic install/update/rollback,
   predecessor, race, symlink and dirty-input/refusal controls. That is not HAOS
   installation or a production backup restore.
4. Obtain a fresh independent OpenAI review of the exact candidate and evidence;
   implementation tests are not self-approval. Parent acceptance remains separate.
5. Verify licences/credit/privacy against an explicit publication allowlist. Keep
   private diagnostics, household identifiers, access helpers, artifacts/evidence
   and local policy files outside public source. Honour current owner wording.
6. Obtain separate exact publication/deployment authority. This document and green
   tests grant no push/PR/tag/release/PyPI/comment or household action authority.

After authorised publication, read back remote source/tag and downloaded artifact
bytes; prove the NORMAL public-index named 0.1.2 pin resolves as wheel AND sdist
with dependencies in fresh environments. Verify actual imports/runtime/digests,
not metadata availability alone. Never weaken the normal manifest requirement,
patch Core or substitute a Git/private dependency. Record genuine install status
in a successor manifest rather than rewriting sealed historical provenance.

Any later HA update must deliver the MATCHED 0.1.2 library and adapter, preserve
entries/IDs/credentials/options, use supported backups/restarts and verify the
actual runtime. Physical/native-UI acceptance, ordinary control preservation and
fresh-current-track recovery remain distinct from offline or deployment proof.
Outreach to maintainers/testers is separately controlled, not auto-run by this pack.

## Publication sequence — separately verified external state

- Obtain Dave's explicit source/PR/release/PyPI authority; outreach and issue
  updates remain separately approved. Freeze the independent release verdict.
- Refresh authenticated main/issue/release/PR state. Reconcile concurrent owner
  docs without overwriting it, including the current issue #2 wording/hold.
- Publish only the allowlisted candidate via an approved branch/PR and verify
  exact-head required CI. No workflow dispatch is needed to simulate a release.
- After authorised merge, tag the exact reviewed commit as `v0.1.2`; never move
  tags or replace existing files. An intentional PUBLISHED release triggers
  `.github/workflows/release.yml`; a draft or ordinary PR must not upload.
- Require build/source/exact-wheel/strict-Twine, upload and `verify-public` success.
  Use HOSTED tested wheel/sdist as the authoritative release distributions.
  Local/container-only sdist differences must be disclosed; do not attach an
  untested same-version rebuild in place of the actual uploaded artifact.
- Download public source/tag/assets and actual PyPI wheel/sdist. Verify complete
  runtime/dependency/import/RECORD digests against the tested workflow artifact.
  Fresh NORMAL public-index named-pin wheel AND sdist installs are mandatory.
- Record a new final verification manifest; only then change availability text
  and separately approved issue/outreach drafts. Do not rewrite historical seals.

The existing workflow and production gate remain unchanged. Local strict Twine,
preview filesystem tests and local named-pin installs do not substitute for
hosted CI or public-index acceptance. Remaining return/position cases in
KNOWN-ISSUES.md must not be silently closed with the metadata issue.
