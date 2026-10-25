"""
Real HA lifecycle with fake transports and explicitly synthetic structure/events.

No household configuration, credentials, or real device captures are used.
"""

from __future__ import annotations

# Assert/magic fixture IDs, private lifecycle checks and stub exceptions are intentional.
# ruff: noqa: S101, INP001, PLR2004, SLF001, ARG001, TRY003, EM101

import asyncio
import copy
from datetime import timedelta
import json
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Self
from unittest.mock import ANY, AsyncMock

import pytest
import voluptuous as vol
from homeassistant.components.media_player import MediaPlayerEntityFeature
from homeassistant.const import Platform
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.translation import async_get_translations
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components import loxone
from custom_components.loxone import audio_announcement
from custom_components.loxone.const import DOMAIN, EVENT
from custom_components.loxone.coordinator import LoxoneCoordinator
from custom_components.loxone.pyloxone_api import audioserver

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from homeassistant.core import HomeAssistant

STRUCTURE = {
    "controls": {
        f"synthetic-zone-{player}": {
            "uuidAction": f"synthetic-zone-{player}",
            "name": "Duplicate zone name",
            "type": "AudioZoneV2",
            "details": {"playerid": player},
            "states": {"volume": f"volume-{player}", "playState": f"play-{player}"},
        }
        for player in (7, 8)
    },
    "rooms": {},
    "cats": {},
}


@pytest.fixture
async def audio_setup(
    hass: HomeAssistant, enable_custom_integrations: None, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[SimpleNamespace]:
    """Run the integration's actual setup and unload, replacing only transports."""
    opened = []
    closed = []
    queues = []
    apis = []

    class Socket:
        def __init__(self, uri: str) -> None:
            self.uri = uri
            self.queue = asyncio.Queue()
            queues.append(self.queue)

        async def __aenter__(self) -> Self:
            opened.append(self.uri)
            return self

        async def __aexit__(self, *_: object) -> None:
            closed.append(self.uri)

        async def __aiter__(self) -> AsyncIterator[str]:
            while True:
                message = await self.queue.get()
                if message is None:
                    return
                yield message

    async def miniserver_run(**_: Any) -> None:
        await asyncio.Future()

    async def first_refresh(coordinator: LoxoneCoordinator) -> None:
        coordinator.api = SimpleNamespace(
            run=miniserver_run,
            close=AsyncMock(),
            send_websocket_command=AsyncMock(),
            get_token_dict=lambda: {"token": "", "hash_alg": "", "valid_until": ""},
        )
        apis.append(coordinator.api)
        coordinator.miniserver = SimpleNamespace(
            lox_config=SimpleNamespace(json=copy.deepcopy(STRUCTURE)),
            miniserver_type=2,
        )
        coordinator._control_uuids = frozenset(STRUCTURE["controls"])

    monkeypatch.setattr(loxone, "LOXONE_PLATFORMS", [Platform.MEDIA_PLAYER])
    monkeypatch.setattr(LoxoneCoordinator, "async_config_entry_first_refresh", first_refresh)
    monkeypatch.setattr(audioserver, "connect", lambda uri, **_: Socket(uri))
    monkeypatch.setattr(
        audioserver.AudioServerCommands,
        "async_room_favourites",
        AsyncMock(side_effect=lambda player: [{"id": player, "start": 0, "totalitems": 0, "items": []}]),
    )

    monkeypatch.setattr(audioserver.AudioServerCommands, "async_source_inputs", AsyncMock(return_value=[]))
    monkeypatch.setattr(audioserver.AudioServerCommands, "async_recent_sources", AsyncMock(return_value={"items": [], "ts": 0}))
    monkeypatch.setattr(audioserver.AudioServerCommands, "async_service_accounts", AsyncMock(return_value=[]))
    monkeypatch.setattr(audioserver.AudioServerCommands, "async_search_capabilities", AsyncMock(return_value={"tunein": ["station", "custom"]}))
    monkeypatch.setattr(audioserver.AudioServerCommands, "async_radio_services", AsyncMock(return_value=[{"cmd": "world", "root": "root", "name": "World"}]))
    monkeypatch.setattr(audioserver.AudioServerCommands, "async_media_folder", AsyncMock(return_value=[{"start": 0, "totalitems": 0, "items": []}]))

    async def setup(
        host: str = "audio.example.invalid", *, title: str = "Synthetic Miniserver", playback: bool = False
    ) -> MockConfigEntry:
        entry = MockConfigEntry(
            domain=DOMAIN,
            title=title,
            version=4,
            options={
                "host": "miniserver.example.invalid",
                "port": 80,
                "username": "synthetic-user",
                "password": "synthetic-password",
                "audioserver_host": host,
                **({"audioserver_playback": True} if playback else {}),
            },
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return entry

    entries = []

    async def tracked_setup(*args: Any, **kwargs: Any) -> MockConfigEntry:
        entry = await setup(*args, **kwargs)
        entries.append(entry)
        return entry

    yield SimpleNamespace(setup=tracked_setup, opened=opened, closed=closed, queues=queues, apis=apis)
    for entry in entries:
        await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def zone_entity_id(hass: HomeAssistant, player: int | str) -> str | None:
    """Resolve the actual registry identity, never an entity-name assumption."""
    return er.async_get(hass).async_get_entity_id("media_player", DOMAIN, f"synthetic-zone-{player}")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["play", "stop"])
@pytest.mark.parametrize("position", [0, 0.125, 180])
async def test_seek_service_applies_confirmed_offset_without_implicit_play(
    hass: HomeAssistant,
    audio_setup: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    position: float,
) -> None:
    """A confirmed zero/fraction/end must bypass passive placeholder filtering."""
    expected = min(position, 179)

    async def observed_seek(player: int, seconds: float, **kwargs: Any) -> float:
        assert kwargs["is_current"]()
        kwargs["on_send"]()
        asyncio.get_running_loop().call_soon(
            audio_setup.queues[0].put_nowait,
            json.dumps({"audio_event": [{**row, "time": expected, "mode": "play"}]}),
        )
        return expected

    seek = AsyncMock(side_effect=observed_seek)
    play = AsyncMock()
    monkeypatch.setattr(audioserver.AudioServerCommands, "async_seek", seek)
    monkeypatch.setattr(audioserver.AudioServerCommands, "async_execute", play)
    await audio_setup.setup(playback=True)
    first = zone_entity_id(hass, 7)
    hass.bus.async_fire(EVENT, {"play-7": 2 if mode == "play" else 0})
    row = {
        "playerid": 7,
        "mode": mode,
        "audiopath": "spotify:track:synthetic",
        "time": 63.25,
        "duration": 180,
        "pbr": 32,
    }
    await audio_setup.queues[0].put(json.dumps({"audio_event": [row]}))
    await hass.async_block_till_done()
    before = hass.states.get(first).state
    assert hass.states.get(first).attributes["supported_features"] & MediaPlayerEntityFeature.SEEK
    await hass.services.async_call(
        "media_player", "media_seek", {"entity_id": first, "seek_position": position}, blocking=True
    )
    await hass.async_block_till_done()
    seek.assert_awaited_once()
    assert seek.await_args is not None
    assert seek.await_args.args == (7, expected)
    assert not seek.await_args.kwargs["is_current"](), "Settled seeks cannot be replayed"
    play.assert_not_awaited()
    assert hass.states.get(first).attributes["media_position"] == expected
    assert hass.states.get(first).state == before
    # Repeated observed anchors and passive zero placeholders cannot undo the
    # observed seek. A genuinely changed positive native position is not an
    # identifiable replay: it can be an independent seek from another client.
    for offset in (expected, 0, expected):
        await audio_setup.queues[0].put(json.dumps({"audio_event": [{**row, "time": offset}]}))
        await hass.async_block_till_done()
    assert expected <= hass.states.get(first).attributes["media_position"] <= expected + 0.5
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("pbr", [None, 0, 31, True, "32", -1])
async def test_seek_is_withheld_without_explicit_valid_capability(
    hass: HomeAssistant,
    audio_setup: SimpleNamespace,
    pbr: Any,
) -> None:
    """Unknown or denying capabilities never become an optimistic seek button."""
    await audio_setup.setup(playback=True)
    first = zone_entity_id(hass, 7)
    row = {
        "playerid": 7,
        "mode": "play",
        "audiopath": "spotify:track:synthetic",
        "time": 12,
        "duration": 180,
        "pbr": pbr,
    }
    await audio_setup.queues[0].put(json.dumps({"audio_event": [row]}))
    await hass.async_block_till_done()
    entity = hass.data["media_player"].get_entity(first)
    assert not entity.supported_features & MediaPlayerEntityFeature.SEEK
    with pytest.raises(HomeAssistantError):
        await entity.async_media_seek(12)


@pytest.mark.asyncio
@pytest.mark.parametrize("return_to_original", [False, True])
async def test_seek_rejects_stale_ack_and_preserves_artwork_on_capability_updates(
    hass: HomeAssistant,
    audio_setup: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    *,
    return_to_original: bool,
) -> None:
    """Capability feedback is not new art; an old track ACK cannot affect a new one."""
    await audio_setup.setup(playback=True)
    first = zone_entity_id(hass, 7)
    row = {
        "playerid": 7,
        "mode": "stop",
        "audiopath": "library:local:track:synthetic",
        "time": 12,
        "duration": 180,
        "pbr": 32,
        "coverurl": "/synthetic.jpg",
    }

    async def frame(extra: dict) -> None:
        await audio_setup.queues[0].put(json.dumps({"audio_event": [{**row, **extra}]}))
        await hass.async_block_till_done()

    await frame({})
    entity = hass.data["media_player"].get_entity(first)
    artwork = entity.media_image_hash
    assert artwork is not None
    track_id = entity.extra_state_attributes["audio_track_id"]
    assert len(track_id) == 64
    await frame({"pbr": 33})
    assert entity.media_image_hash == artwork
    assert entity.extra_state_attributes["audio_track_id"] == track_id

    async def changed_track(*_: Any, **_kwargs: Any) -> int:
        await frame({"audiopath": "library:local:track:other", "time": 30})
        if return_to_original:
            await frame({})
        assert not _kwargs["is_current"]()
        return 0

    monkeypatch.setattr(audioserver.AudioServerCommands, "async_seek", changed_track)
    with pytest.raises(HomeAssistantError):
        await entity.async_media_seek(0)
    assert entity.media_position == (12 if return_to_original else 30)
    assert entity.extra_state_attributes["audio_track_id"] != track_id


@pytest.mark.parametrize(("service", "action"), [("media_play", "play"), ("media_pause", "pause")])
@pytest.mark.asyncio
async def test_optin_play_pause_uses_exact_audio_player_without_native_start(
    hass: HomeAssistant, audio_setup: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, service: str, action: str
) -> None:
    """Optin play pause uses exact audio player without native start."""
    command = AsyncMock()
    monkeypatch.setattr(audioserver.AudioServerCommands, "async_execute", command)
    await audio_setup.setup(playback=True)
    first = zone_entity_id(hass, 7)
    before = hass.states.get(first).state
    await hass.services.async_call("media_player", service, {"entity_id": first}, blocking=True)
    command.assert_awaited_once_with(7, action, is_current=ANY)
    assert command.await_args.kwargs["is_current"]()
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()
    assert hass.states.get(first).state == before


@pytest.mark.asyncio
async def test_playback_option_uses_current_token_and_is_closed_on_unload(
    hass: HomeAssistant, audio_setup: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Playback option uses current token and is closed on unload."""
    entry = await audio_setup.setup()
    form = await hass.config_entries.options.async_init(entry.entry_id)
    assert "audioserver_playback" in {str(key) for key in form["data_schema"].schema}
    result = await hass.config_entries.options.async_configure(
        form["flow_id"], {**entry.options, "audioserver_playback": True}
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    coordinator = hass.data[DOMAIN][entry.entry_id]
    client = coordinator.audio_commands
    audio_setup.apis[-1].get_token_dict = lambda: {"token": "synthetic-current-token"}
    assert client._credentials() == ("synthetic-user", "synthetic-current-token")
    audio_setup.apis[-1].get_token_dict = lambda: {"token": "synthetic-refreshed-token"}
    assert client._credentials() == ("synthetic-user", "synthetic-refreshed-token")
    closed = AsyncMock()
    monkeypatch.setattr(client, "async_close", closed)
    assert await hass.config_entries.async_unload(entry.entry_id)
    closed.assert_awaited_once()
    assert coordinator.audio_commands is None


@pytest.mark.asyncio
async def test_playback_option_requires_host(hass: HomeAssistant, audio_setup: SimpleNamespace) -> None:
    """Playback option requires host."""
    entry = await audio_setup.setup()
    form = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        form["flow_id"], {**entry.options, "audioserver_host": "", "audioserver_playback": True}
    )
    assert result["type"] == "form"
    assert result["errors"]["base"] == "audioserver_playback_requires_host"
    assert not entry.options.get("audioserver_playback")


@pytest.mark.parametrize("failure", ["missing_token", "negative_ack", "invalid_player", "missing_host"])
@pytest.mark.asyncio
async def test_enabled_playback_failure_never_falls_back_to_room_start(
    hass: HomeAssistant, audio_setup: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """Enabled playback failure never falls back to room start."""
    if failure == "invalid_player":
        monkeypatch.setitem(STRUCTURE["controls"]["synthetic-zone-7"]["details"], "playerid", None)
    if failure == "negative_ack":
        monkeypatch.setattr(
            audioserver.AudioServerCommands,
            "async_execute",
            AsyncMock(side_effect=audioserver.AudioCommandError("Synthetic negative acknowledgement")),
        )
    await audio_setup.setup(host="" if failure == "missing_host" else "audio.example.invalid", playback=True)
    first = zone_entity_id(hass, 7)
    with pytest.raises(HomeAssistantError) as failure_info:
        await hass.services.async_call("media_player", "media_play", {"entity_id": first}, blocking=True)
    assert failure_info.value.translation_domain == DOMAIN
    assert failure_info.value.translation_key == (
        "audioserver_playback_unavailable" if failure == "missing_host" else "audioserver_playback_failed"
    )
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_enabled_playback_keeps_volume_native(
    hass: HomeAssistant, audio_setup: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Enabled playback keeps volume native."""
    command = AsyncMock()
    monkeypatch.setattr(audioserver.AudioServerCommands, "async_execute", command)
    await audio_setup.setup(playback=True)
    first = zone_entity_id(hass, 7)
    hass.bus.async_fire(EVENT, {"play-7": 1, "volume-7": 36})
    await hass.async_block_till_done()
    await hass.services.async_call("media_player", "media_play", {"entity_id": first}, blocking=True)
    assert hass.states.get(first).attributes["volume_level"] == 0.36
    await hass.services.async_call(
        "media_player", "volume_set", {"entity_id": first, "volume_level": 0.41}, blocking=True
    )
    await hass.async_block_till_done()
    audio_setup.apis[0].send_websocket_command.assert_awaited_once_with("synthetic-zone-7", "volume/41")
    command.assert_awaited_once_with(7, "play", is_current=ANY)
    assert command.await_args.kwargs["is_current"]()


@pytest.mark.asyncio
@pytest.mark.parametrize("radio_path", ["loxoneradio:stream:synthetic", "tunein:station:synthetic"])
@pytest.mark.parametrize(
    "following_path",
    ["spotify:track:synthetic", "library:local:track:synthetic", "airplay", "linein:synthetic", ""],
)
async def test_radio_skip_features_follow_exact_zone_source(
    hass: HomeAssistant, audio_setup: SimpleNamespace, following_path: str, radio_path: str
) -> None:
    """Radio providers remove skip only on their zone; non-radio restores it."""
    await audio_setup.setup()
    first = zone_entity_id(hass, 7)
    second = zone_entity_id(hass, 8)
    baseline = hass.states.get(first).attributes["supported_features"]
    skip = MediaPlayerEntityFeature.NEXT_TRACK | MediaPlayerEntityFeature.PREVIOUS_TRACK
    assert baseline & skip == skip
    hass.bus.async_fire(EVENT, {"play-7": 2, "play-8": 2, "volume-7": 36})
    await audio_setup.queues[0].put(
        json.dumps({"audio_event": [{"playerid": 7, "mode": "play", "audiopath": radio_path}]})
    )
    await hass.async_block_till_done()
    radio = hass.states.get(first)
    assert radio.attributes["source"] == ("TuneIn" if radio_path.startswith("tunein:") else "Loxone Radio")
    assert radio.attributes["supported_features"] == baseline & ~skip
    assert radio.state == "playing"
    assert radio.attributes["volume_level"] == 0.36
    assert hass.states.get(second).attributes["supported_features"] == baseline
    await audio_setup.queues[0].put(
        json.dumps({"audio_event": [{"playerid": 7, "mode": "play", "audiopath": following_path}]})
    )
    await hass.async_block_till_done()
    assert hass.states.get(first).attributes["supported_features"] == baseline
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_actual_ha_entities_receive_exact_player_metadata(
    hass: HomeAssistant, audio_setup: SimpleNamespace
) -> None:
    """Same display names must not route metadata to the wrong AudioZoneV2."""
    await audio_setup.setup()
    # This assertion fails before the optional connector is wired into setup.
    assert audio_setup.opened == ["ws://audio.example.invalid:7091/"]
    first = zone_entity_id(hass, 7)
    second = zone_entity_id(hass, 8)
    assert first != second
    # HA intentionally hides track attributes for OFF players. Playback state
    # remains authoritative on the independent Miniserver event path.
    hass.bus.async_fire(EVENT, {"play-7": 2, "play-8": 2})
    await hass.async_block_till_done()
    assert hass.states.get(first).state == "playing"
    await audio_setup.queues[0].put(
        json.dumps(
            {
                "audio_event": [
                    {
                        "playerid": 7,
                        "title": "Synthetic track",
                        "artist": "Synthetic artist",
                        "album": "Synthetic album",
                        "audiopath": "spotify:track:synthetic",
                    }
                ]
            }
        )
    )
    await hass.async_block_till_done()
    attributes = hass.states.get(first).attributes
    assert attributes["media_title"] == "Synthetic track"
    assert attributes["media_artist"] == "Synthetic artist"
    assert attributes["media_album_name"] == "Synthetic album"
    assert attributes["source"] == "Spotify"
    assert "media_title" not in hass.states.get(second).attributes
    assert len(audio_setup.opened) == 1


@pytest.mark.asyncio
async def test_artwork_is_resolved_on_the_configured_audio_origin(
    hass: HomeAssistant, audio_setup: SimpleNamespace
) -> None:
    """Relative covers use the Audioserver, never the Miniserver's address."""
    await audio_setup.setup()
    first = zone_entity_id(hass, 7)
    hass.bus.async_fire(EVENT, {"play-7": 2})
    await audio_setup.queues[0].put(
        '{"audio_event":[{"playerid":7,"title":"Artwork test","coverurl":"/covers/synthetic.jpg"}]}'
    )
    await hass.async_block_till_done()
    entity = hass.data["media_player"].get_entity(first)
    assert entity.media_image_url == "http://audio.example.invalid:7091/covers/synthetic.jpg"
    assert hass.states.get(first).attributes["entity_picture"].startswith("/api/media_player_proxy/")


@pytest.mark.asyncio
async def test_new_track_invalidates_artwork_cache_even_with_the_same_url(
    hass: HomeAssistant, audio_setup: SimpleNamespace
) -> None:
    """Some servers reuse a player cover URL across tracks."""
    await audio_setup.setup()
    first = zone_entity_id(hass, 7)
    hass.bus.async_fire(EVENT, {"play-7": 2})
    hashes = []
    for title in ("First synthetic track", "Second synthetic track"):
        await audio_setup.queues[0].put(
            json.dumps({"audio_event": [{"playerid": 7, "title": title, "coverurl": "/covers/player-7.jpg"}]})
        )
        await hass.async_block_till_done()
        hashes.append(hass.data["media_player"].get_entity(first).media_image_hash)
    assert hashes[0] != hashes[1]


@pytest.mark.asyncio
async def test_options_flow_can_enable_then_disable_metadata(hass: HomeAssistant, audio_setup: SimpleNamespace) -> None:
    """The real options flow reloads the entry; blank host restores opt-out."""
    entry = await audio_setup.setup(host="")
    assert audio_setup.opened == []
    form = await hass.config_entries.options.async_init(entry.entry_id)
    assert "audioserver_host" in {str(key) for key in form["data_schema"].schema}
    result = await hass.config_entries.options.async_configure(
        form["flow_id"],
        user_input={**entry.options, "audioserver_host": "audio.example.invalid"},
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert entry.options["audioserver_host"] == "audio.example.invalid"
    assert audio_setup.opened == ["ws://audio.example.invalid:7091/"]
    form = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        form["flow_id"], user_input={**entry.options, "audioserver_host": ""}
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert not entry.options.get("audioserver_host")
    assert audio_setup.closed == audio_setup.opened
    assert len(audio_setup.opened) == 1


@pytest.mark.asyncio
async def test_options_reject_invalid_audio_host_without_reloading(
    hass: HomeAssistant, audio_setup: SimpleNamespace
) -> None:
    """Optional metadata must not accept URLs, credentials or custom paths."""
    entry = await audio_setup.setup(host="")
    form = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        form["flow_id"], user_input={**entry.options, "audioserver_host": "ws://user:password@audio/bad"}
    )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_audioserver_host"}
    await hass.async_block_till_done()
    assert not entry.options.get("audioserver_host")
    assert audio_setup.opened == []


@pytest.mark.asyncio
async def test_invalid_saved_audio_option_keeps_existing_players(
    hass: HomeAssistant, audio_setup: SimpleNamespace
) -> None:
    """Even bypassed/old invalid options cannot take down normal media controls."""
    await audio_setup.setup(host="ws://not-a-bare-host")
    first = zone_entity_id(hass, 7)
    assert first is not None
    assert hass.states.get(first) is not None
    assert audio_setup.opened == []
    await hass.services.async_call("media_player", "media_play", {"entity_id": first}, blocking=True)
    await hass.async_block_till_done()
    audio_setup.apis[0].send_websocket_command.assert_awaited_once_with("synthetic-zone-7", "play")


@pytest.mark.asyncio
async def test_coordinator_cleanup_explicitly_closes_optional_audio(
    hass: HomeAssistant, audio_setup: SimpleNamespace
) -> None:
    """Connection teardown does not rely solely on HA's eventual task sweep."""
    entry = await audio_setup.setup()
    coordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_cleanup()
    assert audio_setup.closed == audio_setup.opened
    assert coordinator.audio_metadata is None
    audio_setup.apis[0].close.assert_awaited_once()


@pytest.mark.asyncio
async def test_starting_shared_listener_twice_does_not_duplicate_connections(
    hass: HomeAssistant, audio_setup: SimpleNamespace
) -> None:
    """There is one task for all zones of an entry, even if start is repeated."""
    entry = await audio_setup.setup()
    audio = hass.data[DOMAIN][entry.entry_id].audio_metadata
    audio.async_start(hass, entry)
    audio.async_start(hass, entry)
    await hass.async_block_till_done()
    assert audio_setup.opened == ["ws://audio.example.invalid:7091/"]


@pytest.mark.asyncio
async def test_music_hint_is_removed_on_event_unknown_and_disconnect(
    hass: HomeAssistant, audio_setup: SimpleNamespace
) -> None:
    """Exercise the real HA state path, not an attribute-only surrogate."""
    await audio_setup.setup()
    first = zone_entity_id(hass, 7)
    hass.bus.async_fire(EVENT, {"play-7": 2, "volume-7": 36})
    for row, expected in [
        ({"artist": "Synthetic artist", "album": "Synthetic album"}, "music"),
        ({"eventype": 3, "mode": "play", "title": "Synthetic TTS"}, None),
        ({"audiopath": "spotify:track:synthetic"}, "music"),
        ({"title": "Unknown title only"}, None),
        ({"audiopath": "airplay", "type": 7, "mode": "play"}, None),
    ]:
        await audio_setup.queues[0].put(json.dumps({"audio_event": [{"playerid": 7, **row}]}))
        await hass.async_block_till_done()
        assert hass.states.get(first).attributes.get("media_content_type") == expected
        assert hass.states.get(first).attributes["volume_level"] == 0.36
    await audio_setup.queues[0].put(None)
    await hass.async_block_till_done()
    assert "media_content_type" not in hass.states.get(first).attributes
    assert hass.states.get(first).state == "playing"


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["en", "de", "cs"])
async def test_audio_translation_keys_exist_and_load_in_real_ha(
    hass: HomeAssistant, enable_custom_integrations: None, language: str
) -> None:
    """Each shipped language supplies all added audio labels/errors, not fallback English."""
    raw = json.loads((Path(loxone.__file__).parent / "translations" / f"{language}.json").read_text())
    for category, step in (("config", "user"), ("options", "init")):
        labels = await async_get_translations(hass, language, category, {DOMAIN})
        for key in ("audioserver_host", "audioserver_playback"):
            assert raw[category]["step"][step]["data"][key]
            label = f"component.loxone.{category}.step.{step}.data.{key}"
            assert labels[label] == raw[category]["step"][step]["data"][key]
        for key in ("invalid_audioserver_host", "audioserver_playback_requires_host"):
            assert raw[category]["error"][key]
            assert labels[f"component.loxone.{category}.error.{key}"] == raw[category]["error"][key]
    errors = await async_get_translations(hass, language, "exceptions", {DOMAIN})
    for key in ("audioserver_playback_failed", "audioserver_playback_unavailable"):
        assert errors[f"component.loxone.exceptions.{key}.message"] == raw["exceptions"][key]["message"]


@pytest.mark.asyncio
async def test_optional_audio_fields_have_real_ha_ui_translations(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Both setup and options forms need a label and a useful validation error."""
    for category, step in (("config", "user"), ("options", "init")):
        labels = await async_get_translations(hass, "en", category, {DOMAIN})
        label = f"component.loxone.{category}.step.{step}.data.audioserver_host"
        error = f"component.loxone.{category}.error.invalid_audioserver_host"
        assert label in labels
        assert "optional" in labels[label].lower()
        assert error in labels


@pytest.mark.asyncio
async def test_disconnect_clears_metadata_without_affecting_controls(
    hass: HomeAssistant, audio_setup: SimpleNamespace
) -> None:
    """An optional socket loss must not mark the native player unavailable."""
    await audio_setup.setup()
    first = zone_entity_id(hass, 7)
    hass.bus.async_fire(EVENT, {"play-7": 2, "volume-7": 36})
    await audio_setup.queues[0].put(
        '{"audio_event":[{"playerid":7,"title":"Before disconnect","audiopath":"spotify:synthetic"}]}'
    )
    await hass.async_block_till_done()
    assert hass.states.get(first).attributes["media_title"] == "Before disconnect"
    await audio_setup.queues[0].put(None)
    await hass.async_block_till_done()
    state = hass.states.get(first)
    assert "media_title" not in state.attributes
    assert "source" not in state.attributes
    assert state.state == "playing"
    assert state.attributes["volume_level"] == 0.36
    await hass.services.async_call("media_player", "media_pause", {"entity_id": first}, blocking=True)
    await hass.async_block_till_done()
    audio_setup.apis[0].send_websocket_command.assert_awaited_once_with("synthetic-zone-7", "pause")


@pytest.mark.asyncio
async def test_reload_keeps_entity_ids_and_replaces_all_subscriptions(
    hass: HomeAssistant, audio_setup: SimpleNamespace
) -> None:
    """Reload closes the old socket and does not retain old entities/listeners."""
    entry = await audio_setup.setup()
    first = zone_entity_id(hass, 7)
    old_audio = hass.data[DOMAIN][entry.entry_id].audio_metadata
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    new_audio = hass.data[DOMAIN][entry.entry_id].audio_metadata
    assert new_audio is not old_audio
    assert old_audio._listeners == {}
    assert len(new_audio._listeners) == 2
    assert len(audio_setup.opened) == 2
    assert len(audio_setup.closed) == 1
    assert zone_entity_id(hass, 7) == first
    hass.bus.async_fire(EVENT, {"play-7": 2})
    await audio_setup.queues[1].put('{"audio_event":[{"playerid":7,"title":"After reload"}]}')
    await hass.async_block_till_done()
    assert hass.states.get(first).attributes["media_title"] == "After reload"
    assert old_audio.get(7) is None


@pytest.mark.asyncio
async def test_unavailable_audio_does_not_block_setup_or_native_commands(
    hass: HomeAssistant, audio_setup: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Connection refusal is background metadata failure, not core unavailability."""

    def refuse(*_: Any, **__: Any) -> None:
        raise OSError("synthetic connection refused")

    monkeypatch.setattr(audioserver, "connect", refuse)
    entry = await audio_setup.setup()
    first = zone_entity_id(hass, 7)
    assert hass.data[DOMAIN][entry.entry_id].connection_available
    assert hass.states.get(first).state != "unavailable"
    await hass.services.async_call("media_player", "media_play", {"entity_id": first}, blocking=True)
    await hass.async_block_till_done()
    audio_setup.apis[0].send_websocket_command.assert_awaited_once_with("synthetic-zone-7", "play")


@pytest.mark.asyncio
async def test_multiple_entries_keep_player_ids_and_connections_isolated(
    hass: HomeAssistant, audio_setup: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same numeric player ID on another server is not the same player."""
    first_entry = await audio_setup.setup()
    second_structure = copy.deepcopy(STRUCTURE)
    second_controls = {}
    for key, control in second_structure["controls"].items():
        control["uuidAction"] += "-b"
        control["states"] = {name: value + "-b" for name, value in control["states"].items()}
        second_controls[key + "-b"] = control
    second_structure["controls"] = second_controls
    monkeypatch.setitem(globals(), "STRUCTURE", second_structure)
    second_entry = await audio_setup.setup(host="second-audio.example.invalid", title="Synthetic Miniserver B")
    first = zone_entity_id(hass, 7)
    second = zone_entity_id(hass, "7-b")
    hass.bus.async_fire(EVENT, {"play-7": 2, "play-7-b": 2})
    await audio_setup.queues[0].put(
        '{"audio_event":[{"playerid":7,"title":"First server track","eventype":100,"mode":"play"}]}'
    )
    await hass.async_block_till_done()
    assert hass.states.get(first).attributes["media_title"] == "First server track"
    assert "media_title" not in hass.states.get(second).attributes
    assert hass.states.get(first).attributes["audio_event"] == "alarm"
    assert hass.states.get(second).attributes["audio_event_active"] is None
    await audio_setup.queues[0].put('{"audio_event":[{"playerid":7}]}')
    await audio_setup.queues[1].put(
        '{"audio_event":[{"playerid":7,"title":"Second server track","eventype":3,"mode":"play"}]}'
    )
    await hass.async_block_till_done()
    old_audio = hass.data[DOMAIN][first_entry.entry_id].audio_metadata
    timers = tuple(old_audio._client._receiver._end_timers.values())
    assert len(timers) == 1
    assert await hass.config_entries.async_unload(first_entry.entry_id)
    await hass.async_block_till_done()
    assert audio_setup.closed == ["ws://audio.example.invalid:7091/"]
    assert all(timer.cancelled() for timer in timers)
    assert hass.states.get(second).attributes["media_title"] == "Second server track"
    assert hass.states.get(second).attributes["audio_event"] == "tts"
    assert hass.states.get(second).attributes["audio_event_active"] is True
    assert hass.data[DOMAIN][second_entry.entry_id].audio_metadata.get(7).title == "Second server track"
    await hass.services.async_call("media_player", "media_pause", {"entity_id": second}, blocking=True)
    await hass.async_block_till_done()
    audio_setup.apis[1].send_websocket_command.assert_awaited_once_with("synthetic-zone-7-b", "pause")
    audio_setup.apis[0].send_websocket_command.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("details", [None, {}, {"playerid": True}, {"playerid": 7.5}, {"playerid": "wrong"}])
async def test_missing_or_invalid_player_mapping_preserves_native_zone(
    hass: HomeAssistant, audio_setup: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, details: object
) -> None:
    """Never infer a player ID from a name, order, or malformed structure."""
    monkeypatch.setitem(STRUCTURE["controls"]["synthetic-zone-7"], "details", details)
    await audio_setup.setup()
    first = zone_entity_id(hass, 7)
    hass.bus.async_fire(EVENT, {"play-7": 2})
    await audio_setup.queues[0].put('{"audio_event":[{"playerid":7,"title":"Must not attach"}]}')
    await hass.async_block_till_done()
    assert hass.states.get(first).state == "playing"
    assert "media_title" not in hass.states.get(first).attributes
    assert "audio_event" not in hass.states.get(first).attributes
    assert "audio_event_active" not in hass.states.get(first).attributes


@pytest.mark.asyncio
async def test_audio_event_attributes_are_per_zone_and_preserve_controls(
    hass: HomeAssistant, audio_setup: SimpleNamespace
) -> None:
    """Target activity is visible even with duplicate names and independent native state."""
    await audio_setup.setup()
    first = zone_entity_id(hass, 7)
    second = zone_entity_id(hass, 8)
    assert hass.states.get(first).attributes["audio_event_active"] is None
    hass.bus.async_fire(EVENT, {"play-7": 2, "play-8": 2, "volume-7": 36})
    await audio_setup.queues[0].put(
        json.dumps(
            {
                "audio_event": [
                    {"playerid": 7, "eventype": 3, "mode": "play", "title": "Synthetic TTS"},
                    {"playerid": 8, "eventype": 3, "mode": "stop", "title": "Synthetic TTS"},
                ]
            }
        )
    )
    await hass.async_block_till_done()
    state = hass.states.get(first)
    assert state.attributes["audio_event"] == "tts"
    assert state.attributes["audio_event_active"] is True
    assert state.attributes["uuid"] == "synthetic-zone-7"
    assert state.attributes["platform"] == "loxone"
    assert state.attributes["volume_level"] == 0.36
    assert state.state == "playing"
    assert hass.states.get(second).attributes["audio_event_active"] is False
    assert hass.states.get(second).attributes["audio_event"] is None
    assert "media_title" not in hass.states.get(second).attributes
    await hass.services.async_call("media_player", "media_pause", {"entity_id": first}, blocking=True)
    await hass.async_block_till_done()
    audio_setup.apis[0].send_websocket_command.assert_awaited_once_with("synthetic-zone-7", "pause")
    await audio_setup.queues[0].put('{"audio_event":[{"playerid":7,"mode":"stop"}]}')
    await hass.async_block_till_done()
    assert hass.states.get(first).attributes["audio_event_active"] is False
    assert hass.states.get(first).attributes["audio_event"] is None


@pytest.mark.asyncio
async def test_alarm_end_timer_updates_real_ha_without_another_frame(
    hass: HomeAssistant, audio_setup: SimpleNamespace
) -> None:
    """The actual loop callback, not just parsing, must publish the stable end."""
    await audio_setup.setup()
    first = zone_entity_id(hass, 7)
    await audio_setup.queues[0].put('{"audio_event":[{"playerid":7,"eventype":100,"mode":"play"}]}')
    await hass.async_block_till_done()
    assert hass.states.get(first).attributes["audio_event"] == "alarm"
    await audio_setup.queues[0].put(
        '{"audio_event":[{"playerid":7,"mode":"stop","title":"Stable track","coverurl":"/covers/stable.jpg"}]}'
    )
    await hass.async_block_till_done()
    assert hass.states.get(first).attributes["audio_event_active"] is True
    entity = hass.data["media_player"].get_entity(first)
    before_hash = entity.media_image_hash
    assert before_hash is not None
    await asyncio.sleep(1.55)
    await hass.async_block_till_done()
    assert hass.states.get(first).attributes["audio_event_active"] is False
    assert hass.states.get(first).attributes["audio_event"] is None
    assert entity.media_image_hash == before_hash


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["disconnect", "reload", "unload"])
async def test_pending_alarm_timer_is_cancelled_by_ha_lifecycle(
    hass: HomeAssistant, audio_setup: SimpleNamespace, action: str
) -> None:
    """Exercise real teardown with an outstanding timer, not only idle sockets."""
    entry = await audio_setup.setup()
    first = zone_entity_id(hass, 7)
    old_audio = hass.data[DOMAIN][entry.entry_id].audio_metadata
    await audio_setup.queues[0].put('{"audio_event":[{"playerid":7,"eventype":100,"mode":"play"}]}')
    await hass.async_block_till_done()
    await audio_setup.queues[0].put('{"audio_event":[{"playerid":7,"mode":"stop"}]}')
    await hass.async_block_till_done()
    receiver = old_audio._client._receiver
    timers = tuple(receiver._end_timers.values())
    assert len(timers) == 1
    assert hass.states.get(first).attributes["audio_event_active"] is True
    if action == "disconnect":
        await audio_setup.queues[0].put(None)
    elif action == "reload":
        assert await hass.config_entries.async_reload(entry.entry_id)
    else:
        assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert receiver._end_timers == {}
    assert all(timer.cancelled() for timer in timers)
    assert old_audio.get(7) is None
    if action != "unload":
        assert hass.states.get(first).attributes["audio_event_active"] is None
        assert hass.states.get(first).attributes["audio_event"] is None
        assert hass.states.get(first).state != "unavailable"
    if action != "disconnect":
        assert old_audio._listeners == {}


@pytest.mark.asyncio
async def test_event_attributes_absent_when_listener_is_disabled(
    hass: HomeAssistant, audio_setup: SimpleNamespace
) -> None:
    """Opt-out remains native-only, not a permanently unknown optional feature."""
    await audio_setup.setup(host="")
    first = zone_entity_id(hass, 7)
    assert "audio_event" not in hass.states.get(first).attributes
    assert "audio_event_active" not in hass.states.get(first).attributes


@pytest.mark.asyncio
async def test_timed_track_reaches_ha_without_advertising_or_sending_seek(
    hass: HomeAssistant, audio_setup: SimpleNamespace
) -> None:
    """The first seeking slice is useful passive timing, not a new control."""
    await audio_setup.setup()
    first = zone_entity_id(hass, 7)
    second = zone_entity_id(hass, 8)
    hass.bus.async_fire(EVENT, {"play-7": 2, "play-8": 2, "volume-7": 36})
    before = dt_util.utcnow()
    await audio_setup.queues[0].put(
        json.dumps(
            {
                "audio_event": [
                    {
                        "playerid": 7,
                        "mode": "play",
                        "audiopath": "spotify:track:synthetic",
                        "title": "Timed track",
                        "time": 63.25,
                        "duration": 180.5,
                    }
                ]
            }
        )
    )
    await hass.async_block_till_done()
    entity = hass.data["media_player"].get_entity(first)
    assert entity.media_position == 63.25
    assert entity.media_duration == 180.5
    assert before <= entity.media_position_updated_at <= dt_util.utcnow()
    attributes = hass.states.get(first).attributes
    assert attributes["media_position"] == 63.25
    assert attributes["media_duration"] == 180.5
    assert attributes["media_position_updated_at"] == entity.media_position_updated_at
    assert attributes["volume_level"] == 0.36
    assert hass.states.get(first).state == "playing"
    assert "media_position" not in hass.states.get(second).attributes
    assert not (attributes["supported_features"] & MediaPlayerEntityFeature.SEEK)
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_progress_updates_do_not_reload_the_unchanged_cover(
    hass: HomeAssistant, audio_setup: SimpleNamespace
) -> None:
    """A moving clock must not turn every event into a new artwork request."""
    await audio_setup.setup()
    first = zone_entity_id(hass, 7)
    hashes = []
    stamps = []
    for position in (0, 63.25):
        await audio_setup.queues[0].put(
            json.dumps(
                {
                    "audio_event": [
                        {
                            "playerid": 7,
                            "mode": "play",
                            "audiopath": "spotify:track:synthetic",
                            "title": "Same track",
                            "coverurl": "/covers/same.jpg",
                            "time": position,
                            "duration": 180,
                        }
                    ]
                }
            )
        )
        await hass.async_block_till_done()
        entity = hass.data["media_player"].get_entity(first)
        hashes.append(entity.media_image_hash)
        stamps.append(entity.media_position_updated_at)
        assert entity.media_position == position
    assert hashes[0] is not None
    assert hashes[1] == hashes[0]
    assert stamps[1] > stamps[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("stopped_state", [0, 1])
async def test_native_pause_stop_freezes_position_and_resume_does_not_count_silence(
    hass: HomeAssistant, audio_setup: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, stopped_state: int
) -> None:
    """Keep native playback authority without counting paused/idle wall time."""
    await audio_setup.setup()
    first = zone_entity_id(hass, 7)
    hass.bus.async_fire(EVENT, {"play-7": 2})
    await audio_setup.queues[0].put(
        json.dumps(
            {
                "audio_event": [
                    {
                        "playerid": 7,
                        "mode": "play",
                        "audiopath": "spotify:track:synthetic",
                        "time": 63.25,
                        "duration": 180,
                    }
                ]
            }
        )
    )
    await hass.async_block_till_done()
    entity = hass.data["media_player"].get_entity(first)
    base = entity.media_position_updated_at
    now = base + timedelta(seconds=10)
    monkeypatch.setattr(dt_util, "utcnow", lambda: now)
    hass.bus.async_fire(EVENT, {"play-7": stopped_state})
    await hass.async_block_till_done()
    assert entity.media_position == 73.25
    assert entity.media_position_updated_at == now
    now = base + timedelta(seconds=70)
    hass.bus.async_fire(EVENT, {"play-7": 2})
    await hass.async_block_till_done()
    assert entity.media_position == 73.25
    assert entity.media_position_updated_at == now
    now = base + timedelta(seconds=80)
    hass.bus.async_fire(EVENT, {"play-7": stopped_state})
    await hass.async_block_till_done()
    assert entity.media_position == 83.25
    assert entity.media_position_updated_at == now
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario",
    [
        (mode, native_first, native_stopped, stopped_time)
        for mode in ("pause", "stop")
        for native_first in (True, False)
        for native_stopped in (0, 1)
        for stopped_time in (0, None)
    ],
)
async def test_zero_pause_snapshot_preserves_frozen_position_in_either_arrival_order(
    hass: HomeAssistant,
    audio_setup: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    scenario: tuple[str, bool, int, int | None],
) -> None:
    """A stopped zero is not a seek to the start of the unchanged track."""
    mode, native_first, native_stopped, stopped_time = scenario
    await audio_setup.setup()
    first = zone_entity_id(hass, 7)
    now = dt_util.utcnow()
    monkeypatch.setattr(dt_util, "utcnow", lambda: now)
    monkeypatch.setattr(audioserver, "datetime", SimpleNamespace(now=lambda _tz: now))
    row = {
        "playerid": 7,
        "mode": "play",
        "audiopath": "library:local:track:synthetic",
        "title": "Unchanged track",
        "coverurl": "/synthetic.jpg",
        "time": 63.25,
        "duration": 180,
    }

    async def frame(extra: dict) -> None:
        payload = {**row, **extra}
        if payload.get("time") is None:
            payload.pop("time", None)
        await audio_setup.queues[0].put(json.dumps({"audio_event": [payload]}))
        await hass.async_block_till_done()

    hass.bus.async_fire(EVENT, {"play-7": 2})
    await frame({})
    entity = hass.data["media_player"].get_entity(first)
    artwork = entity.media_image_hash
    now += timedelta(seconds=10)
    if native_first:
        hass.bus.async_fire(EVENT, {"play-7": native_stopped})
        await hass.async_block_till_done()
    await frame({"mode": mode, "time": stopped_time})
    if not native_first:
        assert hass.states.get(first).state == "playing"
        assert hass.states.get(first).attributes.get("audio_position_frozen") is True
        # The native status can lag the Audio Server snapshot.
        now += timedelta(seconds=2)
        hass.bus.async_fire(EVENT, {"play-7": native_stopped})
        await hass.async_block_till_done()
    assert hass.states.get(first).attributes["media_position"] == 73.25
    assert entity.media_image_hash == artwork
    now += timedelta(seconds=60)
    await frame({"mode": mode, "time": stopped_time})
    assert entity.media_position == 73.25
    assert entity.media_image_hash == artwork
    # A fresh play snapshot is authoritative again, with no paused-time jump.
    await frame({"mode": "play", "time": 73.25})
    hass.bus.async_fire(EVENT, {"play-7": 2})
    await hass.async_block_till_done()
    now += timedelta(seconds=10)
    hass.bus.async_fire(EVENT, {"play-7": 0})
    await hass.async_block_till_done()
    assert entity.media_position == 83.25
    assert not (entity.supported_features & MediaPlayerEntityFeature.SEEK)
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("extra", "expected", "duration"),
    [
        ({"audiopath": "library:local:track:different"}, 0, 180),
        ({"audiopath": "spotify:track:different"}, 0, 180),
        ({"title": "Different title"}, 0, 180),
        ({"duration": 200}, 0, 200),
        # A bare same-track play zero is observed on resume, not proof of restart.
        ({"mode": "play"}, 63.25, 180),
        ({"audiopath": "loxoneradio:stream:synthetic"}, None, None),
        ({"eventype": 3}, None, None),
    ],
)
async def test_zero_timing_hold_respects_track_source_and_event_identity(
    hass: HomeAssistant,
    audio_setup: SimpleNamespace,
    extra: dict,
    expected: float | None,
    duration: float | None,
) -> None:
    """Identity changes invalidate the clock; same-track play zero does not."""
    await audio_setup.setup()
    first = zone_entity_id(hass, 7)
    row = {
        "playerid": 7,
        "mode": "play",
        "audiopath": "library:local:track:synthetic",
        "title": "Original",
        "time": 63.25,
        "duration": 180,
    }
    await audio_setup.queues[0].put(json.dumps({"audio_event": [row]}))
    await hass.async_block_till_done()
    hass.bus.async_fire(EVENT, {"play-7": 0})
    await hass.async_block_till_done()
    await audio_setup.queues[0].put(json.dumps({"audio_event": [{**row, "mode": "stop", "time": 0, **extra}]}))
    await hass.async_block_till_done()
    entity = hass.data["media_player"].get_entity(first)
    assert entity.media_position == expected
    assert entity.media_duration == duration
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("native_first", [False, True])
async def test_resume_zero_feedback_never_publishes_a_false_restart(
    hass: HomeAssistant,
    audio_setup: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    *,
    native_first: bool,
) -> None:
    """Synthetic reconstruction of observed zero/valid/late-zero HA transitions."""
    await audio_setup.setup()
    first = zone_entity_id(hass, 7)
    now = dt_util.utcnow()
    monkeypatch.setattr(dt_util, "utcnow", lambda: now)
    monkeypatch.setattr(audioserver, "datetime", SimpleNamespace(now=lambda _tz: now))
    row = {
        "playerid": 7,
        "mode": "play",
        "audiopath": "library:local:track:synthetic",
        "title": "Same synthetic track",
        "coverurl": "/synthetic.jpg",
        "time": 63.25,
        "duration": 180,
    }

    async def frame(**extra: Any) -> None:
        await audio_setup.queues[0].put(json.dumps({"audio_event": [{**row, **extra}]}))
        await hass.async_block_till_done()

    async def native(value: int) -> None:
        hass.bus.async_fire(EVENT, {"play-7": value})
        await hass.async_block_till_done()

    await native(2)
    await frame()
    entity = hass.data["media_player"].get_entity(first)
    artwork = entity.media_image_hash
    now += timedelta(seconds=10)
    await frame(mode="stop", time=0)
    await native(0)
    assert entity.media_position == 73.25
    now += timedelta(seconds=60)
    if native_first:
        await native(2)
    await frame(time=0)
    assert hass.states.get(first).attributes["media_position"] == 73.25
    assert entity.state == ("playing" if native_first else "idle")
    assert entity.extra_state_attributes["audio_position_frozen"] is False
    if not native_first:
        await native(2)
    await frame(time=73.25)
    for interval in (0.25, 0.55):
        now += timedelta(seconds=interval)
        await frame(time=0)
        assert entity.media_position > 73.25
        assert entity.media_image_hash == artwork
    now += timedelta(seconds=9.2)
    await native(0)
    assert entity.media_position == pytest.approx(83.25)
    assert hass.states.get(first).attributes["audio_position_frozen"] is True
    assert not (entity.supported_features & MediaPlayerEntityFeature.SEEK)
    assert "media_position" not in hass.states.get(zone_entity_id(hass, 8)).attributes
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("native_first", [False, True])
@pytest.mark.parametrize("mode", ["pause", "stop"])
async def test_unchanged_positive_pause_sample_does_not_rewind_the_visible_clock(
    hass: HomeAssistant,
    audio_setup: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    *,
    native_first: bool,
    mode: str,
) -> None:
    """Reconstruct stale-positive/new-anchor then corrected-position feedback."""
    await audio_setup.setup()
    first = zone_entity_id(hass, 7)
    now = dt_util.utcnow()
    monkeypatch.setattr(dt_util, "utcnow", lambda: now)
    monkeypatch.setattr(audioserver, "datetime", SimpleNamespace(now=lambda _tz: now))
    row = {
        "playerid": 7,
        "mode": "play",
        "audiopath": "library:local:track:synthetic",
        "time": 63.25,
        "duration": 180,
        "coverurl": "/synthetic.jpg",
    }

    async def frame(**extra: Any) -> None:
        await audio_setup.queues[0].put(json.dumps({"audio_event": [{**row, **extra}]}))
        await hass.async_block_till_done()

    hass.bus.async_fire(EVENT, {"play-7": 2})
    await frame()
    entity = hass.data["media_player"].get_entity(first)
    artwork = entity.media_image_hash
    assert artwork is not None
    now += timedelta(seconds=3.2)
    if native_first:
        hass.bus.async_fire(EVENT, {"play-7": 0})
        await hass.async_block_till_done()
    await frame(mode=mode)
    assert entity.media_position == pytest.approx(66.45)
    assert hass.states.get(first).attributes["audio_position_frozen"] is True
    now += timedelta(milliseconds=30)
    await frame(mode=mode)
    assert entity.media_position == pytest.approx(66.45)
    # A genuinely new nonzero offset stays authoritative, even a rewind.
    await frame(mode=mode, time=66)
    assert entity.media_position == 66
    hass.bus.async_fire(EVENT, {"play-7": 0})
    await hass.async_block_till_done()
    now += timedelta(seconds=30)
    await frame(mode=mode, time=66)
    assert entity.media_position == 66
    await frame(mode=mode, time=12.5)
    assert entity.media_position == 12.5
    assert entity.media_image_hash == artwork
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_unchanged_play_sample_reanchors_without_losing_elapsed_time(
    hass: HomeAssistant, audio_setup: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unchanged positive play feedback must not repeatedly restart the clock."""
    await audio_setup.setup()
    first = zone_entity_id(hass, 7)
    now = dt_util.utcnow()
    monkeypatch.setattr(dt_util, "utcnow", lambda: now)
    monkeypatch.setattr(audioserver, "datetime", SimpleNamespace(now=lambda _tz: now))
    row = {"playerid": 7, "mode": "play", "audiopath": "spotify:track:synthetic", "time": 63.25, "duration": 180}
    hass.bus.async_fire(EVENT, {"play-7": 2})
    await audio_setup.queues[0].put(json.dumps({"audio_event": [row]}))
    await hass.async_block_till_done()
    now += timedelta(seconds=1.5)
    await audio_setup.queues[0].put(json.dumps({"audio_event": [row]}))
    await hass.async_block_till_done()
    assert hass.states.get(first).attributes["media_position"] == pytest.approx(64.75)
    now += timedelta(seconds=1)
    await audio_setup.queues[0].put(json.dumps({"audio_event": [row]}))
    await hass.async_block_till_done()
    assert hass.states.get(first).attributes["media_position"] == pytest.approx(65.75)
    now += timedelta(seconds=1)
    hass.bus.async_fire(EVENT, {"play-7": 0})
    await hass.async_block_till_done()
    assert hass.states.get(first).attributes["media_position"] == pytest.approx(66.75)
    await audio_setup.queues[0].put(json.dumps({"audio_event": [{**row, "mode": "stop", "time": 12.5}]}))
    await hass.async_block_till_done()
    assert hass.states.get(first).attributes["media_position"] == 12.5
    now += timedelta(seconds=1)
    # A different identity must accept even the same raw numeric offset.
    await audio_setup.queues[0].put(
        json.dumps({"audio_event": [{**row, "audiopath": "spotify:track:another", "time": 12.5}]})
    )
    await hass.async_block_till_done()
    assert hass.states.get(first).attributes["media_position"] == 12.5
    assert hass.states.get(first).attributes["media_position_updated_at"] == now


@pytest.mark.asyncio
async def test_native_resume_restarts_clock_without_a_fresh_audio_snapshot(
    hass: HomeAssistant,
    audio_setup: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Native resume alone must exclude silence and restart extrapolation."""
    await audio_setup.setup()
    first = zone_entity_id(hass, 7)
    now = dt_util.utcnow()
    monkeypatch.setattr(dt_util, "utcnow", lambda: now)
    monkeypatch.setattr(audioserver, "datetime", SimpleNamespace(now=lambda _tz: now))
    row = {"playerid": 7, "mode": "play", "audiopath": "library:local:track:synthetic", "time": 63.25, "duration": 180}
    hass.bus.async_fire(EVENT, {"play-7": 2})
    await audio_setup.queues[0].put(json.dumps({"audio_event": [row]}))
    await hass.async_block_till_done()
    now += timedelta(seconds=10)
    await audio_setup.queues[0].put(json.dumps({"audio_event": [{**row, "mode": "stop", "time": 0}]}))
    await hass.async_block_till_done()
    hass.bus.async_fire(EVENT, {"play-7": 0})
    await hass.async_block_till_done()
    now += timedelta(seconds=60)
    hass.bus.async_fire(EVENT, {"play-7": 2})
    await hass.async_block_till_done()
    now += timedelta(seconds=10)
    hass.bus.async_fire(EVENT, {"play-7": 0})
    await hass.async_block_till_done()
    assert hass.states.get(first).attributes["media_position"] == 83.25
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("repeated_native_play", [False, True])
async def test_clock_freeze_survives_fresh_untimed_stops_and_repeated_native_play(
    hass: HomeAssistant,
    audio_setup: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    *,
    repeated_native_play: bool,
) -> None:
    """Fresh untimed feedback is not replay; duplicate native play is not resume."""
    await audio_setup.setup()
    first = zone_entity_id(hass, 7)
    now = dt_util.utcnow()
    monkeypatch.setattr(dt_util, "utcnow", lambda: now)
    monkeypatch.setattr(audioserver, "datetime", SimpleNamespace(now=lambda _tz: now))
    row = {"playerid": 7, "mode": "play", "audiopath": "library:local:track:synthetic", "time": 63.25, "duration": 180}

    async def frame(*, stopped: bool = False) -> None:
        payload = {**row, "mode": "stop" if stopped else "play"}
        if stopped:
            payload.pop("time")
        await audio_setup.queues[0].put(json.dumps({"audio_event": [payload]}))
        await hass.async_block_till_done()

    async def native(value: int) -> None:
        hass.bus.async_fire(EVENT, {"play-7": value})
        await hass.async_block_till_done()

    await native(2)
    await frame()
    now += timedelta(seconds=10)
    await frame(stopped=True)
    entity = hass.data["media_player"].get_entity(first)
    if repeated_native_play:
        now += timedelta(seconds=2)
        await native(2)
        expected = 73.25
    else:
        await native(0)
        now += timedelta(seconds=60)
        await native(2)
        now += timedelta(seconds=10)
        await frame(stopped=True)
        expected = 83.25
    assert entity.extra_state_attributes["audio_position_frozen"] is True
    assert entity.media_position == expected
    now += timedelta(seconds=2)
    await native(0)
    assert entity.media_position == expected
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_alarm_end_callback_does_not_undo_a_newer_native_position_freeze(
    hass: HomeAssistant, audio_setup: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An event-attribute timer is not a fresh time sample from the server."""
    entry = await audio_setup.setup()
    first = zone_entity_id(hass, 7)
    hass.bus.async_fire(EVENT, {"play-7": 2})
    await audio_setup.queues[0].put('{"audio_event":[{"playerid":7,"mode":"play","eventype":100}]}')
    await hass.async_block_till_done()
    await audio_setup.queues[0].put(
        json.dumps(
            {
                "audio_event": [
                    {
                        "playerid": 7,
                        "mode": "play",
                        "audiopath": "spotify:track:synthetic",
                        "time": 63.25,
                        "duration": 180,
                    }
                ]
            }
        )
    )
    await hass.async_block_till_done()
    audio = hass.data[DOMAIN][entry.entry_id].audio_metadata
    sample = audio.get(7).position_updated_at
    entity = hass.data["media_player"].get_entity(first)
    now = sample + timedelta(seconds=10)
    monkeypatch.setattr(dt_util, "utcnow", lambda: now)
    hass.bus.async_fire(EVENT, {"play-7": 1})
    await hass.async_block_till_done()
    assert entity.media_position == 73.25
    assert hass.states.get(first).attributes["audio_event_active"] is True
    await asyncio.sleep(1.55)
    await hass.async_block_till_done()
    assert hass.states.get(first).attributes["audio_event_active"] is False
    assert audio.get(7).position_updated_at == sample
    assert entity.media_position == 73.25
    assert entity.media_position_updated_at == now


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "following",
    [
        None,
        {},
        {"mode": "play", "audiopath": "loxoneradio:stream:synthetic", "time": 1, "duration": 180},
        {"mode": "play", "audiopath": "airplay", "time": 1, "duration": 180},
        {"mode": "play", "eventype": 3, "time": 1, "duration": 180},
        {"mode": "stop", "eventype": 3, "time": 1, "duration": 180},
    ],
)
async def test_timing_clears_without_changing_native_state_volume_or_other_zone(
    hass: HomeAssistant, audio_setup: SimpleNamespace, following: dict | None
) -> None:
    """Reconnect, missing data and interruptions cannot retain a stale timeline."""
    await audio_setup.setup()
    first = zone_entity_id(hass, 7)
    second = zone_entity_id(hass, 8)
    hass.bus.async_fire(EVENT, {"play-7": 2, "play-8": 2, "volume-7": 36})
    await audio_setup.queues[0].put(
        json.dumps(
            {
                "audio_event": [
                    {
                        "playerid": pid,
                        "mode": "play",
                        "audiopath": "spotify:track:synthetic",
                        "time": pid,
                        "duration": 180,
                    }
                    for pid in (7, 8)
                ]
            }
        )
    )
    await hass.async_block_till_done()
    entity = hass.data["media_player"].get_entity(first)
    assert entity.media_position == 7
    if following is None:
        await audio_setup.queues[0].put(None)
    else:
        await audio_setup.queues[0].put(json.dumps({"audio_event": [{"playerid": 7, **following}]}))
    await hass.async_block_till_done()
    assert entity.media_position is None
    assert entity.media_duration is None
    assert entity.media_position_updated_at is None
    assert "media_position" not in hass.states.get(first).attributes
    assert "media_duration" not in hass.states.get(first).attributes
    assert hass.states.get(first).state == "playing"
    assert hass.states.get(first).attributes["volume_level"] == 0.36
    if following is not None:
        assert hass.data["media_player"].get_entity(second).media_position == 8
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.parametrize("language", ["en", "de", "cs"])
async def test_audio_error_catalogues_resolve_through_ha(
    hass: HomeAssistant, audio_setup: SimpleNamespace, language: str
) -> None:
    """Exercise HA's real loader, not merely translation-key presence on an error."""
    await audio_setup.setup()
    resources = await async_get_translations(hass, language, "exceptions", {DOMAIN})
    for key in (
        "audioserver_playback_failed",
        "audioserver_playback_unavailable",
        "audioserver_announcement_failed",
        "audioserver_announcement_unavailable",
    ):
        message = resources[f"component.{DOMAIN}.exceptions.{key}.message"]
        assert isinstance(message, str)
        assert len(message) > 40
        assert "Audio Server" in message
    for category in ("config", "options"):
        resources = await async_get_translations(hass, language, category, {DOMAIN})
        for key in ("invalid_audioserver_host", "audioserver_playback_requires_host"):
            assert resources[f"component.{DOMAIN}.{category}.error.{key}"]


@pytest.mark.asyncio
async def test_standard_ha_announcement_action_uploads_once_and_waits_for_exact_player_event_end(
    hass: HomeAssistant,
    audio_setup: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
):
    """Real HA service/entity/lifecycle path; only audio IO is synthetic."""
    prepare = AsyncMock(return_value=(b"synthetic-prepared-wav", 0.2))
    upload = AsyncMock()
    playback = AsyncMock()
    monkeypatch.setattr(audio_announcement, "async_prepare_announcement", prepare)
    monkeypatch.setattr(audioserver.AudioServerCommands, "async_upload_announcement", upload)
    monkeypatch.setattr(audioserver.AudioServerCommands, "async_execute", playback)
    await audio_setup.setup(playback=True)
    entity_id = zone_entity_id(hass, 7)
    finished = asyncio.Event()
    await audio_setup.queues[0].put(json.dumps({"audio_event": [{"playerid": 7, "eventype": 0, "mode": "stop"}]}))
    await hass.async_block_till_done()

    async def native(player: int, filename: str, volume: int, *, is_current: Any, on_send: Any) -> None:
        assert player == 7
        assert volume == 10
        assert is_current()
        on_send()
        # Broadcast elsewhere is not completion of this exact owned event.
        for row in [
            {"playerid": 8, "mode": "play", "eventype": 5, "audiopath": "file:///tmp/audioupload/" + filename},
            {"playerid": 7, "mode": "play", "eventype": 5, "audiopath": "file:///tmp/audioupload/" + filename},
            {"playerid": 7, "mode": "stop", "eventype": 0, "audiopath": "spotify:track:original"},
        ]:
            await audio_setup.queues[0].put(json.dumps({"audio_event": [row]}))
            await asyncio.sleep(0)
        finished.set()

    announce = AsyncMock(side_effect=native)
    monkeypatch.setattr(audioserver.AudioServerCommands, "async_announce", announce)
    state = hass.states.get(entity_id)
    assert state.attributes["supported_features"] & MediaPlayerEntityFeature.MEDIA_ANNOUNCE
    await hass.services.async_call(
        "media_player",
        "play_media",
        {
            "entity_id": entity_id,
            "media_content_id": "media-source://tts/tts.synthetic?message=testing",
            "media_content_type": "music",
            "announce": True,
            "extra": {"volume": 0.1},
        },
        blocking=True,
    )
    assert finished.is_set()
    prepare.assert_awaited_once_with(hass, "media-source://tts/tts.synthetic?message=testing", entity_id)
    upload.assert_awaited_once()
    assert upload.await_args.args[1] == announce.await_args.args[1]
    assert upload.await_args.args[2] == b"synthetic-prepared-wav"
    announce.assert_awaited_once()
    playback.assert_not_awaited()
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_unload_cancels_pending_announcement_resolution_before_any_upload(
    hass: HomeAssistant,
    audio_setup: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real entry unload cancels preparation before any possible sound."""
    entered = asyncio.Event()

    async def prepare(*args: object) -> Any:
        entered.set()
        await asyncio.Future()

    upload = AsyncMock()
    announce = AsyncMock()
    monkeypatch.setattr(audio_announcement, "async_prepare_announcement", prepare)
    monkeypatch.setattr(audioserver.AudioServerCommands, "async_upload_announcement", upload)
    monkeypatch.setattr(audioserver.AudioServerCommands, "async_announce", announce)
    entry = await audio_setup.setup(playback=True)
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    task = asyncio.create_task(
        entity.async_play_media("music", "https://ha.example.invalid/synthetic.wav", announce=True)
    )
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert await asyncio.wait_for(hass.config_entries.async_unload(entry.entry_id), 2)
        await asyncio.sleep(0)
        assert task.done(), "Unloaded entity left an announcement capable of late playback"
        with pytest.raises(asyncio.CancelledError):
            await task
        upload.assert_not_awaited()
        announce.assert_not_awaited()
    finally:
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


@pytest.mark.asyncio
async def test_announcement_provider_failure_never_uploads_or_changes_playback(
    hass: HomeAssistant,
    audio_setup: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider failure has no sound, upload, or room-start side effect."""
    prepare = AsyncMock(side_effect=HomeAssistantError("synthetic provider failure"))
    upload = AsyncMock()
    announce = AsyncMock()
    monkeypatch.setattr(audio_announcement, "async_prepare_announcement", prepare)
    monkeypatch.setattr(audioserver.AudioServerCommands, "async_upload_announcement", upload)
    monkeypatch.setattr(audioserver.AudioServerCommands, "async_announce", announce)
    await audio_setup.setup(playback=True)
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    with pytest.raises(HomeAssistantError) as error:
        await entity.async_play_media("music", "media-source://tts/tts.synthetic?message=testing", announce=True)
    assert error.value.translation_key == "audioserver_announcement_failed"
    assert entity._announcement_task is None
    upload.assert_not_awaited()
    announce.assert_not_awaited()
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_overlapping_announcement_is_rejected_without_queue_or_duplicate_resolution(
    hass: HomeAssistant,
    audio_setup: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second call cannot queue a later duplicate announcement."""
    entered = asyncio.Event()

    async def waiting(*args: object) -> Any:
        entered.set()
        await asyncio.Future()

    prepare = AsyncMock(side_effect=waiting)
    upload = AsyncMock()
    monkeypatch.setattr(audio_announcement, "async_prepare_announcement", prepare)
    monkeypatch.setattr(audioserver.AudioServerCommands, "async_upload_announcement", upload)
    await audio_setup.setup(playback=True)
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    first = asyncio.create_task(entity.async_play_media("music", "https://ha.example.invalid/first.wav", announce=True))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        with pytest.raises(HomeAssistantError) as error:
            await entity.async_play_media("music", "https://ha.example.invalid/second.wav", announce=True)
        assert error.value.translation_key == "audioserver_announcement_unavailable"
        prepare.assert_awaited_once()
        upload.assert_not_awaited()
    finally:
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first


@pytest.mark.asyncio
async def test_standard_source_selection_uses_configured_choice_not_arbitrary_paths(
    hass: HomeAssistant,
    audio_setup: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real standard HA action waits for its exact room-native recent source."""

    def configured(player: int) -> list[dict[str, Any]]:
        items = (
            [{"id": 3, "name": "Synthetic Radio", "type": "tunein", "audiopath": "tunein:station:synthetic"}]
            if player == 7
            else []
        )
        return [{"id": player, "start": 0, "totalitems": len(items), "items": items}]

    monkeypatch.setattr(audioserver.AudioServerCommands, "async_room_favourites", AsyncMock(side_effect=configured))
    monkeypatch.setattr(audioserver.AudioServerCommands, "async_recent_sources", AsyncMock(side_effect=lambda player: {"items": [{"type": 2, "title": "Synthetic Radio", "audiopath": "tunein:station:synthetic"}] if player == 7 else [], "ts": 0}))
    calls = []

    async def start(
        self: audioserver.AudioServerCommands,
        player: int,
        service: str,
        audio_path: str,
        *,
        is_current: Callable[[], bool],
        on_send: Callable[[], None],
    ) -> None:
        assert is_current()
        on_send()
        calls.append((player, service, audio_path))
        hass.bus.async_fire(EVENT, {"play-7": 2})
        await audio_setup.queues[0].put(
            json.dumps({"audio_event": [{"playerid": 7, "mode": "play", "audiopath": "tunein:station:synthetic"}]})
        )

    monkeypatch.setattr(audioserver.AudioServerCommands, "async_play_radio_station", start)
    await audio_setup.setup(playback=True)
    target = zone_entity_id(hass, 7)
    other = zone_entity_id(hass, 8)
    assert hass.states.get(target).attributes.get("source_list") == ["TuneIn"]
    assert hass.states.get(target).attributes["supported_features"] & MediaPlayerEntityFeature.SELECT_SOURCE
    assert hass.states.get(other).attributes["supported_features"] & MediaPlayerEntityFeature.SELECT_SOURCE
    other_entity = hass.data["media_player"].get_entity(other)
    assert not other_entity._radio_catalogue.source_choices
    with pytest.raises(HomeAssistantError, match="Browse"):
        await other_entity.async_select_source("TuneIn")
    await audio_setup.queues[0].put(
        json.dumps({"audio_event": [{"playerid": 7, "mode": "stop", "audiopath": "spotify:track:before"}]})
    )
    await hass.async_block_till_done()
    for _ in range(2):
        await hass.services.async_call(
            "media_player", "select_source", {"entity_id": target, "source": "TuneIn"}, blocking=True
        )
    await hass.async_block_till_done()
    # Repeated selection of the observed playing target is an idempotent no-op.
    assert calls == [(7, "world", "tunein:station:synthetic")]
    assert hass.states.get(target).attributes["source"] == "TuneIn"
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "media_player", "select_source", {"entity_id": target, "source": "tunein:station:arbitrary"}, blocking=True
        )
    assert calls == [(7, "world", "tunein:station:synthetic")]
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("duplicate_path", [False, True])
async def test_favourite_labels_do_not_override_observed_provider_or_ambiguous_identity(
    hass: HomeAssistant,
    audio_setup: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    *,
    duplicate_path: bool,
) -> None:
    """Names are presentation, not provider or unique content evidence."""

    def configured(player: int) -> list[dict[str, Any]]:
        items = [{"id": 3, "name": "Loxone Radio", "type": "tunein", "audiopath": "tunein:station:synthetic"}]
        if duplicate_path:
            items.append({**items[0], "id": 4, "name": "Same content"})
        return [{"id": player, "start": 0, "totalitems": len(items), "items": items}]

    monkeypatch.setattr(audioserver.AudioServerCommands, "async_room_favourites", AsyncMock(side_effect=configured))
    await audio_setup.setup(playback=True)
    target = zone_entity_id(hass, 7)
    hass.bus.async_fire(EVENT, {"play-7": 2})
    await audio_setup.queues[0].put(
        json.dumps({"audio_event": [{"playerid": 7, "mode": "play", "audiopath": "tunein:station:synthetic"}]})
    )
    await hass.async_block_till_done()
    state = hass.states.get(target)
    assert not state.attributes["supported_features"] & MediaPlayerEntityFeature.NEXT_TRACK
    assert not state.attributes["supported_features"] & MediaPlayerEntityFeature.PREVIOUS_TRACK
    assert state.attributes["source"] == "TuneIn"  # A favourite alias never reclassifies its provider.


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["preparation", "dispatched"])
async def test_unload_cancels_source_preparation_without_playback(
    hass: HomeAssistant,
    audio_setup: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    """Real entry unload owns preparation and uncertain dispatch without a replay."""
    monkeypatch.setattr(
        audioserver.AudioServerCommands,
        "async_room_favourites",
        AsyncMock(
            side_effect=lambda player: [
                {
                    "id": player,
                    "start": 0,
                    "totalitems": 1,
                    "items": [
                        {"id": 3, "name": "Synthetic Radio", "type": "tunein", "audiopath": "tunein:station:synthetic"}
                    ],
                }
            ]
        ),
    )
    monkeypatch.setattr(audioserver.AudioServerCommands, "async_recent_sources", AsyncMock(return_value={"items": [{"type": 2, "title": "Synthetic Radio", "audiopath": "tunein:station:synthetic"}], "ts": 0}))
    entry = await audio_setup.setup(playback=True)
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    commands = entity._audio_commands
    entered = asyncio.Event()

    async def waiting(player: int) -> Any:
        entered.set()
        await asyncio.Future()

    async def dispatched(player: int, service: str, path: str, *, is_current: Any, on_send: Any) -> None:
        assert is_current()
        on_send()
        await waiting(player)

    if phase == "preparation":
        monkeypatch.setattr(commands, "async_recent_sources", AsyncMock(side_effect=waiting))
    else:
        await audio_setup.queues[0].put(
            json.dumps({"audio_event": [{"playerid": 7, "mode": "stop", "audiopath": "spotify:track:before"}]})
        )
        await hass.async_block_till_done()
    play = AsyncMock(side_effect=dispatched if phase == "dispatched" else None)
    monkeypatch.setattr(commands, "async_play_radio_station", play)
    task = asyncio.create_task(entity.async_select_source("TuneIn"))
    await asyncio.wait_for(entered.wait(), 2)
    assert entity._source_task is task  # Preparation belongs to entry unload as well as dispatch.
    assert await hass.config_entries.async_unload(entry.entry_id)
    with pytest.raises(asyncio.CancelledError):
        await task
    assert entity._source_task is None
    assert commands._closed
    assert not commands.source_fences
    assert not entity._audio_metadata._listeners
    if phase == "preparation":
        play.assert_not_awaited()
    else:
        play.assert_awaited_once()








