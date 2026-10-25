"""Real entity source actions with synthetic native/provider boundaries only."""

# ruff: noqa: S101, INP001, ANN001, ANN002, ANN003, ANN202, D103, SLF001, PT018
import logging
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from test_spotify_continuity import native
from test_spotify_continuity_activation import ActivationSession
from test_spotify_continuity_review import entity_boundary
from custom_components.loxone.audio_radio import RADIO_MEDIA_TYPE, RadioTarget


@pytest.mark.asyncio
async def test_real_entity_departure_detach_activation_and_active_noop(hass, tmp_path, caplog):
    entity, original, snapshots, commands, provider, _ = entity_boundary(hass)
    hass.config.config_dir = str(tmp_path)
    session = ActivationSession(original, Path(hass.config.path(".storage", "pyloxone_spotify_return_dispatch")))
    provider.runtime_data.session = session
    original_radio = commands.async_play_radio_station.side_effect

    async def radio(*args, **kwargs):
        await original_radio(*args, **kwargs)
        session.current = None

    commands.async_play_radio_station = AsyncMock(side_effect=radio)
    item = entity._radio_catalogue._item(
        RadioTarget("station", "Synthetic radio", "world", audio_path="tunein:station:synthetic")
    )
    entity._radio_catalogue._source_accounts=commands.async_service_accounts.return_value
    entity._radio_catalogue.remember_source(snapshots[0])
    saved=entity._radio_catalogue.source_session('Spotify')
    await entity.async_play_media(RADIO_MEDIA_TYPE, item.media_content_id)
    assert entity._radio_catalogue.source_session('Spotify') is saved and session.current is None
    await entity.async_select_source("Spotify")
    await entity.async_select_source("Spotify")
    assert all(c[0]=='GET' for c in session.calls)
    commands.async_play_radio_station.assert_awaited_once()
    commands.async_play_catalogue.assert_awaited_once()
    assert saved.audio_path in commands.async_play_catalogue.await_args.args
    assert not [
        r for r in caplog.records if r.levelno >= logging.WARNING and r.name.startswith("custom_components.loxone")
    ]


@pytest.mark.asyncio
async def test_detached_without_owned_bookmark_keeps_quiet_native_fallback(hass):
    entity, session, snapshots, commands, _, _ = entity_boundary(hass)
    snapshots[0] = native("tunein:station:synthetic")
    session.current = None
    await entity.async_select_source("Spotify")
    commands.async_play_catalogue.assert_awaited_once()
    assert all(c[0] == "GET" for c in session.calls)
