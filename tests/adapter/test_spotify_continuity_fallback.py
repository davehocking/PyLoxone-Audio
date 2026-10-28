"""Independent review08 native-fallback races, using synthetic fixtures only."""

# ruff: noqa: S101, INP001, ANN001, D103, SLF001
import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock
from Crypto.PublicKey import RSA
import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from test_spotify_continuity import CONFIG, native
from test_spotify_continuity_review import entity_boundary
from test_audioserver_playback import SyntheticAudioSocket
from custom_components.loxone import media_player as media
from custom_components.loxone.audio_radio import RADIO_MEDIA_TYPE
from custom_components.loxone.pyloxone_api import audioserver as wire
from custom_components.loxone.spotify_continuity import spotify_room_uncertain




@pytest.mark.asyncio
@pytest.mark.parametrize("binding", [None, "configured"])
@pytest.mark.parametrize("change", ["stop", "source"])
async def test_native_fallback_resolution_cannot_supersede_newer_room_action(hass, binding, change):
    entity, session, snapshots, commands, provider, old = entity_boundary(hass, CONFIG if binding else None)
    provider.state = ConfigEntryState.NOT_LOADED
    snapshots[0] = native("tunein:station:synthetic")
    entered, release = asyncio.Event(), asyncio.Event()

    async def resolve(_source) -> str:
        entered.set()
        await release.wait()
        return entity._radio_catalogue._item(old).media_content_id

    entity._radio_catalogue.async_source_selection = resolve
    task = asyncio.create_task(entity.async_select_source("Spotify"))
    try:
        async with asyncio.timeout(1):
            await entered.wait()
        if change == "stop":
            await entity.async_media_stop()
        else:
            snapshots[0] = native("tunein:station:newer-household-choice")
    finally:
        release.set()
        result = (await asyncio.gather(task, return_exceptions=True))[0]
    assert isinstance(result, (HomeAssistantError, asyncio.CancelledError))
    commands.async_play_catalogue.assert_not_awaited()
    assert all(call[0] == "GET" for call in session.calls)


@pytest.mark.asyncio
async def test_native_dispatch_guard_pins_selection_before_account_preparation(hass):
    entity, session, snapshots, commands, provider, old = entity_boundary(hass)
    provider.state = ConfigEntryState.NOT_LOADED
    snapshots[0] = native("tunein:station:synthetic")

    async def changed_accounts() -> list:
        snapshots[0] = native("tunein:station:newer-household-choice")
        return [{"cmd": "spotify", "id": "native-owner", "user": "native-user", "configerror": False}]

    commands.async_service_accounts = changed_accounts
    item = entity._radio_catalogue._item(old)
    with pytest.raises(HomeAssistantError):
        await entity.async_play_media(RADIO_MEDIA_TYPE, item.media_content_id)
    commands.async_play_catalogue.assert_not_awaited()
    assert all(call[0] == "GET" for call in session.calls)
