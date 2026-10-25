# PyLoxone-Audio

A Python library for extending [PyLoxone](https://github.com/JoDehli/PyLoxone) capabilities on the Loxone Audio Server.

The aim is to provide a separately maintained, testable audio library that PyLoxone can use while keeping **one Home Assistant integration, one setup and the existing room entities**.

> **Development draft**
>
> This repository currently contains project documentation and the licence. A development implementation is being prepared for separation into the library, but the portable package, public API and PyLoxone adapter are still in progress. This is not yet a supported installation for ordinary users. Features below describe the intended design, not capabilities already released from this repository.

## Why a separate library?

Audio communication and playback behaviour should be developed and tested independently of Home Assistant-specific configuration and entities. A library gives those responsibilities a clear home without creating another integration that users have to install and configure.

PyLoxone is the intended first consumer. The library itself is intended to remain Home Assistant-independent, so other Python applications could use it in future.

This project complements PyLoxone; it is not a replacement for PyLoxone, Home Assistant or Loxone's own applications.

## Architecture and responsibilities

The planned boundary is:

```text
Home Assistant
  └─ PyLoxone: configuration, entities and Home Assistant services
       └─ Audio adapter: translates between the integration and library
            └─ PyLoxone-Audio: native audio communication and playback state
```

**The library** handles audio communication, now-playing and source metadata, playback/source operations, source-return behaviour, and its own connection lifecycle, events and errors.

**The PyLoxone adapter** handles Home Assistant configuration, room/player mapping, entities, services, availability and integration setup/unload. It supplies existing authenticated access through an agreed interface rather than introducing a second user setup.

The public interface should stay small and stable. Ordinary internal library bug fixes should not require structural adapter changes. New capabilities or intentional breaking API changes may still need coordinated updates.

The intended Home Assistant experience uses standard media-player entities and controls: **no patched Home Assistant Core or frontend, injected JavaScript/CSS, or project-specific custom card**.

## Intended audio behaviour

The initial focus is Loxone Audio Server-backed rooms. Source handling is planned for **Local Library, Loxone Radio, Spotify, TuneIn and Line-In**, where available and configured. Not every installation has every source or subscription. Line-In should appear last in the available-source list.

The main principles are:

- **Confirm the requested source.** A successful native command must be followed by fresh now-playing feedback from the correct room identifying the requested source. An unrelated metadata update is not confirmation.
- **Respect the active provider.** Spotify keeps ownership of its live session and queue. Returning to a source does not always mean forcing an exact historical track to play.
- **Remember useful last-good state.** Failed or unconfirmed attempts must not erase the last qualified source history.
- **Treat position restoration as an extra.** Where applicable, make at most one bounded best-effort attempt to restore a remembered position. Do not require proof of an exact position or turn confirmed source playback into an error because that optional step failed.
- **Avoid surprise playback.** No blind retries, replay or substitute content when an operation cannot be confirmed. Superseded Home Assistant requests and integration unload must still be handled cleanly.

Device feedback is not proof that sound was physically audible; hardware testing remains a separate part of validation.

## Installation and releases

**For Home Assistant users:** once the library and adapter are integrated, the normal route should remain installing or updating PyLoxone. PyLoxone will pin a tested library version in its manifest, and Home Assistant will install that dependency automatically. No separate integration or manual `pip` step should be needed.

**For Python developers:** versioned package distribution through PyPI is planned. Installation commands and API examples will be added when a testable package is available; they are deliberately not advertised yet.

A new library release will **not** automatically update existing PyLoxone installations. Adoption happens when a PyLoxone release selects a tested compatible version, which need not be the newest published version. Breaking interface changes will need explicit compatibility notes and coordinated adapter updates.

## Testing and compatibility

This repository is intended to host the library source, portable tests, documentation and release history. The test suite and CI workflows have not yet been published here.

Planned coverage includes:

- Metadata parsing, state handling and source-return behaviour.
- Synthetic communication tests for success, errors, delayed events, disconnects and cancellation.
- Library/adapter contract tests, with Home Assistant integration tests accompanying the host-side changes.
- Real-device checks alongside reproducible offline tests.

Supported Python, Home Assistant, PyLoxone and device/firmware versions will be documented from tested evidence. No universal device or legacy Music Server compatibility is claimed.

## Roadmap

- [ ] Complete and validate the simplified source-return behaviour.
- [ ] Extract the Home Assistant-independent library and define its public interface.
- [ ] Build and test the PyLoxone adapter.
- [ ] Publish reviewed source, tests, CI and compatibility documentation.
- [ ] Release a versioned package and propose a tested PyLoxone dependency update.

## Contributing

Focused issues, reproducible reports and sanitised test contributions are welcome. Include relevant software/device versions and the expected versus observed behaviour.

**Do not post passwords, tokens, credentials or unredacted device exports.** Remove household-specific information from logs and fixtures before sharing them. Developer setup and test commands will accompany the published implementation.

## Acknowledgements and licence

This independent project builds on work from [PyLoxone](https://github.com/JoDehli/PyLoxone) and its contributors. It does not imply official affiliation with Loxone or upstream approval of unreleased changes.

Development is human-directed, with LLM assistance for drafting and implementation under supervisory review.

Licensed under the [Apache License 2.0](LICENSE), matching PyLoxone. Relevant upstream copyright, attribution and notice requirements will be retained when code is reused.
