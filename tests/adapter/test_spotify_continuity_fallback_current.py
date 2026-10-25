"""Synthetic review21 current fallback clock, native no-ops and fresh history."""

# ruff: noqa: S101, INP001, ANN001, D103, SLF001
import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock

from aiohttp import ClientConnectionError
import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from test_spotify_continuity import NEXT, native
from test_spotify_continuity_conflicts import _saved

NATIVE_PREPARE_READ = 1


def native_reads(entity, commands):
    commands.async_source_inputs = AsyncMock(return_value=[])
    commands.async_recent_sources = AsyncMock(
        return_value={
            "items": [
                {
                    "audiopath": "spotify@native-owner:playlist:" + "C" * 22,
                    "type": 7,
                    "title": "Old",
                }
            ]
        }
    )
    entity._radio_catalogue._source_accounts = commands.async_service_accounts.return_value


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["read-failure", "expiration", "native-prepare"])
async def test_paused_seek_cannot_be_hidden_by_optional_fallback(hass, phase):
    entity, session, snapshots, commands = await _saved(hass)
    native_reads(entity, commands)
    snapshots[0] = native(mode="pause")
    if phase == "read-failure":

        async def failed(_url) -> None:
            snapshots[0] = replace(native(mode="pause"), position=40)
            message = "Synthetic pre-dispatch read loss"
            raise ClientConnectionError(message)

        session.on_read = failed
    elif phase == "expiration":

        async def expire() -> None:
            snapshots[0] = replace(native(mode="pause"), position=40)
            entity._spotify_return.bookmark = replace(
                entity._spotify_return.bookmark,
                captured=asyncio.get_running_loop().time() - 100,
            )

        # Capture age is irrelevant, but a paused seek during an ACTUAL
        # successful optional read must still supersede the pending return.
        async def expired_during_read(_url):await expire()
        session.on_read=expired_during_read
    else:
        hass.config_entries.async_get_entry("synthetic-entry").state = ConfigEntryState.NOT_LOADED
        baseline_reads = commands.async_service_accounts.await_count

        async def changed() -> list:
            if commands.async_service_accounts.await_count >= baseline_reads + NATIVE_PREPARE_READ:
                snapshots[0] = replace(native(mode="pause"), position=40)
            return commands.async_service_accounts.return_value

        commands.async_service_accounts.side_effect = changed
    with pytest.raises(HomeAssistantError):
        await entity.async_select_source("Spotify")
    assert all(method == "GET" for method, _, _ in session.calls)
    commands.async_play_catalogue.assert_not_awaited()
    commands.async_play_radio_station.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("availability", ["unloaded", "disabled", "outage", "session-absent"])
@pytest.mark.parametrize("ownership", ["owned", "foreign-account", "other-context"])
async def test_unconsumed_capture_cannot_poison_proven_active_native_noop(hass, availability, ownership):
    entity, session, snapshots, commands = await _saved(hass)
    native_reads(entity, commands)
    snapshots[0] = replace(native(), audio_path=NEXT)
    if ownership == "foreign-account":
        snapshots[0] = replace(snapshots[0], source_name="foreign-native-user")
    elif ownership == "other-context":
        snapshots[0] = replace(snapshots[0], parent_id="spotify:playlist:" + "D" * 22)
    provider = hass.config_entries.async_get_entry("synthetic-entry")
    if availability == "unloaded":
        provider.state = ConfigEntryState.NOT_LOADED
    elif availability == "disabled":
        provider.disabled_by = "user"
    elif availability == "session-absent":
        provider.runtime_data.session = None
    else:
        session.async_request = AsyncMock(side_effect=ClientConnectionError("Synthetic optional outage"))
    before = snapshots[0]
    if ownership in ("owned", "other-context"):
        await entity.async_select_source("Spotify")
        commands.async_spotify_handoff.assert_not_awaited()
    else:
        with pytest.raises(HomeAssistantError):
            await entity.async_select_source("Spotify")
    assert snapshots[0] is before
    assert all(method == "GET" for method, _, _ in session.calls)
    commands.async_play_catalogue.assert_not_awaited()
    commands.async_play_radio_station.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("history", ["omitted", "newer"])
async def test_retained_spotify_choice_is_fallback_only_after_fresh_native_history(hass, history):
    entity, session, _, commands = await _saved(hass)
    native_reads(entity, commands)
    hass.config_entries.async_get_entry("synthetic-entry").state = ConfigEntryState.NOT_LOADED
    target = entity._radio_catalogue.source_choices["Spotify"]
    path = "spotify@native-owner:playlist:" + "D" * 22
    newer = replace(target, folder=path, audio_path=path)

    async def refreshed() -> None:
        entity._radio_catalogue.source_choices = {} if history == "omitted" else {"Spotify": newer}

    entity._radio_catalogue.async_refresh_sources = AsyncMock(side_effect=refreshed)
    # Either history variant retains the genuinely successful exact item.
    # Discovery alone must not invent success or replace the retained record.
    await entity.async_select_source("Spotify")
    entity._radio_catalogue.async_refresh_sources.assert_awaited_once()
    assert commands.async_play_catalogue.await_args.args[-1]=='spotify:track:'+'A'*22
    assert all(method == "GET" for method, _, _ in session.calls)
