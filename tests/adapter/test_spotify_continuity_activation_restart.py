"""Core-restart simulation retains disk only, not any in-memory provider fence."""

# ruff: noqa: S101, INP001, ANN001, ANN202, D103, SLF001
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from homeassistant.exceptions import HomeAssistantError
from custom_components.loxone import media_player
from custom_components.loxone.pyloxone_api.audioserver import AudioCommandError
from test_spotify_continuity import CONFIG, native
from test_spotify_continuity_activation import ActivationSession
from test_spotify_continuity_review import entity_boundary


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["activate-disconnect", "play-disconnect", "success"])
@pytest.mark.parametrize("keep_binding", [False, True])
async def test_disk_uncertainty_blocks_native_fallback_after_cold_lifecycle(
    hass, tmp_path, monkeypatch, outcome, keep_binding
):
    hass.config.config_dir = str(tmp_path)
    entity, original, snapshots, commands, provider, _ = entity_boundary(hass)
    session = ActivationSession(original, Path(hass.config.path(".storage", "pyloxone_spotify_return_dispatch")))
    provider.runtime_data.session = session
    entity._radio_catalogue._source_accounts=commands.async_service_accounts.return_value
    entity._radio_catalogue.remember_source(snapshots[0])
    snapshots[0] = native("tunein:station:synthetic")
    session.current['is_playing']=False

    async def disconnect(_player,_account,*,is_current,on_send):
        assert is_current()
        on_send()
        if outcome=='play-disconnect':
            snapshots[0]=None
        raise AudioCommandError('Synthetic native disconnect after dispatch')

    if outcome!='success':
        commands.async_spotify_handoff.side_effect=disconnect
    if outcome == "success":
        await entity.async_select_source("Spotify")
    else:
        with pytest.raises((HomeAssistantError, ConnectionResetError)):
            await entity.async_select_source("Spotify")
        assert commands.source_fences
        commands.async_play_catalogue.assert_not_awaited()
    entity._spotify_return.close()
    for key in tuple(hass.data):
        if isinstance(key, str) and key.startswith("pyloxone_spotify_return"):
            hass.data.pop(key)
    replacement, session2, snapshots2, commands2, _, _ = entity_boundary(hass, CONFIG if keep_binding else None)
    commands2.async_execute=AsyncMock()
    snapshots2[0] = native("tunein:station:synthetic")
    session2.current = None
    monkeypatch.setattr(media_player.LoxoneEntity, "async_added_to_hass", AsyncMock())
    monkeypatch.setattr(replacement, "_async_refresh_audio_sources", AsyncMock())
    monkeypatch.setattr(replacement, "_update_audio_metadata", lambda: None)
    await replacement.async_added_to_hass()
    if outcome == "success":
        await replacement.async_select_source("Spotify")
        commands2.async_play_catalogue.assert_awaited_once()
    else:
        # Startup is not a new explicit return; no automatic replay is allowed.
        await hass.async_block_till_done()
        commands2.async_play_catalogue.assert_not_awaited()
        commands2.async_spotify_handoff.assert_not_awaited()
        commands2.async_execute.assert_not_awaited()
        assert all(c[0] == "GET" for c in session2.calls)
