"""One account snapshot per native selection, still exact-account validated."""

# Fixture-driven tests intentionally access entity internals and use assertions.
# ruff: noqa: ANN001, ANN002, ANN003, ANN202, D103, F811, INP001, PLR2004, S101, SLF001
from unittest.mock import AsyncMock

import pytest
from test_audioserver_ha import audio_setup  # noqa: F401
from test_native_source_return_ha import install_sources, library_row, RADIO

from custom_components.loxone import audio_sources
from custom_components.loxone.audio_catalogue import CatalogueTarget
from custom_components.loxone.pyloxone_api import audioserver as wire


@pytest.mark.asyncio
async def test_actual_entity_uses_one_account_snapshot_for_native_spotify_selection(hass, audio_setup, monkeypatch):
    entity, emit, writes = await install_sources(hass, audio_setup, monkeypatch, spotify=True)
    accounts = AsyncMock(
        return_value=[
            {
                "cmd": "spotify",
                "id": "synthetic-account",
                "user": "Synthetic owner",
                "configerror": False,
            }
        ]
    )
    monkeypatch.setattr(wire.AudioServerCommands, "async_service_accounts", accounts)
    original = audio_sources.async_select_catalogue
    reads = []

    async def counted(*args, **kwargs):
        before = accounts.await_count
        await original(*args, **kwargs)
        reads.append(accounts.await_count - before)

    monkeypatch.setattr(audio_sources, "async_select_catalogue", counted)
    await emit(
        library_row(
            audiopath="spotify:track:original", parent={"id": "spotify:playlist:original"}, sourceName="Synthetic owner"
        )
    )
    await emit({"playerid": 7, "mode": "play", "eventype": 0, "audiopath": RADIO})
    await hass.services.async_call(
        "media_player",
        "select_source",
        {
            "entity_id": entity.entity_id,
            "source": "Spotify",
        },
        blocking=True,
    )
    assert reads == [1]
    assert len(writes) == 2
    assert writes[0].startswith("audio/7/serviceplay/spotify/synthetic-account/")
    assert writes[-1] == "audio/7/position/45.0"
    assert entity._audio_metadata.get(7).audio_path == "spotify:track:original"
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rows", [[], [{"cmd": "spotify", "id": "synthetic-account", "user": "Synthetic owner", "configerror": True}]]
)
async def test_one_snapshot_still_rejects_missing_or_unhealthy_account(hass, audio_setup, monkeypatch, rows):
    entity, emit, writes = await install_sources(hass, audio_setup, monkeypatch, spotify=True)
    await emit(library_row(audiopath=RADIO, parent={"id": "radio"}, time=0))
    monkeypatch.setattr(wire.AudioServerCommands, "async_service_accounts", AsyncMock(return_value=rows))
    target = CatalogueTarget(
        "item",
        "Synthetic",
        "spotify",
        "spotify:track:original",
        audio_path="spotify:track:original",
        account="synthetic-account",
    )
    with pytest.raises(wire.AudioCommandError):
        await audio_sources.async_select_catalogue(
            entity._audio_commands, entity._audio_metadata, 7, target, is_available=lambda: True
        )
    assert writes == []
