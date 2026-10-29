# PyLoxone-Audio 0.1.2 — 29 October 2026

Metadata freshness and bounded read-only recovery on the current integration.
Independent engineering and release-preparation review is complete. The
publication successor preserves accepted runtime bytes. The release is complete
only after hosted build/publish/verify-public and actual normal public-index
wheel AND sdist acceptance; consult the final release verification receipt.

## New in this patch

Address stale Audio Server title/artwork/progress while preserving independent
Miniserver playback state. Active native data expires after 30 seconds or a
trustworthy track boundary. The existing opted-in native client performs bounded
read-only status recovery, rejecting stale stream/player/authentication/intent
and meaningful-feedback results. Continuing unusable in-flight rows do not veto
a useful delayed result; raw snapshots are not merged or fabricated.

**Library AND matching adapter are required.** Target: PyLoxone 0.10.2 at
`3db77b81f69c77cc814675d191061533b464df5e`, normal requirement
`PyLoxone-Audio==0.1.2`, Python >=3.14. The small incremental host patch assumes
the published 0.1.1 audio adapter: `media_player.py` +12/-0 lines and
`manifest.json` +1/-1 for the pin. The separate cumulative patch targets stock
0.10.2. Neither means Jo has adopted that audio adapter. The broader native fix
remains a separately versioned library dependency, not a large host rewrite.

## Inherited, not new in 0.1.2

Native-only Spotify (no HA Spotify bridge), qualified room-local previous
sources, native Shuffle/Repeat, exact-track/last-good guards, one best-effort
saved-position attempt with bounded readiness, and optional diagnostics are
0.1.1 features retained here. No queue/persistence/grouping feature is added.

## Setup, validation and limits

Set **Audioserver host** and enable **Use Audio Server player play/pause
(experimental; off by default)** (`audioserver_playback: true`). This unchanged
client gate also enables active recovery, Browse/Search, source return, supported
seek/modes and announcements. Diagnostics remains separate, optional/default OFF
for new users; existing preferences are retained.

The accepted runtime pair passed independent source/exact-wheel and owning-HA
engineering review and was installed/parent-verified locally on 29 October 2026.
Offline tests used Python 3.14.7 / HA 2026.9.1; local installed-byte checks used
Core 2026.10.4 / Python 3.14.9. This documentation/package successor preserves
that runtime and passed independent release-preparation review. Neither context
certifies all-room sound, rendered UI, sustained live freshness or firmware cause.

**Remaining return limits:** a missing qualified saved session can select other
content; a transient loss of native seek capability can skip optional position
restoration. One later same-track/saved-position shuffle-ON return succeeded, not
every return. Cause/regression/shuffle attribution remains unproved. See
[KNOWN-ISSUES.md](KNOWN-ISSUES.md) and the canonical
[metadata issue #2](https://github.com/davehocking/PyLoxone-Audio/issues/2).

Use the complete matched [preview and install/update/rollback guide](preview-build/README.md),
[maintainer per-file/baseline guide](adapters/pyloxone/jo-review/README.md),
[API](API.md), [diagnostics workflow](DIAGNOSTICS.md) and
[mandatory production gate](PUBLISHING.md). A package upload never updates an
existing integration automatically. Published/accepted historical files remain
unchanged; publication does not automatically update HA or contact maintainers.
