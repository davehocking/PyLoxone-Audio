# PyLoxone-Audio

A Python library for extending [PyLoxone](https://github.com/JoDehli/PyLoxone) capabilities on the Loxone Audio Server.

PyLoxone-Audio is a separately maintained, testable audio library used through a companion PyLoxone adapter. Home Assistant retains **one integration, one setup and the existing room entities**.

## Version 0.1.0

The 0.1.0 scope covers Audio Server communication, now-playing metadata, playback and source-return behaviour, together with the PyLoxone adapter and tests for both.

Package availability and release-specific compatibility information belong on the [Releases page](https://github.com/davehocking/PyLoxone-Audio/releases). The library version is separate from the PyLoxone integration version; publishing a library package does not itself add support to an upstream PyLoxone release.

## Why a separate library?

Audio communication and playback behaviour are developed and tested independently of Home Assistant-specific configuration and entities. Keeping that work in a library gives it its own tests and releases, while the adapter tests cover its use within PyLoxone. PyLoxone still needs host-side review and compatibility testing when it adopts an adapter or dependency update.

PyLoxone is the main consumer, but the library remains Home Assistant-independent so other Python applications can use it.

This project complements PyLoxone; it is not a replacement for PyLoxone, Home Assistant or Loxone's own applications.

## Architecture and responsibilities

```text
Home Assistant
  └─ PyLoxone: configuration, entities and Home Assistant services
       └─ Audio adapter: translates between the integration and library
            └─ PyLoxone-Audio: native audio communication and playback state
```

**The library** handles audio communication, now-playing and source metadata, playback/source operations, source-return behaviour, and its own connection lifecycle, events and errors. It does not import Home Assistant.

**The PyLoxone adapter** connects the library to the existing integration's configuration, room/player mapping, entities, services, availability and setup/unload lifecycle. It supplies existing authenticated access rather than introducing a second user setup. Non-audio PyLoxone functionality remains the responsibility of PyLoxone.

The adapter is maintained alongside the library in this repository under `adapters/pyloxone/`. It is applied within PyLoxone, not installed as a separate Home Assistant integration. The adapter documentation identifies its supported host base and the matching library version.

The current reference adapter targets released PyLoxone **0.10.2**, exact public commit `3db77b81f69c77cc814675d191061533b464df5e`, with library **0.1.0**. The maintained `preview-build/` directory supplies a complete pinned integration ZIP, provenance/checksums, repeatable build/verification and install/update/rollback/native-UI test instructions. Its focused `adapters/pyloxone/jo-review/` pack is for upstream review; no upstream adoption is claimed.

The adapter uses the library's public interface. Ordinary internal library bug fixes should not require structural adapter changes. New capabilities or intentional breaking API changes may still need coordinated updates.

Home Assistant uses standard media-player entities and controls: **no patched Home Assistant Core or frontend, injected JavaScript/CSS, or project-specific custom card**.

## Audio behaviour

Version 0.1.0 focuses on Loxone Audio Server-backed rooms. Supported sources are **Local Library, Loxone Radio, Spotify, TuneIn and Line-In**, where available and configured in Loxone. Not every installation has every source or subscription. SoundSuit is outside the 0.1.0 scope.

Line-In appears last in the available-source list. Home Assistant's mobile source selector can require scrolling; placing Line-In last keeps the more frequently used sources easier to reach.

The main playback principles are:

- **Confirm the requested source.** A successful native command is followed by fresh now-playing feedback from the correct room identifying the requested source.
- **Respect the active provider.** Spotify keeps ownership of its live session and queue. Returning to a source does not always mean returning to the exact previously played track. Ordinary Spotify transfer uses Spotify Connect.
- **Remember useful last-good state.** Local Library returns to the remembered track where available. Failed or unconfirmed attempts do not erase the last qualified source history.
- **Treat position restoration as an extra.** Where applicable, make at most one bounded best-effort attempt to restore a remembered position. Exact-position proof is not required, and failure of that optional step does not turn confirmed source playback into an error.
- **Avoid surprise playback.** No blind retries, replay or substitute content when an operation cannot be confirmed. Superseded Home Assistant requests and integration unload are handled cleanly.

## Is Home Assistant's Spotify integration required?

**No. Spotify configured in Loxone and Home Assistant's separate Spotify integration are different things.** The library does not depend on Home Assistant, and the PyLoxone adapter does not require HA's Spotify integration to load.

- **Without HA Spotify:** native room controls, now-playing information, source selection and Loxone-backed Browse/Search remain available where configured and supported. That includes Spotify configured in Loxone. Spotify return uses the current native session or qualified remembered content where available; an empty source with no usable session/history needs a selection in Browse or Spotify Connect, not an invented replacement track. Supported native seeking and best-effort position restoration do not require HA Spotify.
- **With HA Spotify and an explicit room/account/device binding:** the adapter can check the authenticated Spotify user and current receiver, then ask **Loxone** to resume that account's existing Spotify session. This can use the live session rather than restarting a remembered track. **It does not seek back to a saved playback position: position remains Spotify's responsibility.** Installing HA Spotify alone does not configure that binding.
- **What this enhancement does not do:** it does not rebuild Spotify's queue, restore a playlist or exact position through Spotify's API, transfer playback from another receiver, or supply Spotify Browse/Search or now-playing metadata. Those are not reasons to install HA Spotify for this project.
- **When the optional evidence is unavailable:** missing/unloaded HA Spotify, unreadable state or no reported session do not by themselves block a valid native return, and do not produce missing-integration warnings. Positive evidence of another account/receiver is a conflict, not permission to silently fall back and take over playback. Ordinary errors and newer-request/lifecycle cancellation still apply.

See [Spotify support and the exact function/API map](https://github.com/davehocking/PyLoxone-Audio/blob/v0.1.0/SPOTIFY.md) for setup fields, active versus retained legacy methods, concrete fallback cases and test coverage.

## Repository layout

The 0.1.0 source tree separates the portable library from its Home Assistant adapter:

```text
pyloxone_audio/       Home Assistant-independent library
adapters/pyloxone/    PyLoxone adapter, host-base information and instructions
preview-build/       Complete pinned integration preview and tester instructions
tests/library/       Portable library tests
tests/adapter/       Audio-adapter and library/host contract tests
```

This repository contains tests for this project and its adapter, not a copy of the full PyLoxone test suite. General PyLoxone connection, authentication, sensor and other non-audio tests belong to the host project and are excluded here. Broader host regression runs are separate compatibility checks, not part of this library's published test suite.

The Python package contains the portable library. The adapter stays separate from that package so installing the library does not install Home Assistant integration files.

## Installation and releases

**For Home Assistant users:** use a PyLoxone build that includes the matching audio adapter. Its manifest pins a tested library version, and Home Assistant installs that dependency automatically. The normal installation unit is PyLoxone; a separate integration or manual `pip` step is not required for a released, compatible pair. The presence of the adapter in this repository does not mean an upstream PyLoxone release already includes it.

The maintained preview targets **PyLoxone 0.10.2 with PyLoxone-Audio 0.1.0**. Before installing it, verify that the exact library version is listed on [PyPI](https://pypi.org/project/PyLoxone-Audio/0.1.0/) and check the matching [release](https://github.com/davehocking/PyLoxone-Audio/releases). A source checkout or preview ZIP alone is not proof of publication. The preview is excluded from both Python wheel and sdist, but retained in the library repository. Its provenance records offline bundle validation; public dependency availability is a separate release check. No upstream adoption or universal hardware/HAOS compatibility is claimed.

**For Python developers:** the library is packaged as a versioned wheel and source distribution, independently of the Home Assistant adapter. Use the artifacts and compatibility information for the selected release. Installing the Python library alone does not add an integration to Home Assistant.

A new library release does **not** automatically update existing PyLoxone installations. Adoption happens when a PyLoxone release selects a tested compatible version, which need *not* be the newest published version. Breaking interface changes need explicit compatibility notes and coordinated adapter updates.

## Testing and compatibility

The project has two test groups:

- **Library tests** cover metadata parsing, playback/source policy, state and timing, communication errors, delayed events, disconnects and cancellation. They run without importing Home Assistant.
- **Adapter tests** exercise the audio library within the owning PyLoxone/Home Assistant paths, including room mapping, native entity behaviour, setup/unload, source selection and the library/adapter contract.

Automated tests use sanitised fixtures and synthetic transports rather than controlling a household's devices. Real-device checks supplement those tests; passing offline tests is not proof of every device, firmware or audible playback outcome.

Compatibility claims apply to the Python, Home Assistant, PyLoxone and device/firmware versions actually tested. No universal device or legacy Music Server compatibility is claimed.

Detailed development tracing, private rolling captures and household-specific tooling are excluded from the library and adapter deliverables. Ordinary useful runtime warnings and errors remain.

## Contributing

Focused issues, reproducible reports and sanitised test contributions are welcome. Include relevant software/device versions and the expected versus observed behaviour. Keep library tests independent of Home Assistant and adapter tests focused on audio integration behaviour; general PyLoxone tests belong with PyLoxone.

**Do not post passwords, tokens, credentials or unredacted device exports.** Remove household-specific information from logs and fixtures before sharing them.

## Acknowledgements and licence

This independent project builds on work from [PyLoxone](https://github.com/JoDehli/PyLoxone) and its contributors. It does not imply official affiliation with Loxone or upstream approval of unreleased changes.

Thanks also to [Sebastian (@SebastianEitzert)](https://github.com/SebastianEitzert) for his contributions to this project.

Development is human-directed, with LLM assistance for drafting and implementation under supervisory review.

Licensed under the [Apache License 2.0](LICENSE), matching PyLoxone. Relevant upstream copyright, attribution and notice requirements are retained when code is reused.
