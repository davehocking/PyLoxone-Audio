# Known issues and limits

- Previous-source track/context/position bookmarks are held in memory and can be
  lost after Home Assistant restarts or the integration reloads. Play the desired
  content again to create a usable bookmark.
- Source return needs a usable remembered selection. Saved-position restoration
  can be skipped when native seek support is unavailable; exact positions and
  complete queues are not guaranteed. Choose content through Browse if a source
  has no remembered selection.
- Group management supports dynamic groups on one Audio Server. Changing a group
  can interrupt sound; check its room list before applying a change.
- Native startup/resume volume behaviour is unchanged. Check the room volume
  before starting playback rather than assuming a previous listening level.
- Radio startup can be slow and room-favourite artwork can be missing. Allow the
  station to start before repeating a play request.

Use [Audio diagnostics](DIAGNOSTICS.md) to report a problem. Include the incident
time/timezone, versions, normal steps and expected versus observed behaviour.

[User guide](USER-GUIDE.md)
