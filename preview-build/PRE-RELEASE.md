# 0.1.1 release / PyPI verification checklist

The bundle's original provenance records its offline acceptance stage. Determine
current publication/readiness from the actual PyPI version, matching GitHub
release and final release manifest, not historical `published`/`deployed` flags.
Offline checks alone must never upload/reserve a project or imply public index
resolution.

Before publication (owner authority already exists for 0.1.1; do not add another
generic approval round):

- Freeze exact repository, wheel, sdist, preview and focused Jo pack checksums.
  Prove the reviewed 0.1.1 runtime/API delta, exact wheel RECORD,
  METADATA and source/sdist rebuild equivalence. Document README-only description
  changes separately from stable metadata fields. Preview material must be absent
  from both Python wheel and sdist and present in repository distribution.
- Run portable HA-rejected and owning-adapter suites against source and final
  wheel/0.10.2 assembly with actual imports, blocked sockets and no fake library.
  Retain unchanged official baseline/candidate and external host compatibility
  counts, every inherited warning's cause and all per-case dispositions.
- Exercise the real generated ZIP install/update/rollback and dirty-input refusal
  in synthetic filesystem fixtures. Verify untouched unrelated files/settings.
  Do not label that a physical or HAOS installation.
- Review final caller/lifecycle/provenance/build/install/user/Jo docs with genuine
  independent primary OpenAI same-card independent inspect/run review; retain exact inputs, identity,
  session, verdict and limits outside publishable archives.
- Independently scan allowlisted assets for credentials/household identifiers,
  config/registry/capture/access scripts, private paths and development trees.
  Retain Apache-2.0, upstream/Sebastian credit and accurate human/LLM provenance.
- Verify ownership/availability of the intended project name and account through
  normal public/read-only procedures at publication time. Do not infer it from a
  locally built `Name:` field or publish/reserve a similarly named placeholder.
- Obtain Dave's separate explicit authority for the exact source push/tag/PR and
  package upload/release actions. A developer or reviewer pass is not authority.

After an authorised publication:

- Verify remote source/tag bytes and every uploaded wheel/sdist digest against
  the frozen artifacts. Independently resolve the exact NORMAL named dependency
  from the public index as both wheel and sdist in separate fresh Python 3.14
  environments; import it and
  verify actual version, module paths and declared dependencies. No skip-pip,
  guessed Git dependency or Core patch. Record resolver output honestly.
- Only then change `external_adoption_ready` in a new reviewed release manifest.
  Rebuild/review any changed artifact/checksum. Do not mutate this frozen candidate
  or silently edit PREVIEW.json to imply it was released earlier.
- Test normal HA dependency/setup/update/rollback in an explicitly authorised
  target. Hardware/native-UI acceptance is separate from offline regressions.
  Explain HACS/native update replacement risk and retain exact rollback assets.
- Send Jo the focused current-base patch/file guide, and Sebastian the COMPLETE
  installable preview/docs, only through separately authorised external actions.
