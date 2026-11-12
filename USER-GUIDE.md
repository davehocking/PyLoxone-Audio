# Using the audio players

Install the [matching preview](https://github.com/davehocking/PyLoxone-Audio/blob/main/preview-build/README.md) and complete [Required setup](README.md#required-setup) first.

## Choose music or return to a source

Open your usual Home Assistant room player and use **Browse media**. Available sources come from Loxone; TuneIn is usually under **Radio**. Search and seeking depend on what the player/source supports.

The **Source** selector lists usable previous sources for that room. First choose and play a track or station in Browse; native playback in that room can also supply a previous selection. A folder visit or playback on your phone or another room is not enough. Configured Line-In inputs are directly selectable.

Returning to Spotify or Local Library can restore the remembered track and try its saved position. Position return is best-effort, not a whole-queue guarantee. Bookmarks can be lost after a Home Assistant restart or integration reload; choose content again if the old source is no longer usable. A separate Home Assistant Spotify integration is not required.

## Create or edit a group

Open the room's expanded player (**More info**) and choose **Join** to open **Audio groups**. The media-control card's grouping entry also opens the manager for supported Loxone rooms. If the ordinary picker appears instead, check [frontend setup](https://github.com/davehocking/PyLoxone-Audio/blob/main/preview-build/README.md#frontend).

- **Create Group:** choose at least two free rooms and select **Create**. The first selected room leads. A preselected room can be unticked.
- Select a free room to add it immediately; there is no Apply button.
- **Remove from group** removes that room. Fewer than two remaining rooms dissolves the group.
- **Destroy Group** removes the entire group.

Only Loxone-managed audio rooms are offered. This manager supports dynamic groups on one Audio Server. Group edits can stop playback; wait for confirmation before making another change.

## Which controls affect which rooms?

| Control | Effect |
|---|---|
| Grouped player's standard play/pause or manager's top play/pause | Whole group |
| Room player's standard volume slider or volume up/down | That room only, whether leader or follower |
| Custom manager's **Group volume** slider | Whole group, keeping the rooms' volume balance until a limit is reached |
| Each room row's play/pause or volume | That room only, including the leader's row |
| Leader Browse, Source or supported seeking | Shared group music |
| Follower's **Media controls on <leader name>** link | Opens the current leader's player |

Use the leader to change the group's music. Supported Shuffle/Repeat controls on a follower change the current leader's modes; idle followers get matching native-style buttons without pretending they are playing. Each volume slider occupies its own full-width line, with percentage and −/+ controls above it. Group volume shows the rounded mean of room levels; it is not a command to give every room the same volume. Startup/resume volume behaviour remains native to Loxone. Rapid −/+ taps in the custom manager are combined after a 300 ms pause; wait for confirmation before another operation.

## Automations and troubleshooting

[Automation grouping](AUTOMATION-GROUPING.md) can select the requested leader and rooms. Its optional membership override moves occupied rooms; the interactive picker does not silently steal them.

If something fails, check [Required setup](README.md#required-setup), room availability and the matching backend/frontend versions. For Source errors, first play actual content in Browse; for grouped content, use the leader. If the controls look old, refresh the browser before restarting the backend.

[Report a problem](DIAGNOSTICS.md) · [Known issues](KNOWN-ISSUES.md) · [Install, upgrade or roll back](https://github.com/davehocking/PyLoxone-Audio/blob/main/preview-build/README.md)
