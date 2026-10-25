"""Synthetic extension contracts derived from native-client schemas; no household IO."""

# ruff: noqa: S101, INP001, ANN001, ANN202, PLC0415, D103, PLR2004, PLR0913, SLF001, ARG001, PT011, PT018

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from custom_components.loxone.audio_sources import parse_room_favourites
from custom_components.loxone.pyloxone_api import audioserver as wire


def favs(items):
    return [{"id": 7, "start": 0, "totalitems": len(items), "items": items}]


def test_one_room_favourites_list_accepts_native_library_spotify_linein_and_custom_radio():
    rows = [
        ("tunein", "tunein:station:one"),
        ("loxoneradio", "loxoneradio:stream:one"),
        ("custom_stream", "tunein:custom:two"),
        ("library_track", "library:local:track:one"),
        ("library_folder", "library:local:folder:one"),
        ("linein", "linein/ABCDEF123456#1000001"),
        ("spotify_track", "spotify@owner:track:one"),
        ("spotify_playlist", "spotify@owner:playlist:one"),
        ("spotify_album", "spotify@owner:album:one"),
        ("spotify_artist", "spotify@owner:artist:one"),
        ("spotify_collection", "spotify@owner:user:collection"),
        ("spotify_show", "spotify@owner:show:one"),
        ("spotify_episode", "spotify@owner:episode:one"),
    ]
    items = [{"id": n, "name": kind, "type": kind, "audiopath": path} for n, (kind, path) in enumerate(rows, 1)]
    choices = parse_room_favourites(favs(items), 7)
    assert len(choices) == len(items)
    assert [c.audio_path for c in choices] == [r[1] for r in rows]
    assert choices[4].is_context and choices[7].is_context
    assert not choices[3].is_context and not choices[5].is_context


def test_native_parent_context_and_source_identity_survive_metadata_parser():
    row = {
        "playerid": 7,
        "mode": "play",
        "audiopath": "spotify:track:one",
        "sourceName": "Synthetic owner",
        "parent": {"id": "spotify:playlist:one"},
    }
    snapshot = wire.parse_audio_events({"audio_event": [row]})[0]
    assert snapshot.parent_id == "spotify:playlist:one"
    assert snapshot.source_name == "Synthetic owner"


@pytest.mark.asyncio
async def test_native_source_reads_and_plays_use_exact_account_and_input(monkeypatch):
    owner = wire.AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "token"))
    request = AsyncMock(return_value=[])
    monkeypatch.setattr(owner, "_async_request", request)
    await owner.async_source_inputs()
    await owner.async_search_capabilities()
    await owner.async_media_folder("library", "nouser", "library:local:folder:one/+x", 50)
    await owner.async_media_folder("spotify", "owner", "start", 0)
    await owner.async_media_folder("loxoneradio", "noUser", "start", 0)
    await owner.async_play_catalogue(7, "linein", "nouser", "ABCDEF123456#1000001")
    await owner.async_play_catalogue(7, "library", "nouser", "library:local:track:one")
    await owner.async_play_catalogue(7, "spotify", "owner", "spotify@owner:playlist:one")
    assert [c.args[0] for c in request.await_args_list] == [
        "audio/cfg/getinputs",
        "audio/cfg/globalsearch/describe",
        "audio/cfg/getmediafolder/library%3Alocal%3Afolder%3Aone%2F%2Bx/50/50",
        "audio/cfg/getservicefolder/spotify/owner/start/0/50",
        "audio/cfg/getservicefolder/loxoneradio/noUser/start/0/50",
        "audio/7/linein/ABCDEF123456%231000001",
        "audio/7/library/play/library%3Alocal%3Atrack%3Aone",
        "audio/7/serviceplay/spotify/owner/spotify%40owner%3Aplaylist%3Aone",
    ]
    before = request.await_count
    for args in [
        (7, "linein", "nouser", ""),
        (True, "library", "nouser", "one"),
        (7, "spotify", "owner/other", "one"),
        (7, "unknown", "nouser", "one"),
    ]:
        with pytest.raises(ValueError):
            await owner.async_play_catalogue(*args)
    assert request.await_count == before


@pytest.mark.asyncio
async def test_global_search_collects_every_requested_ticket_scope_in_any_order(monkeypatch):
    owner = wire.AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "token"))
    socket = AsyncMock()
    socket.__aenter__.return_value = socket
    frames = [
        {"globalsearch_result": {"unique": "one"}},
        {"unique": "wrong", "type": "local", "globalsearch_result": {"track": {"items": []}}},
        {
            "unique": "one",
            "type": "spotify",
            "globalsearch_result": {"error": False, "result": {"user": "wrong", "track": {"items": []}}},
        },
        {"unique": "one", "type": "tunein", "globalsearch_result": {"station": {"items": []}}},
        {
            "unique": "one",
            "type": "spotify",
            "globalsearch_result": {"error": False, "result": {"user": "owner", "track": {"items": []}}},
        },
        {"unique": "one", "type": "local", "globalsearch_result": {"track": {"items": []}}},
    ]
    socket.recv.side_effect = [json.dumps(f) for f in frames]
    monkeypatch.setattr(wire, "connect", MagicMock(return_value=socket))
    monkeypatch.setattr(owner, "_authenticate", AsyncMock())
    result = await owner.async_global_search(
        "café/one",
        {"local": ("track",), "spotify": ("track",), "tunein": ("station", "custom")},
        spotify_account="owner",
    )
    assert set(result) == {"tunein", "local", "spotify"}
    socket.send.assert_awaited_once_with(
        "audio/cfg/globalsearch/local:track#50|spotify@owner:track#50|tunein:station#50,custom#50/caf%C3%A9%2Fone"
    )
    assert socket.recv.await_count == len(frames) and owner._socket is None


def catalogue_commands():
    return SimpleNamespace(
        async_service_accounts=AsyncMock(
            return_value=[
                {
                    "cmd": "spotify",
                    "id": "owner",
                    "user": "Synthetic owner",
                    "name": "Synthetic Spotify",
                    "configerror": False,
                }
            ]
        ),
        async_radio_services=AsyncMock(return_value=[{"cmd": "world", "root": "root", "name": "World"}]),
        async_room_favourites=AsyncMock(return_value=favs([])),
        async_source_inputs=AsyncMock(
            return_value=[
                {
                    "type": 6,
                    "id": "ABCDEF123456#1000001",
                    "cmd": "linein/ABCDEF123456#1000001",
                    "name": "Record player",
                    "valid": True,
                    "power": "on",
                }
            ]
        ),
        async_media_folder=AsyncMock(return_value=[{"start": 0, "totalitems": 0, "items": []}]),
        async_search_capabilities=AsyncMock(
            return_value={
                "local": ["track", "folder"],
                "spotify": ["track", "playlist"],
                "tunein": ["station", "custom"],
            }
        ),
        async_global_search=AsyncMock(
            return_value={
                "local": {"tracks": {"items": [{"id": "library:local:track:one", "type": 2, "name": "Local song"}]}},
                "spotify": {
                    "user": "owner",
                    "playlists": {
                        "items": [
                            {
                                "id": "spotify@owner:playlist:one",
                                "audiopath": "spotify@owner:playlist:one",
                                "type": 7,
                                "tag": "playlist",
                                "name": "Spotify collection",
                            }
                        ]
                    },
                },
                "tunein": {"station": {"items": [{"type": 2, "name": "Radio one", "audiopath": "tunein:station:one"}]}},
            }
        ),
    )


@pytest.mark.asyncio
async def test_native_browser_contains_sources_and_exact_nonsearchable_linein():
    from custom_components.loxone.audio_catalogue import AudioCatalogue

    commands = catalogue_commands()
    catalogue = AudioCatalogue(commands, 7)
    root = await catalogue.async_browse()
    titles = [c.title for c in root.children]
    assert titles == [
        "Room favourites",
        "Radio",
        "Loxone Radio",
        "Local Library",
        "Spotify · Synthetic Spotify",
        "Line-In",
    ]
    inputs = next(c for c in root.children if c.title == "Line-In")
    page = await catalogue.async_browse(inputs.media_content_id)
    assert not page.can_search and len(page.children) == 1
    target = catalogue.resolve(page.children[0].media_content_id)
    assert target.kind == "input" and target.folder == "ABCDEF123456#1000001"
    assert target.audio_path == "linein:ABCDEF123456#1000001"
    with pytest.raises(ValueError):
        await catalogue.async_search("record", inputs.media_content_id)
    commands.async_global_search.assert_not_awaited()


@pytest.mark.asyncio
async def test_library_browse_preserves_page_bounds_and_context_playability():
    from custom_components.loxone.audio_catalogue import AudioCatalogue

    commands = catalogue_commands()
    catalogue = AudioCatalogue(commands, 7)
    root = await catalogue.async_browse()
    library = next(c for c in root.children if c.title == "Local Library")
    commands.async_media_folder.return_value = [
        {
            "start": 0,
            "totalitems": 51,
            "items": [{"type": 1, "id": "library:local:folder:" + str(i), "name": str(i)} for i in range(50)],
        }
    ]
    page = await catalogue.async_browse(library.media_content_id)
    assert len(page.children) == 51 and page.children[0].can_play and page.children[0].can_expand
    more = page.children[-1]
    assert more.can_expand and not more.can_play
    assert catalogue.resolve(more.media_content_id).offset == 50
    commands.async_media_folder.assert_awaited_once_with("library", "nouser", "0", 0)


@pytest.mark.asyncio
async def test_root_search_combines_plural_native_categories_and_provider_search_is_scoped():
    from custom_components.loxone.audio_catalogue import AudioCatalogue

    commands = catalogue_commands()
    catalogue = AudioCatalogue(commands, 7)
    result = await catalogue.async_search("one")
    targets = [catalogue.resolve(r.media_content_id) for r in result.result]
    assert {t.service for t in targets} == {"library", "spotify", "world"}
    assert next(t for t in targets if t.service == "library").account == "nouser"
    spotify = next(t for t in targets if t.service == "spotify")
    assert spotify.account == "owner" and spotify.is_context
    assert all(any(provider in r.title for provider in ("Library", "Spotify", "Radio")) for r in result.result)
    root = await catalogue.async_browse()
    library = next(c for c in root.children if c.title == "Local Library")
    commands.async_global_search.return_value = {"local": {"tracks": {"items": []}}}
    await catalogue.async_search("none", library.media_content_id)
    assert commands.async_global_search.await_args.args[1] == {"local": ("track", "folder")}
    assert commands.async_global_search.await_args.kwargs == {"spotify_account": None}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("service", "path", "context", "wire_row"),
    [
        (
            "library",
            "library:local:folder:one",
            True,
            {"audiopath": "library:local:track:child", "parent": {"id": "library:local:folder:one"}},
        ),
        (
            "spotify",
            "spotify@owner:playlist:one",
            True,
            {
                "audiopath": "spotify:track:child",
                "parent": {"id": "spotify:playlist:one"},
                "sourceName": "Synthetic owner",
            },
        ),
        ("linein", "linein:ABCDEF123456#1000001", False, {"audiopath": "linein:ABCDEF123456#1000001"}),
    ],
)
async def test_catalogue_selection_requires_exact_context_account_or_input(service, path, context, wire_row):
    from custom_components.loxone.audio_catalogue import CatalogueTarget
    from custom_components.loxone.audio_sources import async_select_catalogue
    from test_audio_sources import Metadata

    metadata = Metadata()
    commands = catalogue_commands()
    commands.source_fences = {}
    commands.announcement_fences = {}
    called = asyncio.Event()

    async def play(player, provider, account, item, *, is_current, on_send):
        assert is_current()
        on_send()
        called.set()

    commands.async_play_catalogue = AsyncMock(side_effect=play)
    target = CatalogueTarget(
        "folder" if context else "input",
        "Selected",
        service,
        "ABCDEF123456#1000001" if service == "linein" else path,
        audio_path=path,
        account="owner" if service == "spotify" else "nouser",
        is_context=context,
    )
    task = asyncio.create_task(async_select_catalogue(commands, metadata, 7, target, is_available=lambda: True))
    try:
        await called.wait()
        await asyncio.sleep(0)
        metadata.set(
            {
                "mode": "play",
                "audiopath": "spotify:track:wrong",
                "parent": {"id": "spotify:playlist:wrong"},
                "sourceName": "Wrong account",
            }
        )
        assert not task.done()
        metadata.set({"mode": "play", **wire_row})
        await asyncio.wait_for(task, 0.2)
        assert not commands.source_fences
        assert commands.async_play_catalogue.await_count == 1
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for release in tuple(commands.source_fences.values()):
            release()


@pytest.mark.asyncio
async def test_spotify_favourite_confirms_native_parent_not_track_uri():
    from custom_components.loxone.audio_sources import async_select_favourite
    from test_audio_sources import Metadata

    payload = favs(
        [{"id": 3, "name": "Collection", "type": "spotify_playlist", "audiopath": "spotify@owner:playlist:one"}]
    )
    choice = parse_room_favourites(payload, 7)[0]
    metadata = Metadata()
    commands = catalogue_commands()
    commands.source_fences = {}
    commands.announcement_fences = {}
    commands.async_room_favourites.return_value = payload

    async def play(player, favourite, *, is_current, on_send):
        assert is_current()
        on_send()
        metadata.set(
            {
                "mode": "play",
                "audiopath": "spotify:track:child",
                "parent": {"id": "spotify:playlist:one"},
                "sourceName": "Synthetic owner",
            }
        )

    commands.async_play_room_favourite = AsyncMock(side_effect=play)
    await asyncio.wait_for(async_select_favourite(commands, metadata, choice, is_available=lambda: True), 0.2)
    commands.async_play_room_favourite.assert_awaited_once()


@pytest.mark.asyncio
async def test_native_loxone_radio_station_uses_native_no_user_service(monkeypatch):
    owner = wire.AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "token"))
    request = AsyncMock()
    monkeypatch.setattr(owner, "_async_request", request)
    await owner.async_play_radio_station(7, "loxoneradio", "loxoneradio:stream:one")
    assert request.await_args.args[0] == "audio/7/serviceplay/radio/nouser/loxoneradio%3Astream%3Aone"


@pytest.mark.asyncio
async def test_read_rejection_is_not_reported_as_empty_available_inputs(monkeypatch):
    owner = wire.AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "token"))
    socket = AsyncMock()
    socket.__aenter__.return_value = socket
    socket.recv.return_value = json.dumps(
        {"command": "audio/cfg/getinputs", "error": "rejected", "getinputs_result": []}
    )
    monkeypatch.setattr(wire, "connect", MagicMock(return_value=socket))
    monkeypatch.setattr(owner, "_authenticate", AsyncMock())
    with pytest.raises(wire.AudioCommandError):
        await owner.async_source_inputs()


@pytest.mark.asyncio
async def test_local_playlist_search_uses_observed_playlist_path_not_invented_library_uri():
    from custom_components.loxone.audio_catalogue import AudioCatalogue

    commands = catalogue_commands()
    commands.async_search_capabilities.return_value = {"local": ["playlist"]}
    commands.async_global_search.return_value = {
        "local": {
            "playlists": {
                "items": [
                    {"id": "one", "type": 11, "audiopath": "lms:synthetic:playlist:one", "name": "Local playlist"}
                ]
            }
        }
    }
    catalogue = AudioCatalogue(commands, 7)
    result = await catalogue.async_search("playlist")
    assert len(result.result) == 1 and result.result[0].can_play
    target = catalogue.resolve(result.result[0].media_content_id)
    assert target.service == "playlist" and target.folder == "lms:synthetic:playlist:one" and target.is_context


@pytest.mark.asyncio
@pytest.mark.parametrize("finish", ["timeout", "cancel", "error", "close"])
async def test_partial_multi_provider_search_never_masquerades_as_complete_and_closes(monkeypatch, finish):
    owner = wire.AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "token"), timeout=0.03)
    socket = AsyncMock()
    socket.__aenter__.return_value = socket
    waiting, closed = asyncio.Event(), asyncio.Event()
    frames = [
        {"globalsearch_result": {"unique": "one"}},
        {"unique": "one", "type": "local", "globalsearch_result": {"tracks": {"items": []}}},
    ]

    async def recv():
        if frames:
            return json.dumps(frames.pop(0))
        waiting.set()
        if finish == "error":
            return json.dumps({"unique": "one", "type": "spotify", "globalsearch_result": {"error": 1}})
        if finish == "close":
            await closed.wait()
            raise OSError
        await asyncio.Future()
        message = "Unreachable after unresolved receive"
        raise AssertionError(message)

    socket.recv.side_effect = recv
    socket.close.side_effect = closed.set
    monkeypatch.setattr(wire, "connect", MagicMock(return_value=socket))
    monkeypatch.setattr(owner, "_authenticate", AsyncMock())
    task = asyncio.create_task(
        owner.async_global_search("one", {"local": ("track",), "spotify": ("track",)}, spotify_account="owner")
    )
    await waiting.wait()
    if finish == "cancel":
        task.cancel()
    if finish == "close":
        await owner.async_close()
    with pytest.raises(asyncio.CancelledError if finish == "cancel" else wire.AudioCommandError):
        await task
    assert socket.__aexit__.await_count == 1 and owner._socket is None
    socket.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_unscoped_spotify_selection_cannot_noop_on_same_track_in_another_account():
    from custom_components.loxone.audio_catalogue import CatalogueTarget
    from custom_components.loxone import audio_sources as sources
    from test_audio_sources import Metadata

    metadata = Metadata()
    metadata.set({"audiopath": "spotify:track:one", "mode": "play", "sourceName": "Second user"})
    sent = []

    async def play(player, provider, account, item, *, is_current, on_send):
        assert is_current()
        on_send()
        sent.append((player, provider, account, item))
        metadata.set({"audiopath": "spotify:track:one", "mode": "play", "sourceName": "First user"})

    commands = SimpleNamespace(
        source_fences={},
        announcement_fences={},
        async_play_catalogue=play,
        async_service_accounts=AsyncMock(
            return_value=[
                {"cmd": "spotify", "id": "first", "user": "First user", "configerror": False},
                {"cmd": "spotify", "id": "second", "user": "Second user", "configerror": False},
            ]
        ),
    )
    target = CatalogueTarget(
        "item", "One", "spotify", "spotify:track:one", audio_path="spotify:track:one", account="first"
    )
    await sources.async_select_catalogue(commands, metadata, 7, target, is_available=lambda: True)
    assert sent == [(7, "spotify", "first", "spotify:track:one")]


def test_spotify_catalogue_checks_actual_identifier_not_just_advertised_path():
    from custom_components.loxone.audio_catalogue import AudioCatalogue

    with pytest.raises(ValueError, match=r"account|identity"):
        AudioCatalogue._parse_source_item(
            {"type": 2, "name": "One", "id": "spotify@other:track:one", "audiopath": "spotify@owner:track:one"},
            "spotify",
            "owner",
        )


def test_unscoped_spotify_favourite_is_not_advertised_as_verified_account_selection():
    items = [
        {"id": 1, "name": "Ambiguous", "type": "spotify_track", "audiopath": "spotify:track:one"},
        {"id": 2, "name": "Radio", "type": "tunein", "audiopath": "tunein:station:one"},
    ]
    choices = parse_room_favourites(favs(items), 7)
    assert [choice.favourite_id for choice in choices] == [2]


@pytest.mark.asyncio
async def test_search_ignores_explicit_wrong_account_error_before_accepting_right_account():
    owner = wire.AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "token"))
    frames = iter(
        [
            {"globalsearch_result": {"unique": "one"}},
            {"unique": "one", "type": "spotify", "globalsearch_result": {"error": 1, "result": {"user": "other"}}},
            {
                "unique": "one",
                "type": "spotify",
                "globalsearch_result": {"error": 0, "result": {"user": "owner", "tracks": {"items": []}}},
            },
        ]
    )
    socket = SimpleNamespace(recv=AsyncMock(side_effect=lambda: json.dumps(next(frames))))
    result = await owner._global_search_reply(socket, ("spotify",), "owner")
    assert result == {"spotify": {"user": "owner", "tracks": {"items": []}}}


@pytest.mark.asyncio
async def test_multi_account_search_fails_bounded_instead_of_returning_evicted_opaque_selections():
    from custom_components.loxone.audio_catalogue import AudioCatalogue

    commands = catalogue_commands()
    commands.async_service_accounts.return_value = [
        {"cmd": "spotify", "id": f"owner{i}", "user": f"User {i}", "configerror": False} for i in range(25)
    ]
    commands.async_search_capabilities.return_value = {"spotify": ["track"]}

    async def search(query, scopes, *, spotify_account=None):
        return {
            "spotify": {
                "tracks": {
                    "items": [
                        {"id": f"spotify@{spotify_account}:track:{i}", "type": 2, "name": str(i)} for i in range(50)
                    ]
                }
            }
        }

    commands.async_global_search.side_effect = search
    with pytest.raises(ValueError, match=r"bound|refine"):
        await AudioCatalogue(commands, 7).async_search("one")


@pytest.mark.asyncio
async def test_expanded_playable_spotify_collection_preserves_native_play_action():
    from custom_components.loxone.audio_catalogue import AudioCatalogue

    commands = catalogue_commands()
    commands.async_media_folder.return_value = [{"start": 0, "totalitems": 0, "items": []}]
    catalogue = AudioCatalogue(commands, 7)
    target = catalogue._parse_source_item(
        {"type": 1, "id": "spotify@owner:playlist:one", "name": "One", "tag": "playlist"}, "spotify", "owner"
    )
    item = catalogue._item(target)
    opened = await catalogue.async_browse(item.media_content_id)
    assert opened.can_play and opened.can_expand and opened.media_content_id == item.media_content_id
