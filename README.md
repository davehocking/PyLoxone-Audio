# PyLoxone-Audio

> **Documentation-only revision `0.1.2.post1`.** This republishes corrected
> package-description text for the 0.1.2 metadata-fix release. Audio code,
> dependencies and the matching 0.1.2 adapter/pin are unchanged; existing
> installations need no update or restart. Original 0.1.2 files remain unchanged.
> A separately named preview refresh updates only documentation and provenance.

> **0.1.2 — metadata freshness and read-only recovery.** The matching library
> and adapter passed independent source/exact-wheel, owning-HA and release-preparation
> review. The accepted runtime is already installed locally for normal-use testing.
> See [release notes](RELEASE-NOTES-0.1.2.md) and the mandatory
> [publication verification gate](PUBLISHING.md). Physical/UI outcomes remain separate.
>
> **Both the library and matching adapter are required.** The host remains
> PyLoxone 0.10.2. No upstream adoption or automatic update is implied.

A Python library for extending [PyLoxone](https://github.com/JoDehli/PyLoxone) capabilities on the Loxone Audio Server.

PyLoxone-Audio is a separately maintained, testable audio library used through a companion PyLoxone adapter. Home Assistant retains **one integration, one setup and the existing room entities**.

## Version 0.1.1

Version 0.1.1 adds native-only Spotify source return, usable room-specific previous sources, opt-in audio diagnostics, native Shuffle/Repeat controls and shared same-track/saved-position return corrections. It covers Audio Server communication, now-playing metadata, playback and source-return behaviour, together with the PyLoxone adapter and tests for both.

The matching library and adapter passed independent source and exact-wheel review, and the common pair was installed on Home Assistant OS (Core 2026.10.4, Python 3.14.9). On 28 October 2026 the owner accepted two normal-use Local Library → Spotify returns to the same track near its saved position, supported by integration command and native content/position feedback. This is one-room confirmation, not all-room acoustic, whole-queue, persistent shuffle or restart-recovery proof.

Package availability and release-specific compatibility information belong on the [Releases page](https://github.com/davehocking/PyLoxone-Audio/releases). The library version is separate from the PyLoxone integration version; publishing a library package does not itself add support to an upstream PyLoxone release.

## Known issues and the 0.1.2 correction

**[Stale track and progress in Home Assistant — #2](https://github.com/davehocking/PyLoxone-Audio/issues/2):** HA can keep showing an old track, artwork or elapsed time while the Loxone Audio Server plays different content. Playing/volume feedback and controls may still work. Confirmed with 0.1.1 and its matching reference adapter; the event-stream cause is still under investigation.

**0.1.2 addresses #2 with a focused metadata-freshness correction.** The paired correction has independent software and release-preparation acceptance and local installed-byte verification; sustained live recovery, rendered UI and all-room sound are not certified by those checks. Issue #2 is the canonical release/status thread. [METADATA-FRESHNESS.md](METADATA-FRESHNESS.md) identifies the tested library/adapter installation unit. Updating a Python package alone does not update the HA adapter.

The issue is the live status/reporting thread; the [0.1.1 release notes](https://github.com/davehocking/PyLoxone-Audio/releases/tag/v0.1.1) and [changelog](CHANGELOG.md) record version-specific changes and limitations. Please review and sanitise diagnostics before sharing; see [DIAGNOSTICS.md](DIAGNOSTICS.md).

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

The reference adapter targets released PyLoxone **0.10.2**, exact public commit `3db77b81f69c77cc814675d191061533b464df5e`, with the matching **0.1.2** library. The accepted runtime pair is installed locally for testing. PyLoxone-Audio **0.1.2 is published on PyPI**, with its matching adapter review package and complete test preview available in the **GitHub v0.1.2 release**. These test/review materials are not a release of upstream PyLoxone. The 0.1.1 owner acceptance above remains bounded historical evidence. The maintained `preview-build/` directory supplies a complete pinned integration ZIP, provenance/checksums, repeatable build/verification and install/update/rollback/native-UI test instructions. Its focused `adapters/pyloxone/jo-review/` pack is for upstream review; no upstream adoption is claimed.

The adapter uses the library's public interface. Ordinary internal library bug fixes should not require structural adapter changes. New capabilities or intentional breaking API changes may still need coordinated updates.

Home Assistant uses standard media-player entities and controls: **no patched Home Assistant Core or frontend, injected JavaScript/CSS, or project-specific custom card**.

## Required Audio Server configuration

**Enable the Audio Server playback option to use this project's enhanced audio
functions through the matching PyLoxone adapter.** Installing the library alone
or entering the Audio Server address does not enable them.

In the existing PyLoxone integration's configuration/options:

1. Set **Audioserver host** to the Audio Server's bare hostname or IP address.
2. Turn ON **Use Audio Server player play/pause (experimental; off by default)**
   (`audioserver_playback: true`). This is the current option label.
3. Save the options before testing the enhanced audio features.

Despite the label, this option enables more than play/pause: the native command
client is also required for Browse/Search, source selection and return,
supported seeking, native Shuffle/Repeat and announcements. With it OFF, the library can still load
and a configured host can supply metadata, but those enhanced functions remain
unavailable. Existing non-audio PyLoxone functionality and Miniserver-only
controls are not disabled.

These instructions describe the current reference adapter. The wording and
configuration approach can be revisited once JoDehli's upstream approach is
agreed; no change of defaults or upstream adoption is implied here.

**Audio diagnostics** is a separate, default-OFF switch: it records existing activity but does not enable playback. All rooms use this same setup and implementation, with independent remembered content and bookmarks.

## Audio behaviour

The 0.1.x feature set focuses on Loxone Audio Server-backed rooms. Supported sources are **Local Library, Loxone Radio, Spotify, TuneIn and Line-In**, where available and configured in Loxone. Not every installation has every source or subscription. SoundSuit is outside this scope.

The standard **Source** selector lists only usable previously selected or played content for that exact room. Qualified native playback observed from Loxone or Spotify Connect can qualify without an HA play request. A folder visit, provider label, another room or phone-only playback cannot. First choose and **play** content in **Browse media > Radio** (TuneIn), **Local Library**, **Loxone Radio**, or **Spotify · your account**. No new history database is introduced. The requested “Previous Sources” wording cannot be set for the standard HA control; its normal **Source** heading is retained.

Configured Line-In inputs remain directly selectable and last. Home Assistant's mobile source selector can require scrolling; placing Line-In last keeps the more frequently used sources easier to reach.

The main playback principles are:

- **Confirm the requested source.** A successful native command is followed by fresh now-playing feedback from the correct room identifying the requested source.
- **Return to qualified content.** A saved exact Spotify or Local Library track must be confirmed as that same track before success. A wrong-track reply leaves the actual now-playing visible and preserves the prior last-good bookmark. Context-only resume has a weaker source-level contract. Ordinary Spotify transfer uses Spotify Connect; complete queue preservation is not guaranteed.
- **Remember useful last-good state.** Failed or unconfirmed attempts do not erase the last qualified source history, including overlapping Source actions. This memory is room-specific and RAM-only: it does not survive an HA restart.
- **Treat position restoration as an extra.** After confirmed Spotify or Local Library return, allow up to two seconds for the same track's native seek support, then make at most one best-effort position attempt. Already-ready tracks do not wait. A changed track, account or active request cancels the old attempt. Every room uses the same policy, with no extra settings. Timeout or optional failure keeps confirmed source playback; exact position is not guaranteed.
- **Use standard Shuffle/Repeat controls.** In the room’s **More info** dialog, supported native players offer Shuffle on/off and Repeat Off/All/One, with state from Loxone feedback. Missing state is unknown, not fabricated Off; not every source or firmware supports these controls.
- **Avoid surprise playback.** No blind retries, replay or substitute content when an operation cannot be confirmed. Superseded Home Assistant requests and integration unload are handled cleanly.

## Is Home Assistant's Spotify integration required?

**No. 0.1.1 removes the optional HA-Spotify provider/session/binding bridge.** Native Loxone Spotify controls, account checks, metadata, Browse/Search, native resume and supported native seeking remain. Legacy bridge options are ignored on normal reload; the separate HA Spotify entry is not modified. There is no Spotify Web API access or new receiver/queue arbitration in this adapter.

Returns use qualified room-native content, not a phone's unrelated selection. Saved exact tracks require matching feedback, and same-track position return has one-room owner confirmation. The whole queue and exact position on every attempt are not guaranteed. Historical raw capability-mask and wrong-track firmware causes remain unproved. Intermittent audible volume lag is **not fixed**.

Remaining source-return cases are not repaired by the metadata fix: a return without a qualified saved session can choose different content, and transient native seek-capability loss can skip optional position restoration. One saved-position return with shuffle ON succeeded locally, but does not close the other cases or prove their cause. See [known issues](KNOWN-ISSUES.md).

See [native Spotify’s function map](SPOTIFY.md), [exact-track return](EXACT-TRACK-RETURN.md), [native modes](NATIVE-MODES.md) and [position-restoration findings](POSITION-RESTORE.md).

## Repository layout

The source tree separates the portable library from its Home Assistant adapter:

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

The maintained preview targets **PyLoxone 0.10.2 with PyLoxone-Audio 0.1.2**. Use its matching complete ZIP and [installation/update/rollback guide](preview-build/README.md), not the wheel alone. Check the matching release and successful public-index production gate before installation; do not use 0.1.1 to satisfy a 0.1.2 pin. Historical releases and preview archives remain unchanged; the assembled integration is excluded from wheel and sdist. Existing locally installed identical runtime needs no repeat install merely for these documentation/package changes.

- **Testers: [start here](preview-build/README.md)** — prerequisites, backup, install/update/rollback, native UI and report checklist.
- **Maintainers: [review and adoption](adapters/pyloxone/jo-review/README.md)** — ordered inspect/reproduce/test/rebase/adopt/release and per-file what/why/tests.
- [Release checklist](preview-build/PRE-RELEASE.md) and [publishing procedure](PUBLISHING.md).

**For Python developers:** the library is packaged as a versioned wheel and source distribution, independently of the Home Assistant adapter. Use the artifacts and compatibility information for the selected release. Installing the Python library alone does not add an integration to Home Assistant.

A new library release does **not** automatically update existing PyLoxone installations. Adoption happens when a PyLoxone release selects a tested compatible version, which need *not* be the newest published version. Breaking interface changes need explicit compatibility notes and coordinated adapter updates.

## Testing and compatibility

The project has two test groups:

- **Library tests** cover metadata parsing, playback/source policy, state and timing, communication errors, delayed events, disconnects and cancellation. They run without importing Home Assistant.
- **Adapter tests** exercise the audio library within the owning PyLoxone/Home Assistant paths, including room mapping, native entity behaviour, setup/unload, source selection and the library/adapter contract.

Automated tests use sanitised fixtures and synthetic transports rather than controlling a household's devices. Real-device checks supplement those tests; passing offline tests is not proof of every device, firmware or audible playback outcome.

Compatibility claims apply to the Python, Home Assistant, PyLoxone and device/firmware versions actually tested. No universal device or legacy Music Server compatibility is claimed.

## Opt-in audio diagnostics

The matching adapter retains the 0.1.1 feature: one **Audio diagnostics** switch per Loxone entry, **OFF by default** and hidden from automatic dashboards. Enable it, reproduce normally, use the entry's **Download diagnostics**, disable it, then review the entire file before sharing. No automatic upload occurs. Toggling does not reload the integration, change playback or discard bookmarks.

Collection continues until switched off, retaining up to the latest **24 hours**, subject to fixed queue/disk/export bounds. Reports explain shortened coverage, omissions and failures. Preference persists once saving is confirmed; if storage fails, inspect pending-preference/restart-risk health before relying on it. Actual sends, replies and restore decisions are distinct from HA requests and physical playback. HA's outer download envelope may include installation details: sanitised audio events do not make the entire file universally anonymous. See [workflow, privacy and limits](DIAGNOSTICS.md).

The owner has used enabled collection and supplied a downloaded report with actual send/reply/session/restore-decision evidence and no reported collector/storage failures. This validates that journey, not every branch or firmware. Private reports, detailed development captures and household tooling remain excluded; useful ordinary warnings/errors remain.

## Contributing

Focused issues, reproducible reports and sanitised test contributions are welcome. Include relevant software/device versions and the expected versus observed behaviour. Keep library tests independent of Home Assistant and adapter tests focused on audio integration behaviour; general PyLoxone tests belong with PyLoxone.

**Do not post passwords, tokens, credentials or unredacted device exports.** Remove household-specific information from logs and fixtures before sharing them.

## Acknowledgements and licence

This independent project builds on work from [PyLoxone](https://github.com/JoDehli/PyLoxone) and its contributors. It does not imply official affiliation with Loxone or upstream approval of unreleased changes.

Thanks also to [Sebastian (@SebastianEitzert)](https://github.com/SebastianEitzert) for his contributions to this project.

Development is human-directed, with LLM assistance for drafting and implementation under supervisory review.

Licensed under the [Apache License 2.0](LICENSE), matching PyLoxone. Relevant upstream copyright, attribution and notice requirements are retained when code is reused.
