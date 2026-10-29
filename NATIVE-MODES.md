# Native Shuffle/Repeat — inherited 0.1.1 behaviour

> 0.1.2 preserves this feature, not a new source-return/mode correction.
> See [0.1.2 release notes](RELEASE-NOTES-0.1.2.md) and
> [remaining return/position limitations](KNOWN-ISSUES.md). Historical 0.1.1
> acceptance below must not be read as universal 0.1.2 return acceptance.

## What appears in Home Assistant

Open an existing Loxone room's **More info** media-player dialog. Where the
current Audio Server reports support, the normal HA controls offer **Shuffle**
and **Repeat**. Shuffle is on/off; Repeat cycles **Off → All → One → Off**.
The standard icons distinguish the reported modes. Compact Media Control/Tile
cards do not necessarily show extended controls. No custom card, helper switch,
frontend resource or Core patch is installed.

Configure **Audioserver host** and turn on the existing option
**Use Audio Server player play/pause (experimental; off by default)**
(`audioserver_playback`). This option and its default are unchanged. Metadata can
still be received with control disabled. **Audio diagnostics** is a different,
default-off feature, not a prerequisite for mode control.

These are **Loxone player controls, not Spotify controls**. Every action addresses
one exact existing native Audio Server player through the library's current-token
command client. Local Library and any other genuinely capable native source use
the same implementation. There is no Spotify Web API/Connect command, HA Spotify
entity/service, provider credential, binding or provider-derived mode state in
this feature. Existing room identities, configuration and independent bookmarks
are retained. Radio or Line-In labels do not imply support.

## Truthful state and limits

- The exact player's native `plshuffle` and `plrepeat` feedback supplies the
  displayed state, including changes made in Loxone or another controlling app.
  A submitted HA request or successful socket write does not turn the indicator
  on. A validated native reply acknowledges the command; this adapter waits for
  the ordinary exact-player feedback to change its displayed mode.
- Missing, malformed or disconnected state is **unknown**, not a fabricated Off.
  Full native player-state records are replaced rather than merging absent mode
  fields from an older track/session. Announcement events are not queue state.
- Shuffle requires native bit2048, known shuffle state, current ordinary playing
  media, and API >=1.6 / firmware >=16.1.09.23 on the event connection. The command
  connection must independently qualify that greeting before sending an explicit
  enable/disable. There is no fallback to the older no-argument shuffle action.
- Native repeat is **0 Off / 1 All / 3 One**, never2. HA has one REPEAT_SET feature
  and its standard button cycles all three modes. Therefore this adapter exposes
  that button only with known repeat state and **both** native permissions4096
  and8192 on current playing/paused media. Partial repeat support is not advertised
  as a full cycle; a direct HA setter also refuses it. The library's qualification
  helper can check a specifically requested repeat mode for another typed host.
- Support follows current native data, not provider/source-name guesses. Unknown
  permissions and unsupported source records hide the extended control without
  changing existing Miniserver controls. Unknown or older shuffle firmware does
  not disable otherwise-qualified native Repeat.
- Exactly one requested native mode command is sent. No play, source start,
  queue replacement, seek, skip or automatic retry is added. In particular this
  mode-control feature does **not** replace queues or implement source-return
  selection. The separate exact-item return correction is described in
  [EXACT-TRACK-RETURN.md](EXACT-TRACK-RETURN.md).
- A queued request cannot survive loss of its original track/account/context,
  capability, connection, newest-action ownership or entity lifetime while
  authentication is awaited. Existing shared serialization and clean cancellation
  remain. Mode feedback does not alter artwork identity or saved source content.

## Portable API and adapter map

`AudioRepeatMode` and `audio_mode_supported` are public HA-independent exports.
`AudioZoneMetadata.shuffle` is `bool | None`; `repeat` is
`AudioRepeatMode | None`; `shuffle_switch_supported` is connection-qualified
`bool | None`. Only greeting versions are retained, never the session credential.

`AudioServerCommands.async_set_shuffle(player_id, bool, *, is_current=...)` and
`async_set_repeat(player_id, AudioRepeatMode, *, is_current=...)` reuse current
authentication, bounded command-wide timeout, connection serialization and close.
The host must qualify the latest native snapshot and maintain a liveness callback
across awaits. The repeat API rejects bare integers/strings rather than silently
coercing an unknown enum. Setters strictly validate the corresponding native mode
reply. Neither setters nor helpers import Home Assistant or own provider APIs.

The existing AudioZoneV2 entity translates HA SHUFFLE_SET/REPEAT_SET and
`async_set_shuffle`/`async_set_repeat` into those calls. The normal event callback
updates HA attributes. The same policy is used in every mapped room, with no
per-room flags/delays. Strict optional diagnostics add only fixed aliased command
routes and typed mode fields; default-off and all storage/export bounds remain.

## Evidence and remaining acceptance

The maintained tests use synthetic data and real owning HA services, native
RSA/AES authentication and AF_UNIX WebSocket framing with TCP blocked. The all-room
matrix includes Local Library and native Spotify without loading HA Spotify;
additional positive/negative permission controls do not claim physical radio or
Line-In firmware support. Existing mode-control tests remain separate from exact-item source-start tests.
Version-matched frontend function tests exercise HA's real control/icon/cycle
functions using emitted HA entity states, not a replacement player UI.

Independent review and common private HAOS adoption are complete. Actual mode
requests and native mode feedback were observed, but those are not proof of
physical queue behaviour or every rendered frontend control. The ordinary
install/backup/update/rollback route is in
[the preview guide](preview-build/README.md); the maintainer's exact patch and
what/why/test map are in [the review pack](adapters/pyloxone/jo-review/README.md).
