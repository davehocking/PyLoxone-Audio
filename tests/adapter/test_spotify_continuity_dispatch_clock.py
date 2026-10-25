"""Synthetic review20 local paused-seek changes at the final dispatch boundary."""

# ruff: noqa: S101, INP001, ANN001, D103, SLF001
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError
from test_spotify_continuity import native
from test_spotify_continuity_conflicts import _saved
from custom_components.loxone.pyloxone_api.audioserver import AudioCommandError

FINAL_QUEUE = 1
ORIGINAL_POSITION = 13.264


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["final-queue", "middleware"])
@pytest.mark.parametrize("position", [ORIGINAL_POSITION, 40.0])
async def test_paused_native_position_is_rechecked_at_final_send(hass, phase, position):
    entity, session, snapshots, commands = await _saved(hass)
    snapshots[0] = native(mode="pause")
    session.on_put = AsyncMock()
    reads = 0
    original = commands.async_spotify_handoff.side_effect
    sent=[]

    async def changed(url) -> None:
        nonlocal reads
        if url.endswith("/me/player"):
            reads += 1
            if reads == FINAL_QUEUE and phase == "final-queue":
                snapshots[0] = native(mode="pause")
                snapshots[0] = replace(snapshots[0], position=position)

    async def request(player,account,*,is_current,on_send):
        if phase == "middleware":
            snapshots[0] = replace(native(mode="pause"), position=position)
        if not is_current():raise AudioCommandError('Synthetic final native guard rejected changed position')
        sent.append(True)
        return await original(player,account,is_current=is_current,on_send=on_send)

    session.on_read = changed
    commands.async_spotify_handoff.side_effect=request
    if position == ORIGINAL_POSITION:
        await entity.async_select_source("Spotify")
        commands.async_spotify_handoff.assert_awaited_once()
        assert sent==[True]
    else:
        with pytest.raises(HomeAssistantError):
            await entity.async_select_source("Spotify")
        # Session.calls counts a prepared OAuth request even if middleware
        # rejects it. on_put is the actual fake transport send boundary.
        session.on_put.assert_not_awaited()
        assert not sent
        if phase == "final-queue":
            assert all(method == "GET" for method, _, _ in session.calls)
        assert not entity._spotify_return.uncertain
    commands.async_play_catalogue.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_already_playing_with_paused_provider_view_uses_native_noop(hass):
    entity, session, snapshots, commands = await _saved(hass)
    snapshots[0] = native()
    await entity.async_select_source("Spotify")
    assert all(method == "GET" for method, _, _ in session.calls)
    commands.async_play_catalogue.assert_not_awaited()
    commands.async_spotify_handoff.assert_not_awaited()
