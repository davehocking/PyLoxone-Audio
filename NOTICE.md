# Provenance and licence — PyLoxone-Audio 0.1.2

PyLoxone-Audio 0.1.2 is supplied under Apache-2.0. Published 0.1.0 and 0.1.1 remain
immutable; this 0.1.2 publication preserves the independently accepted runtime. `LICENSE` retains PyLoxone's Apache License, Version 2.0 verbatim.
Actual public availability is established by the matching release production gate.

The HA entry ownership, exact-player mapping, current-token callback and entity-property delegation are adapted from the PyLoxone integration maintained by JoDehli and its contributors, specifically the sealed `media_player.py`, `audio.py` and `coordinator.py` call graph. Those inspected source files contain no additional per-file copyright notices to remove or replace. This project does not assign invented upstream copyright ownership.

The original native protocol source retains this attribution, which must accompany any future adaptation of its event mapping:

> Event names adapted from SebastianEitzert's Apache-2.0 POC in #523, comment 6251138699. See tests/fixtures/audioserver/README.md for provenance.

The actual parser/event mapping is now extracted into `pyloxone_audio/native.py`, retaining that attribution. Native transport/authentication, metadata coordination, source policy, radio and catalogue implementations are derived from the project's accepted extraction and native-audio implementation; public source history preserves the applicable versioned changes. Native announcement ownership remains extracted; the optional HA-Spotify bridge/provider session controller was retired in0.1.1, preserving native Spotify. HA preparation and UI responsibilities stay with the host. Relevant upstream attribution and Apache-2.0 terms are retained; no invented copyright assignment is made.

Historical fake-facade, extraction and operational evidence remains outside release assets. The concrete package exports real native classes and source-policy functions instead. Synthetic fixture provenance is preserved under `tests/library/fixtures/audioserver/README.md` outside the wheel. The older path in the attribution quoted above is historical; the current location applies to this repository and its source archive. New default-off fixed-schema audio diagnostics supersedes the blanket instrumentation exclusion only for this increment; legacy private tracing, household observer/watchdog assets and HA failure-summary publication remain excluded.

Dave directed requirements, behaviour decisions and normal-use validation. Implementation and offline testing were AI-assisted through Hermes with OpenAI primary models; release-cutoff implementation uses gpt-6.1-sol and the independently recorded review uses an actual primary OpenAI invocation. AI assistance is provenance, not an invented human author, a transfer of upstream ownership, hardware certification or a guarantee of defect freedom. Independent review identity and limitations are recorded in release-level evidence, not claimed as a substitute for tests.
