"""Native 17.2.2 per-item command parity, not a firmware response model.

Pure official playItem -> shouldShuffleAudioItem -> ServicePlayScheme:
individual Spotify track/episode starts serialize /noshuffle AFTER parentpath.
All identities are invented. No persistent mode/queue behaviour is inferred.
"""

from unittest.mock import AsyncMock
from urllib.parse import quote

import pytest

from pyloxone_audio.native import AudioServerCommands


@pytest.mark.parametrize("prefix", ["spotify", "spotify@synthetic-account"])
@pytest.mark.parametrize("kind", ["track", "episode"])
@pytest.mark.parametrize("index", [None, 0, 13, 63])
async def test_individual_spotify_item_matches_native_no_shuffle_start(
    prefix, kind, index
):
    commands = AudioServerCommands("synthetic.invalid", lambda: ("user", "token"))
    commands._async_request = AsyncMock()
    path = f"{prefix}:{kind}:synthetic-item"
    parent = (
        {}
        if index is None
        else {
            "parent_path": "spotify:album:synthetic-parent",
            "parent_index": index,
        }
    )
    await commands.async_play_catalogue(
        7, "spotify", "synthetic-account", path, **parent
    )
    expected = f"audio/7/serviceplay/spotify/synthetic-account/{quote(path, safe='')}"
    if index is not None:
        expected += f"/parentpath/spotify%3Aalbum%3Asynthetic-parent/{index}"
    commands._async_request.assert_awaited_once_with(
        expected + "/noshuffle",
        None,
        is_current=None,
        on_send=None,
    )


@pytest.mark.parametrize(
    "service,account,path",
    [
        ("spotify", "synthetic-account", "spotify:album:synthetic"),
        ("spotify", "synthetic-account", "spotify:playlist:synthetic"),
        ("spotify", "synthetic-account", "spotify:artist:synthetic"),
        ("spotify", "synthetic-account", "spotify:show:synthetic"),
        ("library", "nouser", "library:local:track:synthetic"),
        ("playlist", "nouser", "playlist:synthetic"),
        ("linein", "nouser", "synthetic-input"),
    ],
)
async def test_contexts_and_other_native_routes_do_not_gain_item_flag(
    service, account, path
):
    commands = AudioServerCommands("synthetic.invalid", lambda: ("user", "token"))
    commands._async_request = AsyncMock()
    await commands.async_play_catalogue(7, service, account, path)
    command = commands._async_request.await_args.args[0]
    assert not command.endswith("/noshuffle")
    commands._async_request.assert_awaited_once()
