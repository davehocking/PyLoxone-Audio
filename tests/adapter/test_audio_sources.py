"""Synthetic bounded configured-favourite controls; no household payloads."""

# ruff: noqa: S101, INP001, ANN001, ANN002, ANN202, ANN204, PLC0415, D101, D102, D103, D107, PLR2004, SLF001, ARG001, ARG002, ARG005, PT011, PT018
import importlib.util

import pytest


def test_known_room_favourites_preserve_exact_ids_paths_and_names():
    assert importlib.util.find_spec("custom_components.loxone.audio_sources") is not None, (
        "Configured-source parser missing"
    )
    from custom_components.loxone.audio_sources import parse_room_favourites

    rows = [
        {
            "id": 7,
            "start": 0,
            "totalitems": 2,
            "type": 4,
            "items": [
                {
                    "id": 3,
                    "slot": 1,
                    "name": "Radio one",
                    "type": "tunein",
                    "audiopath": "tunein:station:synthetic-one",
                },
                {
                    "id": 8,
                    "slot": 2,
                    "name": "Radio two",
                    "type": "tunein",
                    "audiopath": "tunein:station:synthetic-two",
                },
            ],
        }
    ]
    choices = parse_room_favourites(rows, 7)
    assert [(c.player_id, c.favourite_id, c.label, c.audio_path) for c in choices] == [
        (7, 3, "Radio one", "tunein:station:synthetic-one"),
        (7, 8, "Radio two", "tunein:station:synthetic-two"),
    ]


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        [],
        [{"id": 8, "start": 0, "totalitems": 0, "items": []}],
        [{"id": 7, "start": 1, "totalitems": 0, "items": []}],
        [{"id": 7, "start": 0, "totalitems": 33, "items": []}],
        [{"id": 7, "start": 0, "totalitems": 1, "items": []}],
        [{"id": 7, "start": 0, "totalitems": 0, "items": "not items"}],
    ],
)
def test_wrong_room_incomplete_or_unbounded_favourites_are_rejected(payload):
    from custom_components.loxone.audio_sources import parse_room_favourites

    with pytest.raises(ValueError):
        parse_room_favourites(payload, 7)


def test_unsupported_favourite_types_are_not_advertised_and_duplicate_labels_are_unambiguous():
    from custom_components.loxone.audio_sources import parse_room_favourites

    items = [
        {"id": 3, "name": "Radio", "type": "tunein", "audiopath": "tunein:station:one"},
        {"id": 8, "name": "Radio", "type": "tunein", "audiopath": "tunein:station:two"},
        {"id": 9, "name": "Unsupported", "type": "soundsuit", "audiopath": "soundsuit:synthetic"},
    ]
    result = parse_room_favourites([{"id": 7, "start": 0, "totalitems": 3, "items": items}], 7)
    assert [(x.favourite_id, x.label) for x in result] == [(3, "Radio (favourite 3)"), (8, "Radio (favourite 8)")]


@pytest.mark.parametrize(
    "change",
    [
        {"id": True},
        {"id": "3/play"},
        {"id": 0},
        {"name": ""},
        {"name": "x\ncontrol"},
        {"audiopath": "tunein:"},
        {"audiopath": "spotify:track:synthetic"},
        {"audiopath": "tunein:station:x\nother"},
    ],
)
def test_malformed_supported_favourite_is_not_a_control_target(change):
    from custom_components.loxone.audio_sources import parse_room_favourites

    item = {"id": 3, "name": "Radio", "type": "tunein", "audiopath": "tunein:station:one", **change}
    with pytest.raises(ValueError):
        parse_room_favourites([{"id": 7, "start": 0, "totalitems": 1, "items": [item]}], 7)


@pytest.mark.asyncio
async def test_native_favourite_discovery_and_play_keep_exact_player_and_id(monkeypatch):
    from unittest.mock import AsyncMock
    from custom_components.loxone.pyloxone_api import audioserver as wire

    owner = wire.AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "token"))
    assert hasattr(owner, "async_room_favourites"), "Read-only configured-source discovery missing"
    request = AsyncMock(return_value=[])
    monkeypatch.setattr(owner, "_async_request", request)
    assert await owner.async_room_favourites(7) == []
    request.assert_awaited_once_with("audio/cfg/getroomfavs/7/0/32", "getroomfavs_result")
    request.reset_mock()
    request.return_value = None
    await owner.async_play_room_favourite(7, 3)
    request.assert_awaited_once_with("audio/7/roomfav/play/3", None, is_current=None, on_send=None)


@pytest.mark.asyncio
async def test_native_handoff_keeps_required_empty_audio_path(monkeypatch):
    from unittest.mock import AsyncMock
    from custom_components.loxone.pyloxone_api import audioserver as wire

    owner = wire.AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "token"))
    assert hasattr(owner, "async_spotify_handoff"), "Explicit Spotify takeover missing"
    request = AsyncMock(return_value=None)
    monkeypatch.setattr(owner, "_async_request", request)
    await owner.async_spotify_handoff(7, "synthetic.owner")
    request.assert_awaited_once_with(
        "audio/7/serviceplay/spotify/synthetic.owner/", None, is_current=None, on_send=None
    )


@pytest.mark.asyncio
async def test_optional_result_send_keeps_socket_until_matching_command_echo(monkeypatch):
    import asyncio
    import json
    from unittest.mock import AsyncMock
    from custom_components.loxone.pyloxone_api import audioserver as wire

    owner = wire.AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "token"))
    command = "audio/7/roomfav/play/3"
    socket = AsyncMock()
    context = AsyncMock()
    context.__aenter__.return_value = socket
    monkeypatch.setattr(wire, "connect", lambda *args, **kwargs: context)
    monkeypatch.setattr(owner, "_authenticate", AsyncMock())
    reply = AsyncMock(side_effect=AssertionError("Never require the optional roomfav_result"))
    monkeypatch.setattr(owner, "_reply", reply)
    received = asyncio.Event()
    allow_echo = asyncio.Event()

    async def receive():
        received.set()
        await allow_echo.wait()
        return json.dumps({"command": command})  # Native BaseResponse, no optional result.

    socket.recv.side_effect = receive
    task = asyncio.create_task(owner._async_request(command, None))
    try:
        await asyncio.sleep(0)
        assert not task.done(), "Closing before the native command echo can discard the operation"
        await asyncio.wait_for(received.wait(), 1)
        context.__aexit__.assert_not_awaited()
        allow_echo.set()
        assert await task is None
        socket.send.assert_awaited_once_with(command)
        reply.assert_not_awaited()
        context.__aexit__.assert_awaited_once()
    finally:
        allow_echo.set()
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["native_error", "missing_echo", "wrong_echo"])
async def test_optional_result_requires_bounded_exact_error_free_command_echo(monkeypatch, failure):
    import asyncio
    import json
    from unittest.mock import AsyncMock
    from custom_components.loxone.pyloxone_api import audioserver as wire

    owner = wire.AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "token"), timeout=0.03)
    command = "audio/7/roomfav/play/3"
    socket = AsyncMock()
    context = AsyncMock()
    context.__aenter__.return_value = socket
    monkeypatch.setattr(wire, "connect", lambda *args, **kwargs: context)
    monkeypatch.setattr(owner, "_authenticate", AsyncMock())

    async def receive():
        if failure == "native_error":
            return json.dumps({"command": command, "error": "synthetic-private-native-detail"})
        if failure == "wrong_echo":
            await asyncio.sleep(0)
            return json.dumps({"command": "audio/8/roomfav/play/3"})
        await asyncio.Event().wait()
        return None

    socket.recv.side_effect = receive
    with pytest.raises(wire.AudioCommandError) as error:
        await owner._async_request(command, None)
    assert "synthetic-private-native-detail" not in str(error.value)
    socket.send.assert_awaited_once_with(command)
    context.__aexit__.assert_awaited_once()


def test_spotify_accounts_are_configured_healthy_exact_ids_only():
    from custom_components.loxone import audio_sources as sources

    assert hasattr(sources, "parse_spotify_accounts"), "Configured Spotify identity parser missing"
    payload = [
        {"cmd": "spotify", "id": "synthetic.owner", "configerror": False},
        {"cmd": "spotify", "id": "broken", "configerror": True},
        {"cmd": "soundsuit", "id": "other", "configerror": False},
    ]
    assert sources.parse_spotify_accounts(payload) == ("synthetic.owner",)
    for bad in [None, {}, [{"cmd": "spotify", "id": "owner/command", "configerror": False}]]:
        with pytest.raises(ValueError):
            sources.parse_spotify_accounts(bad)


def test_source_confirmation_retains_radio_mode_without_inventing_track_timing():
    from custom_components.loxone.pyloxone_api.audioserver import parse_audio_events

    row = parse_audio_events(
        {"audio_event": [{"playerid": 7, "audiopath": "tunein:station:synthetic", "mode": "play"}]}
    )[0]
    assert getattr(row, "native_mode", None) == "play"
    assert row.playback_mode is None and row.position is None


class Metadata:
    def __init__(self):
        self.listeners = set()
        self.set({"audiopath": "spotify:track:before", "mode": "stop"})

    def get(self, player):
        assert player == 7
        return self.row

    def async_add_listener(self, player, callback):
        self.listeners.add(callback)
        return lambda: self.listeners.discard(callback)

    def set(self, extra):
        from custom_components.loxone.pyloxone_api.audioserver import parse_audio_events

        self.row = None if extra is None else parse_audio_events({"audio_event": [{"playerid": 7, **extra}]})[0]
        for callback in tuple(self.listeners):
            callback()


def favourites():
    return [
        {
            "id": 7,
            "start": 0,
            "totalitems": 1,
            "items": [{"id": 3, "name": "Radio", "type": "tunein", "audiopath": "tunein:station:synthetic"}],
        }
    ]


@pytest.mark.asyncio
async def test_select_favourite_revalidates_identity_and_waits_for_exact_playing_content():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from custom_components.loxone import audio_sources as sources

    assert hasattr(sources, "async_select_favourite"), "Observed source-selection backend missing"
    metadata = Metadata()
    sent = asyncio.Event()
    writes = []

    async def play(player, favourite, *, is_current, on_send):
        assert is_current()
        on_send()
        writes.append((player, favourite))
        metadata.set({"audiopath": "tunein:station:wrong", "mode": "play"})
        sent.set()

    commands = SimpleNamespace(
        async_room_favourites=AsyncMock(return_value=favourites()),
        async_play_room_favourite=play,
        announcement_fences={},
        source_fences={},
    )
    choice = sources.parse_room_favourites(favourites(), 7)[0]
    task = asyncio.create_task(sources.async_select_favourite(commands, metadata, choice, is_available=lambda: True))
    await sent.wait()
    await asyncio.sleep(0)
    assert not task.done()
    metadata.set({"audiopath": "tunein:station:synthetic", "mode": "play"})
    await asyncio.wait_for(task, 0.2)
    assert writes == [(7, 3)] and not metadata.listeners and not commands.source_fences
    commands.async_room_favourites.assert_awaited_once_with(7)


@pytest.mark.asyncio
async def test_cancelled_source_send_cannot_overlap_until_exact_target_arrives():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from custom_components.loxone import audio_sources as sources
    from custom_components.loxone.pyloxone_api.audioserver import AudioCommandError

    assert hasattr(sources, "async_select_favourite"), "Observed source-selection backend missing"
    metadata = Metadata()
    sent = asyncio.Event()
    writes = []

    async def play(player, favourite, *, is_current, on_send):
        assert is_current()
        on_send()
        writes.append((player, favourite))
        sent.set()
        await asyncio.Future()

    commands = SimpleNamespace(
        async_room_favourites=AsyncMock(return_value=favourites()),
        async_play_room_favourite=play,
        announcement_fences={},
        source_fences={},
    )
    choice = sources.parse_room_favourites(favourites(), 7)[0]
    task = asyncio.create_task(sources.async_select_favourite(commands, metadata, choice, is_available=lambda: True))
    await sent.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(AudioCommandError):
        await sources.async_select_favourite(commands, metadata, choice, is_available=lambda: True)
    metadata.set(None)
    metadata.set({"audiopath": "spotify:track:before", "mode": "stop"})
    assert 7 in commands.source_fences and writes == [(7, 3)]
    metadata.set({"audiopath": "tunein:station:synthetic", "mode": "play"})
    assert not metadata.listeners and not commands.source_fences


@pytest.mark.asyncio
async def test_changed_favourite_or_unavailable_entity_prevents_content_write():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from custom_components.loxone import audio_sources as sources
    from custom_components.loxone.pyloxone_api.audioserver import AudioCommandError

    assert hasattr(sources, "async_select_favourite"), "Observed source-selection backend missing"
    metadata = Metadata()
    choice = sources.parse_room_favourites(favourites(), 7)[0]
    changed = favourites()
    changed[0]["items"][0]["audiopath"] = "tunein:station:changed"
    commands = SimpleNamespace(
        async_room_favourites=AsyncMock(return_value=changed),
        async_play_room_favourite=AsyncMock(),
        announcement_fences={},
        source_fences={},
    )
    with pytest.raises(AudioCommandError):
        await sources.async_select_favourite(commands, metadata, choice, is_available=lambda: True)
    commands.async_play_room_favourite.assert_not_awaited()
    commands.async_room_favourites.return_value = favourites()
    with pytest.raises(AudioCommandError):
        await sources.async_select_favourite(commands, metadata, choice, is_available=lambda: False)
    commands.async_play_room_favourite.assert_not_awaited()


@pytest.mark.asyncio
async def test_client_shutdown_releases_pending_source_fence_and_listener(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock
    from custom_components.loxone import audio_sources as sources
    from custom_components.loxone.pyloxone_api.audioserver import AudioServerCommands

    commands = AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "token"))
    metadata = Metadata()
    sent = asyncio.Event()
    monkeypatch.setattr(commands, "async_room_favourites", AsyncMock(return_value=favourites()))

    async def play(*args, is_current, on_send):
        assert is_current()
        on_send()
        sent.set()

    monkeypatch.setattr(commands, "async_play_room_favourite", play)
    choice = sources.parse_room_favourites(favourites(), 7)[0]
    task = asyncio.create_task(sources.async_select_favourite(commands, metadata, choice, is_available=lambda: True))
    await sent.wait()
    await commands.async_close()
    try:
        assert not commands.source_fences and not metadata.listeners
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_pending_source_prevents_announcement_before_upload(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from custom_components.loxone.audio_announcement import async_send_announcement
    from custom_components.loxone.pyloxone_api.audioserver import AudioCommandError
    from custom_components.loxone.audio_announcement import aiohttp_client

    monkeypatch.setattr(aiohttp_client, "async_get_clientsession", lambda hass: object())
    commands = SimpleNamespace(
        announcement_fences={},
        source_fences={7: lambda: None},
        async_upload_announcement=AsyncMock(),
        async_announce=AsyncMock(side_effect=AudioCommandError("synthetic stop")),
    )
    with pytest.raises(AudioCommandError):
        await async_send_announcement(SimpleNamespace(), commands, Metadata(), 7, b"wave", 0.2, 10)
    commands.async_upload_announcement.assert_not_awaited()


@pytest.mark.asyncio
async def test_already_playing_favourite_is_verified_without_restarting_it():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from custom_components.loxone import audio_sources as sources

    metadata = Metadata()
    metadata.set({"audiopath": "tunein:station:synthetic", "mode": "play"})
    commands = SimpleNamespace(
        async_room_favourites=AsyncMock(return_value=favourites()),
        async_play_room_favourite=AsyncMock(side_effect=AssertionError("Already selected; no restart")),
        announcement_fences={},
        source_fences={},
    )
    choice = sources.parse_room_favourites(favourites(), 7)[0]
    await sources.async_select_favourite(commands, metadata, choice, is_available=lambda: True)
    commands.async_play_room_favourite.assert_not_awaited()
    assert not commands.source_fences and not metadata.listeners


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["cancel", "transport"])
async def test_matching_feedback_during_uncertain_write_cannot_release_source_ownership(failure, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from custom_components.loxone import audio_sources as sources, audio_announcement as ann
    from custom_components.loxone.pyloxone_api.audioserver import AudioCommandError

    metadata = Metadata()
    entered = asyncio.Event()
    outcome = asyncio.get_running_loop().create_future()

    async def play(player, favourite, *, is_current, on_send):
        assert is_current()
        on_send()
        entered.set()
        await outcome

    commands = SimpleNamespace(
        async_room_favourites=AsyncMock(return_value=favourites()),
        async_play_room_favourite=play,
        announcement_fences={},
        source_fences={},
        async_upload_announcement=AsyncMock(),
        async_announce=AsyncMock(),
    )
    choice = sources.parse_room_favourites(favourites(), 7)[0]
    task = asyncio.create_task(sources.async_select_favourite(commands, metadata, choice, is_available=lambda: True))
    try:
        await asyncio.wait_for(entered.wait(), 0.2)
        metadata.set({"audiopath": "tunein:station:synthetic", "mode": "play"})
        assert 7 in commands.source_fences
        if failure == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            outcome.set_exception(AudioCommandError("Synthetic uncertain transport"))
            with pytest.raises(AudioCommandError):
                await task
        assert 7 in commands.source_fences
        monkeypatch.setattr(ann.aiohttp_client, "async_get_clientsession", lambda hass: object())
        with pytest.raises(AudioCommandError):
            await ann.async_send_announcement(SimpleNamespace(), commands, metadata, 7, b"wave", 0.2, 10)
        commands.async_upload_announcement.assert_not_awaited()
        metadata.set({"audiopath": "tunein:station:synthetic", "mode": "play"})
        assert not commands.source_fences and not metadata.listeners
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("unsupported_first", [False, True])
def test_duplicate_favourite_ids_are_rejected_even_across_unsupported_types(unsupported_first):
    from custom_components.loxone.audio_sources import parse_room_favourites

    supported = favourites()[0]["items"][0]
    unsupported = {"id": 3, "name": "Unsupported", "type": "spotify_track", "audiopath": "spotify:track:other"}
    items = [unsupported, supported] if unsupported_first else [supported, unsupported]
    with pytest.raises(ValueError):
        parse_room_favourites([{"id": 7, "start": 0, "totalitems": 2, "items": items}], 7)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["cancel", "transport"])
async def test_real_receiver_debounce_cannot_replay_pre_settlement_feedback(failure, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from custom_components.loxone import audio_sources as sources
    from custom_components.loxone.audio import AudioMetadataCoordinator
    from custom_components.loxone.pyloxone_api import audioserver as wire

    monkeypatch.setattr(wire, "_EVENT_END_DELAY", 0.02)
    metadata = AudioMetadataCoordinator("192.0.2.1")
    receiver = metadata._client._receiver

    def feed(path="spotify:track:before", mode="stop", eventype=0):
        row = wire.parse_audio_events(
            {"audio_event": [{"playerid": 7, "audiopath": path, "mode": mode, "eventype": eventype}]}
        )[0]
        row = receiver._apply(row)
        metadata._on_update((row,))

    feed()
    entered = asyncio.Event()
    outcome = asyncio.get_running_loop().create_future()

    async def play(player, favourite, *, is_current, on_send):
        assert is_current()
        on_send()
        entered.set()
        await outcome

    commands = SimpleNamespace(
        async_room_favourites=AsyncMock(return_value=favourites()),
        async_play_room_favourite=play,
        announcement_fences={},
        source_fences={},
    )
    task = asyncio.create_task(
        sources.async_select_favourite(
            commands, metadata, sources.parse_room_favourites(favourites(), 7)[0], is_available=lambda: True
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 0.2)
        feed("file:///synthetic-alarm.wav", "play", 100)
        feed("tunein:station:synthetic", "play")
        sample = metadata.get(7).received_at
        assert metadata.get(7).event_active is True
        if failure == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            outcome.set_exception(wire.AudioCommandError("Synthetic transport failure"))
            with pytest.raises(wire.AudioCommandError):
                await task
        await asyncio.sleep(0.04)
        assert metadata.get(7).event_active is False
        assert metadata.get(7).received_at is sample
        assert 7 in commands.source_fences
        feed("tunein:station:synthetic", "play")
        assert metadata.get(7).received_at is not sample
        assert not commands.source_fences and not metadata._listeners
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        receiver._reset()


@pytest.mark.asyncio
async def test_successful_echo_accepts_post_send_wire_feedback_in_either_order():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from custom_components.loxone import audio_sources as sources

    metadata = Metadata()
    entered = asyncio.Event()
    echo = asyncio.Event()

    async def play(player, favourite, *, is_current, on_send):
        assert is_current()
        on_send()
        metadata.set({"audiopath": "tunein:station:synthetic", "mode": "play"})
        entered.set()
        await echo.wait()

    commands = SimpleNamespace(
        async_room_favourites=AsyncMock(return_value=favourites()),
        async_play_room_favourite=play,
        announcement_fences={},
        source_fences={},
    )
    task = asyncio.create_task(
        sources.async_select_favourite(
            commands, metadata, sources.parse_room_favourites(favourites(), 7)[0], is_available=lambda: True
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 0.2)
        assert not task.done() and 7 in commands.source_fences
        echo.set()
        await asyncio.wait_for(task, 0.2)
        assert not commands.source_fences and not metadata.listeners
    finally:
        echo.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for release in tuple(commands.source_fences.values()):
            release()






