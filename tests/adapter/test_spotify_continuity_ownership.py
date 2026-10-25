"""Synthetic review09 active conflicts and absent initial native identity."""

# ruff: noqa: S101, INP001, ANN001, D103, SLF001
from unittest.mock import AsyncMock
import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from test_spotify_continuity import native
from test_spotify_continuity_review import entity_boundary
from custom_components.loxone.audio_radio import RADIO_MEDIA_TYPE


@pytest.mark.asyncio
@pytest.mark.parametrize("capability", ["restricted", "unsupported"])
@pytest.mark.parametrize("phase", ["initial", "final"])
async def test_positive_active_conflict_precedes_optional_capability_fallback(hass, capability, phase):
    entity, session, snapshots, commands, _, old = entity_boundary(hass)
    await entity._spotify_return.async_capture(lambda: True)
    snapshots[0] = native("tunein:station:synthetic")

    def activate() -> None:
        session.current["is_playing"] = True
        if capability == "restricted":
            session.current["device"]["is_restricted"] = True
        else:
            session.current["currently_playing_type"] = "episode"
            session.current["item"]["type"] = "episode"
            session.current["item"]["uri"] = "spotify:episode:" + "E" * 22

    if phase == "initial":
        activate()
    else:
        session.current["is_playing"] = False
        async def activate_during_read(url):
            if url.endswith('/me'):activate()
        session.on_read=activate_during_read
    entity._radio_catalogue.async_source_selection = AsyncMock(
        return_value=entity._radio_catalogue._item(old).media_content_id
    )
    await entity.async_select_source("Spotify")
    commands.async_spotify_handoff.assert_awaited_once()
    assert snapshots[0].audio_path==session.current['item']['uri']
    commands.async_play_catalogue.assert_not_awaited()
    assert all(call[0] == "GET" for call in session.calls)


@pytest.mark.asyncio
async def test_missing_initial_native_snapshot_never_adopts_later_source(hass):
    entity, session, snapshots, commands, provider, old = entity_boundary(hass)
    provider.state = ConfigEntryState.NOT_LOADED
    snapshots[0] = None

    async def appear() -> list:
        snapshots[0] = native("tunein:station:newer-household-choice")
        return [{"cmd": "spotify", "id": "native-owner", "user": "native-user", "configerror": False}]

    commands.async_service_accounts = AsyncMock(side_effect=appear)
    item = entity._radio_catalogue._item(old)
    with pytest.raises(HomeAssistantError):
        await entity.async_play_media(RADIO_MEDIA_TYPE, item.media_content_id)
    commands.async_service_accounts.assert_not_awaited()
    commands.async_play_catalogue.assert_not_awaited()
    assert all(call[0] == "GET" for call in session.calls)
