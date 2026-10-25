# Jo: focused 0.10.2 audio adapter review

Base is the released public tag 0.10.2 / commit
`3db77b81f69c77cc814675d191061533b464df5e`, NOT unreleased master.
`audio-0.1.0-on-0.10.2.patch` is a binary-capable Git patch against that complete
base. Apply it only after verifying BASE.json; review is requested, not assumed.
`FILE-GUIDE.json` lists every actual changed file and its tests/WHAT/WHY. Patch
application is exercised against a fresh exact upstream component and compared
to every assembled file hash; there are no generic fixes claimed as our work.

## Ownership and lifecycle to review

* manifest: exact actual `PyLoxone-Audio==0.1.0`, preserving original dependencies
  and upstream integration version 0.10.2. This library pin is NOT yet uploaded
  to PyPI. Normal external install is contingent on approved public release and
  verified resolution, independent of this offline patch/preview.
* config_flow/const: existing setup/options entry, optional audio host/playback,
  exact room/provider bindings; retain all unrelated upstream settings and TEXT.
  No second integration/login/credential persistence path.
* media_player: existing AudioZoneV2 entity/native controls, public-library
  composition; direct native operations only when opted in, fresh exact source
  confirmation and optional one bounded best-effort position. No blind replay,
  fallback, abandoned explicit Spotify handover or queue takeover. Native UI only.
* coordinator/audio: the original owning entrypoint is UNCHANGED upstream 0.10.2.
  Real platform forwarding constructs audio resources in the entry coordinator.
  Entry background tasks own optional listener scheduling. Unload cancels the
  owning Miniserver listener, unsubscribes callbacks, closes optional command and
  metadata resources before the native API and leaves other entries/services.
  The host supplies current Miniserver credentials/token on demand; library
  transport owns its connection lifecycle, not the integration's auth store.
* audio_sources/spotify_continuity/audio_announcement: HA services, authenticated
  provider access, caller/current-target checks and HA errors remain host-owned;
  portable source/history/selection/announcement/native code is in the library.
  Cancellation propagates, superseded requests do not replay, useful ordinary
  warning/error translation remains. Detailed development tracing is excluded.
* catalogue/radio/native import aliases deliberately preserve actual library
  module identity for existing callers/tests; do not create duplicate transport
  or catalogue implementations. audio_models converts neutral models to native
  HA BrowseMedia. Artwork remains a host HTTP/UI responsibility.

## What is explicitly NOT our delta

The 14 other generic upstream-changed files (including __init__.py, text.py,
WebSocket state handling, generic lighting/climate/cover/sensor fixes) are exact
0.10.2 bytes. No Core/frontend/custom cards, generic fixes, full host copy at
library root, registry reset or new service is part of this contribution.
The only overlaps with old audio delta were const.py and manifest.json; they
were reconciled narrowly. Every accepted library runtime byte remains 0.1.0.

## Test ownership and evidence limits

Project tests/library tests portable runtime with HA imports rejected;
tests/adapter tests the real library/HA audio callers with synthetic I/O. Their
source and final-wheel executions are separate receipts, not additive totals.
`test_host_0102_lifecycle_ha.py` additionally drives actual complete platform
forwarding, TextInput state/set-value, connection-state dispatcher, two owning
entries, audio resource teardown and preserved services. Existing upstream tests
are run unchanged against official baseline and this host; the 1956-case broad
accepted host compatibility suite is retained outside the library repository.
No meaningful accepted assertion is dropped or weakened to port this host.
Unawaited coroutine warnings in original official tests are baseline harness
behaviour, not proof those handlers ran; supplemental explicitly awaited paths
and strict own/external tests distinguish this from product defects.

No household connection, HAOS install, device/firmware matrix, physical playback,
source/PyPI publication, upstream adoption or maintainer approval is claimed.
The worker remains offline; parent independently accepts exact outputs before
any authorised local adoption. Tests are socket-blocked, with AF_UNIX synthetic
wire fixtures. The complete third-party preview and reproducible installation/
update/rollback/report instructions are at ../../../preview-build/.

## Credit and maintenance

Apache-2.0 and upstream authorship remain intact. Thanks to Sebastian
(@SebastianEitzert) for contributions and protocol examples. Dave directs scope,
behaviour and normal-use validation; LLM-assisted implementation is supervised
through Hermes/OpenAI. Independent review is a genuine supplied-text OpenAI run,
not hardware verification. See NOTICE.md for retained attribution. Jo's later
merged upstream code is authoritative; this versioned reference is not a licence
to overwrite intervening upstream work with stale whole files.
