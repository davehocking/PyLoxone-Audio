# Contributor instructions for PyLoxone-Audio 0.1.2

Preserve Apache-2.0 LICENSE, NOTICE.md and upstream authorship; disclose human/LLM
provenance honestly. This is a separately versioned concrete library consumed by
one existing PyLoxone integration, not another entity/setup path or facade.

API.md describes ownership and host obligations. A compatible internal library
fix should not restructure the adapter. New capabilities/API breaks require an
explicit version/adapter decision. Default-off fixed-schema diagnostics
is inherited from 0.1.1; see DIAGNOSTICS.md. Legacy unconditional
private tracing/failure-summary APIs must not be reintroduced as compatibility.
Keep fixed useful warnings; never log tokens, payloads or exception bodies.

Build in a clean allowlisted source directory, with available setuptools:
    python -c 'import setuptools.build_meta as b; b.build_wheel("dist"); b.build_sdist("dist")'
This direct backend command is an alternative artifact build, not the complete
release gate: PUBLISHING.md also requires strict twine checks and public-index
verification. No global installation is needed. Do not build from an operational
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
Further household adoption is a separate phase, not performed by these tests.
No test result grants public publication or agent household-control permission.

## Prepared 0.1.2 scope

Preserve the independently accepted native runtime: this phase changes release
documents, metadata and paired delivery only. The metadata fix is not a promise
that every Spotify return is repaired; see KNOWN-ISSUES.md. The incremental
`audio-0.1.1-to-0.1.2.patch` assumes the published 0.1.1 audio adapter, whereas
`audio-0.1.2-on-0.10.2.patch` applies cumulatively to pinned stock 0.10.2.
Jo has not adopted the former merely because that baseline is supplied.

Use isolated build tooling; never repair the provisioned HA test interpreter
just to add build/twine. `python -m build` plus `twine check --strict` is the
normal distribution path. Pristine-source and extracted-sdist wheel rebuilds
are checked separately. Do not claim byte-identical sdists when gzip/tar metadata
or backend-generated inventories differ. `SOURCE_DATE_EPOCH` and umask 022 must
be set in the actual builder. Exact commands, resolved tools and receipts belong
outside public source, as does the explicit per-file freeze/rationale ledger.
