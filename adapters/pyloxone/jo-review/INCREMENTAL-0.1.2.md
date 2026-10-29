# Incremental adapter: published audio 0.1.1 → 0.1.2

This is NOT a patch against stock PyLoxone and does NOT imply Jo has adopted
0.1.1. Baseline is the AUDIO assembly described by `adapters/pyloxone/BASE.json`
at PyLoxone-Audio commit `222ce5640c56d9168b509a0d5f161ca21b704f14`.
The underlying host is JoDehli/PyLoxone 0.10.2, exact commit
`3db77b81f69c77cc814675d191061533b464df5e`.

| Host file | Delta | Why / owning tests |
|---|---|---|
| `custom_components/loxone/media_player.py` | +12/-0 | Entry-owned opted-in reconciler registration/removal; independent Miniserver PLAYING feedback and stale projected-attribute clearing. `test_metadata_freshness_regression_ha.py`, `test_metadata_reconciliation_ha.py`, `test_metadata_inflight_recovery_ha.py` plus full adapter suite. |
| `custom_components/loxone/manifest.json` | +1/-1 | Change only `PyLoxone-Audio==0.1.1` to `PyLoxone-Audio==0.1.2`, retaining every other requirement/domain/version. Distribution/preview contracts and actual source/wheel imports. |

The larger metadata-coordinator/receiver correction is in the separately
versioned library dependency, not hidden in this small host diff. Both are needed.
No gate/default/configuration/control policy is changed here.

## Reproduce without touching an installation

1. Assemble a NEW synthetic/isolated copy from the exact stock host files plus
   the published 0.1.1 audio overlay. Verify every file against that baseline's
   `assembled_files` map. Do not use an arbitrary installed tree as the baseline.
2. From the assembled root run:

   `git apply --check /path/to/audio-0.1.1-to-0.1.2.patch`

   `git apply /path/to/audio-0.1.1-to-0.1.2.patch`

3. Compare the complete resulting component against THIS revision's BASE.json
   `assembled_files`, including unchanged files. Run source and exact-wheel
   library/owning-HA suites using the documented portable entrypoint.
4. Separately apply `audio-0.1.2-on-0.10.2.patch` to pristine pinned STOCK 0.10.2;
   that result must be identical. This is the cumulative adoption-review path.

These steps are offline preparation, not live install or publication permission.
Use the complete matching preview for later separately authorised testing, not
this patch alone. Known source-return/seek limitations remain in KNOWN-ISSUES.md.
