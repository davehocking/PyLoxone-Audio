# PyLoxone-Audio 0.1.3

Library **0.1.3**, reference adapter **0.10.3.dev18**, frontend **r10**,
based on stock PyLoxone **0.10.3**. This is a matched installation: installing
only the Python library does not replace the Home Assistant component.

## Changes since 0.1.2

- Native audio-group management from room players, with leader/follower controls
  and automation grouping actions.
- Improved source return, exact-track and seek qualification, metadata recovery
  and request/lifecycle ownership safeguards.
- Source-independent optional diagnostics: operation/command timelines, owned HA
  state publication, bounded noise sampling and explicit report omissions.
- Shorter installation, user and maintainer guides. Home Assistant uses the
  normal `PyLoxone-Audio==0.1.3` dependency.

[Install, upgrade or roll back](preview-build/README.md), then set
**Audioserver host** and enable **Use Audio Server player play/pause
(experimental; off by default)** in the existing entry's options. The option also
unlocks Browse/Search, source return, supported seeking, modes, announcements and
enhanced grouping. Audio diagnostics is a separate optional switch, default off
for new users; existing explicit preferences are preserved.

Bookmarks are process-local and can be lost on restart/reload. Return/position
support is source-dependent, does not restore a full queue, and does not change
native startup/resume volume behaviour. Dynamic groups are limited to one Audio
Server. Radio startup and favourite artwork remain known limitations.
See the [user guide](USER-GUIDE.md) and [Known issues](KNOWN-ISSUES.md).

See the [maintainer guide](adapters/pyloxone/jo-review/README.md) for the
versioned adapter interface and [PUBLISHING.md](PUBLISHING.md) for release tooling.
