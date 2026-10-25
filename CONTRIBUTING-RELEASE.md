# Contributor instructions for the local 0.1.0 candidate

Preserve Apache-2.0 LICENSE, NOTICE.md and upstream authorship; disclose human/LLM
provenance honestly. This is a separately versioned concrete library consumed by
one existing PyLoxone integration, not another entity/setup path or facade.

API.md describes ownership and host obligations. A compatible internal library
fix should not restructure the adapter. New capabilities/API breaks require an
explicit version/adapter decision. Detailed development tracing is not part of
0.1.0 and must not be reintroduced via no-op compatibility or another module.
Keep fixed useful warnings; never log tokens, payloads or exception bodies.

Build in a clean allowlisted source directory, with available setuptools:
    python -c 'import setuptools.build_meta as b; b.build_wheel("dist"); b.build_sdist("dist")'
No build/twine or global installation is required. Do not build from an operational
evidence workspace or include capture, history, protected paths or credentials.
For deterministic container bytes use SOURCE_DATE_EPOCH=1792886400, umask 022,
0644 source files and normalised tar/gzip timestamps/owners/modes. The local
release receipts record the exact builder and independent rebuild comparison;
the bare backend command alone does not promise deterministic tar/gzip headers.

Use the portable tools/test_project.py entrypoint, running the two suites separately:
    python tools/test_project.py library --work-dir /short/user-owned/library-check
    python tools/test_project.py adapter --host-base /path/to/exact-host-base --work-dir /short/user-owned/adapter-check
The external host base must match adapters/pyloxone/BASE.json; only its listed
custom_components files are needed. Do not substitute another branch or snapshot.
For wheel checks, add --library-root /path/to/fresh-local-wheel-install to either
command. These paths are examples, not dependencies on the development machine.
The runner rejects HA imports for library tests,
blocks TCP, permits local AF_UNIX wire fixtures, treats runtime/resource/unraisable
warnings as errors and records actual package/owning-host import paths. Set TMPDIR
to a short user-owned scratch path. Use fresh work directories; source metadata
is generated locally and temporarily co-located, then cleaned after pytest.

For exact wheel runs use a fresh --no-index --no-deps --target installation and
pass its root with --library-root. Existing dependencies and the HA test plugin
must be supplied by the isolated test environment; no global install or public
dependency-resolution claim follows. The adapter assembles only the exact external
base and scoped overlay in adapters/pyloxone/BASE.json. Keep native/provider
implementations real; replace only external I/O. Preserve per-case identities and
assertions when moving generic host tests to EXTERNAL compatibility evidence or
replacing duplicate native cases with assertion-equivalent portable cases.

The complete installable pinned preview and maintained builder/user instructions
live in preview-build/; its material is excluded from BOTH Python wheel and sdist.
The repository archive includes it. The broad generic host compatibility tests,
historical/private receipts, capture/history and operational deployment scripts
are not this repository. The Jo review pack is adapters/pyloxone/jo-review/.
Parent-supervised adoption is authorised separately, not performed by this worker.
No test result grants public publication or agent household-control permission.
