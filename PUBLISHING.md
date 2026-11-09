# Publishing PyLoxone-Audio

The existing `.github/workflows/release.yml` builds and tests source and wheel,
checks strict package metadata, publishes only intentional GitHub releases, then
verifies normal public-index wheel and sdist installation. PR/development builds
do not upload. Keep exact action pins, branch protection and the separate
build/publish/verify-public jobs.

The publisher uses the `pypi` environment's `PYPI_API_TOKEN`; do not retrieve or
print it, put it in source/arguments, or replace the authentication design as part
of an ordinary release. Token publishing is not Trusted Publishing; attestations
remain disabled.

## Release checklist

1. Prepare a clean public-baseline commit with the matching library/adapter pin,
   documentation, preview and baseline-labelled patches. Preserve Apache-2.0,
   notices, credits and established Git identity; exclude operational data.
2. Run [developer checks](CONTRIBUTING-RELEASE.md) on source and the exact wheel,
   validate both distributions with `twine check --strict`, and exercise the
   complete preview install/update/refusal/rollback route.
3. Review the exact commit, require its configured CI checks and use a guarded
   merge. Create fixed tag `v<project.version>` at the tested commit and publish
   the GitHub release. Ordinary pushes cannot upload Python packages.
4. The publisher downloads the tested distributions without rebuilding them.
   Inspect the actual hosted jobs and download those exact artifacts.
5. Require PyPI version/file digests and downloaded bytes to match the hosted
   distributions, plus fresh normal named-pin wheel AND sdist installs with
   dependencies, import paths and runtime bytes verified.
6. Attach the hosted distributions and matching preview/source/checksums to the
   release. Read back exact release/tag/commit/asset identities and file hashes.

Source push, a tag, release creation or a green uploader is not the production
gate. `tools/verify_public_release.py` performs bounded read-only index retries
and retains success/failure receipts. It does not upload or mutate releases.

```sh
python tools/verify_public_release.py --dist /path/to/tested-dist --version 0.1.4 --work-dir /path/to/new-public-check
```

Never overwrite published files, move a tag, delete/re-upload a package or treat
a cached/local wheel as public-index proof. Keep actual release verification
receipts outside source. Publishing does not update existing HA installations.
