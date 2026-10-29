# Known issues — 0.1.2

[Issue #2](https://github.com/davehocking/PyLoxone-Audio/issues/2) is the canonical metadata status thread. Version 0.1.2 addresses that defect; publication is complete only after the matching GitHub/PyPI and normal public-index production gate. The owner's issue wording and the distinct source-return limitations below remain authoritative.

## Stale track, artwork and progress (#2)

Confirmed on the released 0.1.1 library/adapter pair: HA could retain older native
metadata while Loxone played other content. The 0.1.2 paired correction clears
expired active metadata and attempts bounded read-only status recovery while
preserving independent Miniserver playing/volume state. Source/exact-wheel and
real owning-HA software tests passed independent engineering review; the accepted
runtime was installed and parent-verified locally for testing. Sustained live
track-change/overnight recovery, sound and rendered UI are distinct acceptance
contexts. Historical missing-frame/network/firmware cause is unproved.
Continued unusable raw frames can make presentation unknown again after a useful
read: no old content or capability is merged into new raw rows.

## Source return is not universally repaired

Local normal-use observations on 29 October 2026 include separate outcomes:

- Without a qualified saved session, returning to a source selected different
  content. A previous displayed track is not proof a usable bookmark was saved.
- A later saved-position return reached the same track near its saved position
  with shuffle ON and subsequent same-track native progress. This bounded success
  does not close the other cases or establish whole-queue continuity.
- Another return reached the right track, but native seek support temporarily
  disappeared during authentication. The optional position send was skipped;
  playback continued from the beginning. No dispatched seek rejection was proved.

The initial content/session issue and intermittent position-readiness issue
remain unresolved; no new source-return fix is included in 0.1.2.
Shuffle causation, firmware cause and version-regression attribution remain
unproved. Track/position return and global shuffle state are separate concerns;
`/noshuffle` on an individual start is not a persistent-mode/queue guarantee.

## Other retained limits

- Bookmarks/history are room-specific and RAM-only, not restored after HA restart.
- Source/seek/mode support depends on configured native accounts and firmware.
  Optional position failure does not undo confirmed source playback; there is no
  blind replay, substitute selection or compensating shuffle write.
- Intermittent audible volume lag is not fixed; grouping/cross-room sessions and
  persistence are not new 0.1.2 features. No universal legacy Music Server support.
- Diagnostics is optional/default OFF for new users. It has bounded coverage and
  omissions; zero failure counters do not prove every frame was received. Review
  the entire HA download before sharing; see [DIAGNOSTICS.md](DIAGNOSTICS.md).

Report expected/observed content and position separately, with exact versions,
incident time/timezone and sanitised diagnostic request/send/reply/decision
stages. Do not post room/account IDs, private titles, tokens, URLs or raw logs.
