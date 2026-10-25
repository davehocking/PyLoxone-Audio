# Publishing PyLoxone-Audio

The library publishes as `PyLoxone-Audio`; its Python import is `pyloxone_audio`.
The wheel contains the portable library, not a Home Assistant integration. The
companion adapter and maintained preview stay in this GitHub repository.

## One-time account setup

Use an owner-controlled PyPI account with a verified email and two-factor
authentication. Do not put its password, recovery codes or tokens into this
repository, issues, chat or CI configuration.

The current release uses the owner's PyPI API key, retained in 1Password and
supplied to GitHub as the `PYPI_API_TOKEN` **environment secret** in environment
`pypi`. Only the separate publishing job uses that environment and secret. No
key is placed in source, command arguments or a local plaintext credential file.
The action uses token authentication, not Trusted Publishing; PEP740
attestations are explicitly disabled rather than claiming an OIDC identity.

## Optional future Trusted Publishing

To replace that token with GitHub OIDC, register a Trusted Publisher with the
following fields. Use a pending publisher only while the PyPI project does not
yet exist:

- PyPI project name: `PyLoxone-Audio`
- GitHub owner: `davehocking`
- Repository: `PyLoxone-Audio`
- Workflow filename: `release.yml`
- Environment: `pypi`

The corresponding GitHub environment is also named `pypi`. Trusted Publishing
would remove the need for the stored API token, but is not the current upload
mechanism. Switch the workflow and remove/revoke its token only after OIDC has
been configured and verified. A pending publisher does not reserve the package
name or create a project until its first successful upload.

Official references:
- https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/
- https://docs.pypi.org/trusted-publishers/using-a-publisher/
- https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/

## Release procedure

1. Keep the runtime/API version, adapter compatibility, documentation and tests
   consistent. Preserve attribution, Apache-2.0 and NOTICE.md. Do not copy private
   operational evidence, household settings or the development capture here.
2. Commit the reviewed source. Pushes/PRs run portable source and built-wheel
   tests, package metadata checks and the publishing contract. Adapter acceptance
   must separately run against the exact upstream base listed in
   `adapters/pyloxone/BASE.json`; generic upstream regressions remain external.
3. Review the exact commit and green checks. Create a GitHub release with tag
   `v<project.version>` at that commit. Publishing that release starts the PyPI
   job; ordinary branch pushes and pull requests cannot upload packages.
4. The build job checks the tag against pyproject.toml, tests source, builds a
   wheel and sdist, checks their PyPI metadata and tests the exact wheel without
   source shadowing. It uploads those tested distributions as a workflow artifact.
5. The separate publish job downloads that artifact and uses the protected
   `pypi` environment's API-token secret. It does not check out/build the
   repository. Action revisions are pinned to reviewed commit SHAs. Token
   publishing does not provide a Trusted Publisher identity or PEP740 attestation.
6. Verify the final workflow result and PyPI's version/file metadata. Download
   the actual published wheel/sdist, compare their hashes with the workflow
   artifact and test installation into a fresh isolated Python environment.
   A successful job alone is not package-installation proof.
7. Attach useful source/preview/checksum material to the corresponding GitHub
   release. Verify the actual release assets and preserve immutable version
   provenance. Publishing this package does not merge the adapter upstream or
   update existing Home Assistant installations.

PyPI release filenames cannot be reused for different bytes. Never delete and
re-upload a version as an update procedure; correct a published package with a
new version. Do not recreate tags/releases to make different content appear to
be the same accepted release.

## Local checks

Use a clean isolated Python3.14 environment with the project's runtime
requirements, setuptools, build, twine, pytest, pytest-asyncio, pytest-socket and
PyYAML installed. For the owning-HA suite use its independently provisioned
Home Assistant test environment as described in CONTRIBUTING-RELEASE.md.

```
python -m unittest discover -s tests/release -v
python tools/test_project.py library --work-dir /path/to/new-library-check
python -m build
python -m twine check --strict dist/*
```

No local check authorises household playback or uploading an unreviewed build.
