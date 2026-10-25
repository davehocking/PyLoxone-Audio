"""Actual HA entity/service lifecycle with synthetic radio transport only."""

# ruff: noqa: S101, INP001, ANN001, ANN202, D103, PLR2004, SLF001, ARG001, PT018, F811, PLR0913, PLC0415

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from homeassistant.components.media_player import MediaPlayerEntityFeature, SearchMediaQuery
from homeassistant.exceptions import HomeAssistantError

from test_audioserver_ha import audio_setup, zone_entity_id  # noqa: F401 - pytest fixture registration

from custom_components.loxone.pyloxone_api import audioserver


@pytest.mark.asyncio
async def test_native_browse_search_and_standard_play_action_share_exact_room_backend(hass, audio_setup, monkeypatch):
    calls = []
    station = {"type": 2, "name": "Radio search result", "audiopath": "tunein:station:found"}
    monkeypatch.setattr(
        audioserver.AudioServerCommands,
        "async_radio_services",
        AsyncMock(return_value=[{"cmd": "world", "root": "root", "name": "World radio"}]),
    )
    monkeypatch.setattr(
        audioserver.AudioServerCommands,
        "async_radio_folder",
        AsyncMock(return_value=[{"start": 0, "totalitems": 1, "items": [station]}]),
    )
    monkeypatch.setattr(
        audioserver.AudioServerCommands, "async_global_search", AsyncMock(return_value={"tunein": {"station": {"items": [station]}}})
    )

    async def play(self, player, service, path, *, is_current, on_send):
        assert is_current()
        on_send()
        calls.append((player, service, path))
        asyncio.get_running_loop().call_later(
            0.01,
            audio_setup.queues[0].put_nowait,
            json.dumps(
                {
                    "audio_event": [{"playerid": player, "mode": "play", "audiopath": path}],
                }
            ),
        )

    monkeypatch.setattr(audioserver.AudioServerCommands, "async_play_radio_station", play, raising=False)
    await audio_setup.setup(playback=True)
    target = zone_entity_id(hass, 7)
    entity = hass.data["media_player"].get_entity(target)
    assert entity.supported_features & MediaPlayerEntityFeature.BROWSE_MEDIA
    assert entity.supported_features & MediaPlayerEntityFeature.SEARCH_MEDIA
    root = await entity.async_browse_media()
    assert root.can_search
    radio = next(child for child in root.children if child.title == "Radio")
    providers = await entity.async_browse_media(radio.media_content_type, radio.media_content_id)
    provider = next(child for child in providers.children if child.title == "World radio")
    page = await entity.async_browse_media(provider.media_content_type, provider.media_content_id)
    assert page.children[0].can_play
    found = await entity.async_search_media(SearchMediaQuery(search_query="radio"))
    selection = found.result[0]
    assert calls == []
    await audio_setup.queues[0].put(
        json.dumps(
            {
                "audio_event": [
                    {"playerid": 7, "mode": "stop", "audiopath": "spotify:track:before"},
                ]
            }
        )
    )
    await hass.async_block_till_done()
    await hass.services.async_call(
        "media_player",
        "play_media",
        {
            "entity_id": target,
            "media_content_type": selection.media_content_type,
            "media_content_id": selection.media_content_id,
        },
        blocking=True,
    )
    assert calls == [(7, "world", "tunein:station:found")]
    for invalid_id in ["tunein:station:arbitrary", "pyloxone-radio:not-discovered", provider.media_content_id]:
        with pytest.raises(HomeAssistantError):
            await entity.async_play_media(selection.media_content_type, invalid_id)
    other = hass.data["media_player"].get_entity(zone_entity_id(hass, 8))
    with pytest.raises(HomeAssistantError):
        await other.async_play_media(selection.media_content_type, selection.media_content_id)
    assert calls == [(7, "world", "tunein:station:found")]
    assert not entity._audio_commands.source_fences
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_larger_favourites_list_and_radio_search_remain_opt_in(hass, audio_setup, monkeypatch):
    def configured(player):
        rows = [
            {"id": i, "name": f"Station {i}", "type": "tunein", "audiopath": f"tunein:station:s{i}"}
            for i in range(1, 41)
        ]
        return [{"id": player, "start": 0, "totalitems": len(rows), "items": rows}]

    monkeypatch.setattr(audioserver.AudioServerCommands, "async_room_favourites", AsyncMock(side_effect=configured))
    await audio_setup.setup(playback=True)
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    assert entity.source_list == ["TuneIn"]  # Saved content still belongs in Browse.
    root = await entity.async_browse_media("pyloxone_radio", "pyloxone-radio:favourites")
    assert len(root.children) == 40 and all(child.can_play for child in root.children)


@pytest.mark.asyncio
async def test_passive_players_do_not_advertise_or_allow_station_browsing(hass, audio_setup):
    await audio_setup.setup(playback=False)
    passive = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    assert not passive.supported_features & (
        MediaPlayerEntityFeature.BROWSE_MEDIA | MediaPlayerEntityFeature.SEARCH_MEDIA
    )
    with pytest.raises(HomeAssistantError):
        await passive.async_browse_media()


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", [{"enqueue": "add"}, {"enqueue": "next"}, {"announce": True}])
async def test_radio_selection_does_not_silently_ignore_enqueue_or_announcement_modes(
    hass, audio_setup, monkeypatch, extra
):
    monkeypatch.setattr(
        audioserver.AudioServerCommands,
        "async_global_search",
        AsyncMock(
            return_value={
                "tunein": {"station": {"items": [{"type": 2, "name": "Radio", "audiopath": "tunein:station:found"}]}},
            }
        ),
    )
    await audio_setup.setup(playback=True)
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    selection = (await entity.async_search_media(SearchMediaQuery(search_query="radio"))).result[0]
    select = AsyncMock()
    prepare = AsyncMock()
    monkeypatch.setattr(entity, "_async_play_radio", select)
    from custom_components.loxone import audio_announcement

    monkeypatch.setattr(audio_announcement, "async_prepare_announcement", prepare)
    with pytest.raises(HomeAssistantError):
        await entity.async_play_media(selection.media_content_type, selection.media_content_id, **extra)
    select.assert_not_awaited()
    prepare.assert_not_awaited()
