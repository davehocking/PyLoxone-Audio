"""Actual HA entity/service path with synthetic multi-source transports only."""

# ruff: noqa: S101, INP001, ANN001, ANN002, ANN003, ANN202, D103, PLR0913, SLF001, ARG001, PT018, F811, F401

import asyncio
import json
from unittest.mock import AsyncMock
import pytest
from homeassistant.components.media_player import SearchMediaQuery
from homeassistant.exceptions import HomeAssistantError
from test_audioserver_ha import audio_setup, zone_entity_id
from test_audio_catalogue import catalogue_commands
from custom_components.loxone.pyloxone_api import audioserver as wire


@pytest.mark.asyncio
async def test_native_entity_browses_scopes_search_and_plays_one_discovered_library_track(
    hass, audio_setup, monkeypatch
):
    commands = catalogue_commands()
    for name, value in vars(commands).items():
        monkeypatch.setattr(wire.AudioServerCommands, name, value)
    await audio_setup.setup(playback=True)
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    await audio_setup.queues[0].put(
        json.dumps({"audio_event": [{"playerid": 7, "mode": "stop", "audiopath": "tunein:station:before"}]})
    )
    await hass.async_block_till_done()
    root = await entity.async_browse_media()
    library = next(c for c in root.children if c.title == "Local Library")
    commands.async_global_search.return_value = {
        "local": {"tracks": {"items": [{"id": "library:local:track:one", "type": 2, "name": "Song"}]}}
    }
    result = await entity.async_search_media(
        SearchMediaQuery(
            search_query="one", media_content_type=library.media_content_type, media_content_id=library.media_content_id
        )
    )
    assert commands.async_global_search.await_args.args[1] == {"local": ("track", "folder")}

    async def play(self, player, service, account, item, *, is_current, on_send):
        assert (player, service, account, item) == (7, "library", "nouser", "library:local:track:one")
        assert is_current()
        on_send()
        asyncio.get_running_loop().call_soon(
            audio_setup.queues[0].put_nowait,
            json.dumps({"audio_event": [{"playerid": 7, "mode": "play", "audiopath": item}]}),
        )

    sent = AsyncMock(side_effect=play)

    async def bound(self, *args, **kwargs):
        return await sent(self, *args, **kwargs)

    monkeypatch.setattr(wire.AudioServerCommands, "async_play_catalogue", bound)
    selection = result.result[0]
    await hass.services.async_call(
        "media_player",
        "play_media",
        {
            "entity_id": entity.entity_id,
            "media_content_type": selection.media_content_type,
            "media_content_id": selection.media_content_id,
        },
        blocking=True,
    )
    assert sent.await_count == 1 and not entity._audio_commands.source_fences
    with pytest.raises(HomeAssistantError):
        await entity.async_play_media(selection.media_content_type, library.media_content_id)
    other = hass.data["media_player"].get_entity(zone_entity_id(hass, 8))
    with pytest.raises(HomeAssistantError):
        await other.async_play_media(selection.media_content_type, selection.media_content_id)
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_all_supported_room_favourites_remain_in_browse_not_source_dropdown(hass, audio_setup, monkeypatch):
    items = [
        {"id": 1, "name": "Radio", "type": "tunein", "audiopath": "tunein:station:one"},
        {"id": 2, "name": "Saved collection", "type": "spotify_playlist", "audiopath": "spotify@owner:playlist:one"},
        {"id": 3, "name": "Saved library", "type": "library_folder", "audiopath": "library:local:folder:one"},
        {"id": 4, "name": "Saved input", "type": "linein", "audiopath": "linein/ABCDEF123456#1000001"},
    ]
    monkeypatch.setattr(
        wire.AudioServerCommands,
        "async_room_favourites",
        AsyncMock(side_effect=lambda p: [{"id": p, "start": 0, "totalitems": len(items), "items": items}]),
    )
    await audio_setup.setup(playback=True)
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    # Provider presence is independent of saved favourites and history.
    assert entity.source_list == ["TuneIn"]
    browsed = await entity.async_browse_media("pyloxone_radio", "pyloxone-radio:favourites")
    assert [child.title for child in browsed.children] == [i["name"] for i in items]
