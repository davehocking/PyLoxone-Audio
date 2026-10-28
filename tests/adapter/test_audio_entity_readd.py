"""Real HA registry rename regression, synthetic devices and transports only."""

# ruff: noqa: S101, INP001, ANN001, D103, SLF001

import json
from unittest.mock import AsyncMock

import pytest
from homeassistant.components.media_player import MediaPlayerEntityFeature
from homeassistant.helpers import entity_registry as er

from test_audioserver_ha import audio_setup as audio_setup, zone_entity_id  # noqa: PLC0414 - explicit pytest fixture re-export
from custom_components.loxone.const import EVENT
from custom_components.loxone.pyloxone_api import audioserver as wire


@pytest.mark.asyncio
@pytest.mark.parametrize("renames", [1, 3])
async def test_registry_rename_keeps_audio_capabilities_and_new_metadata(
    hass, audio_setup, monkeypatch, renames
):
    monkeypatch.setattr(
        wire.AudioServerCommands,
        "async_recent_sources",
        AsyncMock(return_value={"items": [
            {"audiopath": "tunein:station:synthetic", "title": "Synthetic radio", "type": 2}
        ], "ts": 1}),
    )
    await audio_setup.setup(playback=True)
    original_id = zone_entity_id(hass, 7)
    entity = hass.data["media_player"].get_entity(original_id)
    other_id = zone_entity_id(hass, 8)
    other_before = hass.states.get(other_id)
    required = (
        MediaPlayerEntityFeature.BROWSE_MEDIA
        | MediaPlayerEntityFeature.SEARCH_MEDIA
        | MediaPlayerEntityFeature.PLAY_MEDIA
        | MediaPlayerEntityFeature.MEDIA_ANNOUNCE
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )
    assert entity.supported_features & required == required
    before = await entity.async_browse_media()
    assert before.children

    previous_id = original_id
    for index in range(renames):
        renamed_id = f"media_player.renamed_synthetic_audio_{index}"
        er.async_get(hass).async_update_entity(previous_id, new_entity_id=renamed_id)
        await hass.async_block_till_done()
        renamed = hass.data["media_player"].get_entity(renamed_id)
        assert renamed is entity
        assert hass.states.get(previous_id) is None
        assert renamed.supported_features & required == required
        assert renamed.source_list == ["TuneIn"]
        assert (await renamed.async_browse_media()).children
        assert len(entity._audio_metadata._listeners[7]) == 1
        previous_id = renamed_id

    hass.bus.async_fire(EVENT, {"play-7": 2})
    await audio_setup.queues[0].put(json.dumps({"audio_event": [{
        "playerid": 7, "mode": "play", "audiopath": "tunein:station:synthetic",
        "title": "New metadata after rename",
    }]}))
    await hass.async_block_till_done()
    assert hass.states.get(renamed_id).attributes["media_title"] == "New metadata after rename"
    assert hass.states.get(other_id).as_dict() == other_before.as_dict()
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()
