# Provenance and licence — concrete offline extraction

This local 0.1.0 release candidate is supplied under Apache-2.0. `LICENSE` is copied verbatim from the local PyLoxone repository's Apache License, Version 2.0 file. No package has been published or registered. The library's 0.1.0 metadata and exact local host dependency are not a public index release or installed production change.

The HA entry ownership, exact-player mapping, current-token callback and entity-property delegation are adapted from the PyLoxone integration maintained by JoDehli and its contributors, specifically the sealed `media_player.py`, `audio.py` and `coordinator.py` call graph. Those inspected source files contain no additional per-file copyright notices to remove or replace. This draft does not assign invented upstream copyright ownership.

The original native protocol source retains this attribution, which must accompany any future adaptation of its event mapping:

> Event names adapted from SebastianEitzert's Apache-2.0 POC in #523, comment 6251138699. See tests/fixtures/audioserver/README.md for provenance.

The actual parser/event mapping is now extracted into `pyloxone_audio/native.py`, retaining that attribution. Native transport/authentication, metadata coordination, source policy, radio and catalogue implementations are derived from the immutable accepted source tree identified by `baseline-verification.json` and the extraction provenance receipts. Native announcement ownership and the native read-only-bridge Spotify session selection are also extracted; HA preparation, provider session storage and UI responsibilities stay with the host. Relevant upstream attribution and Apache-2.0 terms are retained; no invented copyright assignment is made.

Historical fake-facade, extraction and operational evidence remains outside release assets. The concrete package exports real native classes and source-policy functions instead. Synthetic fixture provenance is preserved under `tests/library/fixtures/audioserver/README.md` outside the wheel. The older path in the attribution quoted above is historical; the current location applies to this repository and its source archive. Development-only detailed tracing and HA failure-summary publication are excluded from both library and adapter at this cutoff.

Dave directed requirements, behaviour decisions and normal-use validation. Implementation and offline testing were AI-assisted through Hermes with OpenAI primary models; release-cutoff implementation uses gpt-6.1-sol and the independently recorded review uses an actual primary OpenAI invocation. AI assistance is provenance, not an invented human author, a transfer of upstream ownership, hardware certification or a guarantee of defect freedom. Independent review identity and limitations are recorded in release-level evidence, not claimed as a substitute for tests.
