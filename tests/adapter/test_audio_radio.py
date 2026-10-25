"""Synthetic native radio catalogue contracts; no household IO or captures."""

# ruff: noqa: S101, INP001, ANN001, PLC0415, D103, PLR2004, SLF001, PT011, PT018

from unittest.mock import AsyncMock

import pytest


def favourite(index):
    return {"id": index, "name": f"Station {index}", "type": "tunein", "audiopath": f"tunein:station:s{index}"}


@pytest.mark.asyncio
async def test_more_than_one_page_of_favourites_reaches_the_standard_source_parser(monkeypatch):
    from custom_components.loxone.audio_sources import parse_room_favourites
    from custom_components.loxone.pyloxone_api.audioserver import AudioServerCommands

    owner = AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "token"))
    request = AsyncMock(
        side_effect=[
            [{"id": 7, "start": 0, "totalitems": 40, "items": [favourite(i) for i in range(1, 33)]}],
            [{"id": 7, "start": 32, "totalitems": 40, "items": [favourite(i) for i in range(33, 41)]}],
        ] * 2
    )
    monkeypatch.setattr(owner, "_async_request", request)
    choices = parse_room_favourites(await owner.async_room_favourites(7), 7)
    assert len(choices) == 40
    assert [choice.favourite_id for choice in choices] == list(range(1, 41))
    assert [call.args for call in request.await_args_list] == [
        ("audio/cfg/getroomfavs/7/0/32", "getroomfavs_result"),
        ("audio/cfg/getroomfavs/7/32/32", "getroomfavs_result"),
    ] * 2


@pytest.mark.asyncio
async def test_native_browse_lists_provider_folders_and_pages_more_than_three_stations():
    import importlib.util

    assert importlib.util.find_spec("custom_components.loxone.audio_radio") is not None, "Native radio browser missing"
    from custom_components.loxone.audio_radio import RadioCatalogue

    commands = AsyncMock()
    commands.async_radio_services.return_value = [{"name": "World radio", "cmd": "world", "root": "root/path"}]
    commands.async_radio_folder.return_value = [
        {
            "start": 0,
            "totalitems": 55,
            "name": "World radio",
            "items": [
                {"id": str(i), "type": 2, "name": f"Station {i}", "audiopath": f"tunein:station:s{i}"}
                for i in range(50)
            ],
        }
    ]
    catalogue = RadioCatalogue(commands, 7)
    root = await catalogue.async_browse()
    assert root.can_search and not root.can_play
    provider = next(child for child in root.children if child.title == "World radio")
    page = await catalogue.async_browse(provider.media_content_id)
    commands.async_radio_folder.assert_awaited_once_with("world", "root/path", 0)
    stations = [child for child in page.children if child.can_play]
    assert len(stations) == 50 and all(not child.can_expand for child in stations)
    assert catalogue.resolve(stations[4].media_content_id).audio_path == "tunein:station:s4"
    more = page.children[-1]
    assert more.can_expand and not more.can_play and more.title == "More stations…"
    commands.async_radio_folder.return_value = [
        {
            "start": 50,
            "totalitems": 55,
            "name": "World radio",
            "items": [
                {"id": str(i), "type": 2, "name": f"Station {i}", "audiopath": f"tunein:station:s{i}"}
                for i in range(50, 55)
            ],
        }
    ]
    last = await catalogue.async_browse(more.media_content_id)
    assert len(last.children) == 5 and all(child.can_play for child in last.children)
    assert commands.async_radio_folder.await_args.args == ("world", "root/path", 50)
    assert not commands.async_play_radio_station.called


@pytest.mark.asyncio
async def test_native_radio_read_routes_quote_identifiers_and_search_waits_for_matching_ticket(monkeypatch):
    import json
    from unittest.mock import MagicMock
    from custom_components.loxone.pyloxone_api import audioserver as wire

    owner = wire.AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "token"))
    assert hasattr(owner, "async_radio_services"), "Native catalogue transport missing"
    request = AsyncMock(return_value=[])
    monkeypatch.setattr(owner, "_async_request", request)
    await owner.async_radio_services()
    await owner.async_radio_folder("world", "folder:/with + slash", 50)
    assert [call.args for call in request.await_args_list] == [
        ("audio/cfg/getradios", "getradios_result"),
        ("audio/cfg/getservicefolder/world/world/folder%3A%2Fwith%20%2B%20slash/50/50", "getservicefolder_result"),
    ]
    monkeypatch.undo()
    socket = AsyncMock()
    socket.__aenter__.return_value = socket
    result = {
        "station": {
            "totalitems": 1,
            "items": [
                {"type": 2, "name": "Radio & café", "audiopath": "tunein:station:s1"},
            ],
        }
    }
    socket.recv.side_effect = [
        json.dumps(frame)
        for frame in [
            {"globalsearch_result": {"unique": "ticket-one"}},
            {"audio_event": []},
            {"unique": "wrong", "type": "tunein", "globalsearch_result": {"station": {"items": []}}},
            {"unique": "ticket-one", "type": "spotify", "globalsearch_result": {}},
            {"unique": "ticket-one", "type": "tunein", "globalsearch_result": result},
        ]
    ]
    monkeypatch.setattr(wire, "connect", MagicMock(return_value=socket))
    monkeypatch.setattr(owner, "_authenticate", AsyncMock())
    assert await owner.async_radio_search("Radio & café/one") == result
    socket.send.assert_awaited_once_with(
        "audio/cfg/globalsearch/tunein:station#100,custom#100/Radio%20%26%20caf%C3%A9%2Fone"
    )
    assert socket.recv.await_count == 5
    assert owner._socket is None


@pytest.mark.asyncio
async def test_native_search_results_are_playable_discovered_stations_not_an_ack():
    from custom_components.loxone.audio_radio import RadioCatalogue

    commands = AsyncMock()
    commands.async_radio_search.return_value = {
        "station": {
            "totalitems": 2,
            "items": [
                {"type": 2, "name": "Radio one", "audiopath": "tunein:station:s1"},
                {"type": 2, "name": "Radio two", "audiopath": "loxoneradio:station:s2"},
            ],
        },
        "custom": {
            "totalitems": 1,
            "items": [
                {"type": 2, "name": "Custom radio", "audiopath": "tunein:custom:3"},
            ],
        },
    }
    catalogue = RadioCatalogue(commands, 7)
    result = await catalogue.async_search("Radio")
    assert [item.title for item in result.result] == ["Radio one", "Radio two", "Custom radio"]
    targets = [catalogue.resolve(item.media_content_id) for item in result.result]
    assert [target.service for target in targets] == ["world", "world", "custom"]
    assert all(item.can_play and not item.can_expand for item in result.result)
    assert not commands.async_play_radio_station.called


@pytest.mark.asyncio
async def test_discovered_radio_station_uses_native_radio_serviceplay_and_exact_encoded_path(monkeypatch):
    from custom_components.loxone.pyloxone_api.audioserver import AudioServerCommands

    owner = AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "token"))
    assert hasattr(owner, "async_play_radio_station"), "Discovered radio playback missing"
    request = AsyncMock()
    monkeypatch.setattr(owner, "_async_request", request)
    await owner.async_play_radio_station(7, "world", "tunein:station:s1/+plus")
    request.assert_awaited_once_with(
        "audio/7/serviceplay/radio/world/tunein%3Astation%3As1%2F%2Bplus",
        None,
        is_current=None,
        on_send=None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"start": 0},
        {"id": 8},
        {"totalitems": 41},
        {"items": []},
        {"items": [favourite(1)] * 8},
    ],
)
async def test_large_favourites_never_publish_partial_changed_or_duplicate_pages(monkeypatch, change):
    from custom_components.loxone.audio_sources import parse_room_favourites
    from custom_components.loxone.pyloxone_api.audioserver import AudioCommandError, AudioServerCommands

    owner = AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "token"))
    request = AsyncMock(
        side_effect=[
            [{"id": 7, "start": 0, "totalitems": 40, "items": [favourite(i) for i in range(1, 33)]}],
            [{"id": 7, "start": 32, "totalitems": 40, "items": [favourite(i) for i in range(33, 41)], **change}],
        ]
    )
    monkeypatch.setattr(owner, "_async_request", request)
    with pytest.raises((AudioCommandError, ValueError)):
        parse_room_favourites(await owner.async_room_favourites(7), 7)
    assert request.await_count == 2


@pytest.mark.asyncio
async def test_favourite_maximum_is_complete_and_larger_lists_fail_without_truncating(monkeypatch):
    from custom_components.loxone.audio_sources import parse_room_favourites
    from custom_components.loxone.pyloxone_api.audioserver import AudioCommandError, AudioServerCommands

    owner = AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "token"))
    pages = [
        [{"id": 7, "start": start, "totalitems": 256, "items": [favourite(i) for i in range(start + 1, start + 33)]}]
        for start in range(0, 256, 32)
    ]
    request = AsyncMock(side_effect=pages * 2)
    monkeypatch.setattr(owner, "_async_request", request)
    assert len(parse_room_favourites(await owner.async_room_favourites(7), 7)) == 256
    assert request.await_count == 2 * len(pages)
    request.reset_mock(side_effect=True)
    request.return_value = [{"id": 7, "start": 0, "totalitems": 257, "items": [favourite(1)]}]
    with pytest.raises(AudioCommandError):
        await owner.async_room_favourites(7)
    assert request.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["", "  ", "x\n", "x" * 257, True, None])
async def test_invalid_search_queries_send_no_request(monkeypatch, query):
    from custom_components.loxone.pyloxone_api.audioserver import AudioServerCommands

    owner = AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "token"))
    request = AsyncMock()
    monkeypatch.setattr(owner, "_async_request", request)
    with pytest.raises(ValueError):
        await owner.async_radio_search(query)
    request.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("service", "folder", "offset"),
    [
        ("world/other", "root", 0),
        (True, "root", 0),
        ("world", "", 0),
        ("world", "line\ncontrol", 0),
        ("world", "root", True),
        ("world", "root", -1),
        ("world", "root", 1_000_001),
    ],
)
async def test_invalid_catalogue_targets_send_no_request(monkeypatch, service, folder, offset):
    from custom_components.loxone.pyloxone_api.audioserver import AudioServerCommands

    owner = AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "token"))
    request = AsyncMock()
    monkeypatch.setattr(owner, "_async_request", request)
    with pytest.raises(ValueError):
        await owner.async_radio_folder(service, folder, offset)
    request.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("finish", ["timeout", "cancel"])
async def test_ack_only_search_is_never_reported_as_empty_success_and_owns_cleanup(monkeypatch, finish):
    import asyncio
    import json
    from unittest.mock import MagicMock
    from custom_components.loxone.pyloxone_api import audioserver as wire

    owner = wire.AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "token"), timeout=0.03)
    socket = AsyncMock()
    socket.__aenter__.return_value = socket
    received = asyncio.Event()
    count = 0

    async def recv() -> str:
        nonlocal count
        count += 1
        if count == 1:
            return json.dumps({"globalsearch_result": {"unique": "synthetic-ticket"}})
        received.set()
        return await asyncio.Future()

    socket.recv.side_effect = recv
    monkeypatch.setattr(wire, "connect", MagicMock(return_value=socket))
    monkeypatch.setattr(owner, "_authenticate", AsyncMock())
    task = asyncio.create_task(owner.async_radio_search("radio"))
    await received.wait()
    if finish == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(wire.AudioCommandError):
            await task
    socket.send.assert_awaited_once()
    assert socket.__aexit__.await_count == 1 and owner._socket is None


@pytest.mark.asyncio
async def test_search_deduplicates_normalised_results_and_bounds_per_entity_cache():
    from custom_components.loxone import audio_radio as radio

    commands = AsyncMock()
    station = {"type": 2, "name": "Radio", "audiopath": "tunein:station:s1"}
    commands.async_radio_search.return_value = {"error": False, "result": {"station": {"items": [station, station]}}}
    catalogue = radio.RadioCatalogue(commands, 7)
    first = (await catalogue.async_search("radio")).result[0]
    for _ in range(radio._MAX_ENTRIES):
        await catalogue.async_search("radio")
    assert len(catalogue._entries) == radio._MAX_ENTRIES
    with pytest.raises(ValueError):
        catalogue.resolve(first.media_content_id)
    other = radio.RadioCatalogue(commands, 8)
    with pytest.raises(ValueError):
        other.resolve(next(iter(catalogue._entries)))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"start": 1},
        {"totalitems": 0},
        {"totalitems": True},
        {"items": []},
        {"items": [{"type": 2, "name": "wrong path", "audiopath": "https://example.invalid/stream"}]},
    ],
)
async def test_invalid_browse_pages_do_not_offer_guessed_or_partial_stations(change):
    from custom_components.loxone.audio_radio import RadioCatalogue

    commands = AsyncMock()
    commands.async_radio_services.return_value = [{"name": "World", "cmd": "world", "root": "root"}]
    commands.async_radio_folder.return_value = [
        {
            "start": 0,
            "totalitems": 1,
            "items": [
                {"type": 2, "name": "radio", "audiopath": "tunein:station:s1"},
            ],
            **change,
        }
    ]
    catalogue = RadioCatalogue(commands, 7)
    root = await catalogue.async_browse()
    provider = next(item for item in root.children if item.title == "World")
    with pytest.raises(ValueError):
        await catalogue.async_browse(provider.media_content_id)
    commands.async_play_radio_station.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_page", ["first", "last"])
async def test_large_favourites_reject_path_changes_across_page_boundary_even_when_totals_match(
    monkeypatch, changed_page,
):
    from copy import deepcopy
    from custom_components.loxone.pyloxone_api.audioserver import AudioCommandError, AudioServerCommands

    owner = AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "token"))
    first = [{"id": 7, "start": 0, "totalitems": 40, "items": [favourite(i) for i in range(1, 33)]}]
    second = [{"id": 7, "start": 32, "totalitems": 40, "items": [favourite(i) for i in range(33, 41)]}]
    updated_first, updated_second = deepcopy(first), deepcopy(second)
    updated_first[0]["items"][0]["audiopath"] = "tunein:station:changed-one"
    updated_second[0]["items"][0]["audiopath"] = "tunein:station:changed-thirty-three"
    replies = (
        [first, updated_second, updated_first, updated_second]
        if changed_page == "first" else [first, second, first, updated_second]
    )
    request = AsyncMock(side_effect=replies)
    monkeypatch.setattr(owner, "_async_request", request)
    with pytest.raises(AudioCommandError, match="changed"):
        await owner.async_room_favourites(7)
    assert request.await_count == (3 if changed_page == "first" else 4)


@pytest.mark.asyncio
async def test_client_close_aborts_delayed_radio_search_and_blocks_further_connections(monkeypatch):
    import asyncio
    import json
    from unittest.mock import MagicMock
    from custom_components.loxone.pyloxone_api import audioserver as wire

    owner = wire.AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "token"))
    socket = AsyncMock()
    socket.__aenter__.return_value = socket
    received, closed = asyncio.Event(), asyncio.Event()

    async def recv() -> str:
        if not received.is_set():
            received.set()
            return json.dumps({"globalsearch_result": {"unique": "synthetic-ticket"}})
        await closed.wait()
        raise OSError

    socket.recv.side_effect = recv
    socket.close.side_effect = closed.set
    connection = MagicMock(return_value=socket)
    monkeypatch.setattr(wire, "connect", connection)
    monkeypatch.setattr(owner, "_authenticate", AsyncMock())
    task = asyncio.create_task(owner.async_radio_search("radio"))
    await received.wait()
    await owner.async_close()
    with pytest.raises(wire.AudioCommandError):
        await task
    with pytest.raises(wire.AudioCommandError):
        await owner.async_radio_search("radio")
    assert connection.call_count == 1 and owner._socket is None
    socket.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "cancel", "transport"])
async def test_radio_selection_accepts_post_send_feedback_but_retains_uncertain_fences(outcome):
    import asyncio
    from types import SimpleNamespace
    from test_audio_sources import Metadata
    from custom_components.loxone.audio_sources import async_select_radio_station
    from custom_components.loxone.pyloxone_api.audioserver import AudioCommandError

    metadata = Metadata()
    sent, echo = asyncio.Event(), asyncio.Event()

    async def play(player, service, path, *, is_current, on_send) -> None:
        assert (player, service, path) == (7, "world", "tunein:station:found")
        assert is_current()
        on_send()
        sent.set()
        await echo.wait()
        if outcome == "transport":
            raise AudioCommandError

    commands = SimpleNamespace(async_play_radio_station=play, source_fences={}, announcement_fences={})
    task = asyncio.create_task(async_select_radio_station(
        commands, metadata, 7, "world", "tunein:station:found", is_available=lambda: True,
    ))
    try:
        await sent.wait()
        metadata.set({"audiopath": "tunein:station:found", "mode": "play"})
        if outcome == "success":
            echo.set()
            await asyncio.wait_for(task, 0.2)
            assert not commands.source_fences and not metadata.listeners
            return
        elif outcome == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            echo.set()
            with pytest.raises(AudioCommandError):
                await task
        for callback in tuple(metadata.listeners):
            callback()
        assert 7 in commands.source_fences
        metadata.set({"audiopath": "tunein:station:wrong", "mode": "play"})
        assert 7 in commands.source_fences
        metadata.set({"audiopath": "tunein:station:found", "mode": "play"})
        if outcome == "success":
            await task
        assert not commands.source_fences and not metadata.listeners
    finally:
        echo.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for release in tuple(commands.source_fences.values()):
            release()
