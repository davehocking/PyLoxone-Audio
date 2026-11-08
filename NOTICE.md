# Provenance and licence — PyLoxone-Audio

Supplied under Apache-2.0. `LICENSE` retains PyLoxone's Apache License, Version 2.0
verbatim. Preserve the licence, attribution and notices when redistributing.

HA entry ownership, exact-player mapping, current-token callbacks and entity
property delegation are adapted from PyLoxone, maintained by JoDehli and its
contributors. No invented upstream copyright assignment is made.

The native event mapping retains this attribution:

> Event names adapted from SebastianEitzert's Apache-2.0 POC in #523, comment 6251138699. See tests/fixtures/audioserver/README.md for provenance.

The mapping is in `pyloxone_audio/native.py`. The current fixture provenance is
[tests/library/fixtures/audioserver/README.md](https://github.com/davehocking/PyLoxone-Audio/blob/main/tests/library/fixtures/audioserver/README.md);
the path in the original attribution is historical. Native transport/authentication,
metadata, catalogue, radio, source policy and announcement code are derived from
this project's native-audio implementation. HA preparation and UI ownership stay
with the host adapter.

Dave directs requirements, behaviour and normal-use validation. Development and
testing are human-directed with LLM assistance through Hermes and OpenAI models.
This does not transfer upstream ownership or replace the applicable licence.
