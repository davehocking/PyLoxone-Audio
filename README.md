# PyLoxone-Audio

Audio features for [PyLoxone](https://github.com/JoDehli/PyLoxone), using your existing Home Assistant integration and room players.

**Version 0.1.3:** library **0.1.3**, reference adapter **0.10.3.dev18**, frontend **r10**, based on PyLoxone **0.10.3**. Install the matching preview below; Home Assistant resolves `PyLoxone-Audio==0.1.3` through its normal dependency handling. Installing the library alone does not update the integration.

## Start here

- [Install or upgrade](https://github.com/davehocking/PyLoxone-Audio/blob/main/preview-build/README.md), including backup and rollback.
- [Use the players and groups](https://github.com/davehocking/PyLoxone-Audio/blob/main/USER-GUIDE.md).
- [Create groups in automations](https://github.com/davehocking/PyLoxone-Audio/blob/main/AUTOMATION-GROUPING.md).
- [Report a problem](https://github.com/davehocking/PyLoxone-Audio/blob/main/DIAGNOSTICS.md).
- [Maintainer review](https://github.com/davehocking/PyLoxone-Audio/blob/main/adapters/pyloxone/jo-review/README.md).

<a id="required-audio-server-configuration"></a>

## Required setup

In **Settings > Devices & services**, open the existing Loxone entry's configuration/options:

1. Set **Audioserver host** to the Audio Server's hostname or IP address.
2. Enable **Use Audio Server player play/pause (experimental; off by default)** (`audioserver_playback: true`).
3. Save.

Despite its name, that option also enables Browse/Search, source selection and return, supported seeking, Shuffle/Repeat, announcements and enhanced grouping. It uses the existing Loxone authentication; you do not need another integration or a Home Assistant Spotify login. Configure your music accounts in Loxone as usual.

**Audio diagnostics** is a separate, optional switch. It does not enable playback.

## What it adds

- Now-playing information and Browse/Search for supported native sources.
- Previous-source selection with remembered content and best-effort position return.
- Native audio groups through the player's **Join** control, with whole-group and individual-room controls.
- Group music controls on the leader, with a link from followers to the leader's player.
- Grouping actions for automations and optional diagnostic downloads.

See the [user guide](https://github.com/davehocking/PyLoxone-Audio/blob/main/USER-GUIDE.md) for how the controls work.

## Current limits

Previous-source bookmarks are held in memory and can be lost when Home Assistant restarts or the integration reloads. Position restoration and seeking depend on the native source/player; a full queue is not restored. Native startup/resume volume behaviour is unchanged. Group management supports dynamic groups on one Audio Server.

Radio startup delays and room-favourite artwork remain known limitations. See [Known issues](https://github.com/davehocking/PyLoxone-Audio/blob/main/KNOWN-ISSUES.md).

## For developers

The Home Assistant-independent library owns native audio communication and playback state. The adapter connects it to PyLoxone's existing configuration, entities and lifecycle. The preview is a versioned reference for PyLoxone 0.10.3, not files to copy over every future upstream release.

[Maintainer guide](https://github.com/davehocking/PyLoxone-Audio/blob/main/adapters/pyloxone/jo-review/README.md) identifies the patch and files to review. Detailed source maps and developer test instructions are optional references linked there.

## Credits and licence

Built on PyLoxone and its contributors' work. Thanks to Sebastian (@SebastianEitzert) for his contributions. Development is human-directed with LLM assistance.

[Apache License 2.0](https://github.com/davehocking/PyLoxone-Audio/blob/main/LICENSE); existing copyright and [notices](https://github.com/davehocking/PyLoxone-Audio/blob/main/NOTICE.md) are retained.
