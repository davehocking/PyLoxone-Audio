"""Independent review regressions at the real HA entity action boundary."""

# ruff: noqa: S101, INP001, ANN001, ANN003, ANN202, D103, SLF001, PLC0415
import logging
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from homeassistant.exceptions import HomeAssistantError
from test_spotify_continuity import CONFIG, native, setup_boundary
from custom_components.loxone.media_player import LoxoneAudioZoneV2
from custom_components.loxone.audio_catalogue import CatalogueTarget, ConfiguredSource
from custom_components.loxone.audio_radio import RADIO_MEDIA_TYPE, RadioTarget
from custom_components.loxone.pyloxone_api.audioserver import AudioCommandError
from custom_components.loxone.const import SENDDOMAIN


def entity_boundary(hass, binding=CONFIG):
    _original, session, snapshots, commands, provider = setup_boundary(hass)
    entity = LoxoneAudioZoneV2(
        hass=hass,
        name="Synthetic",
        uuidAction="synthetic-room",
        room="Synthetic",
        cat="Audio",
        states={"playState": "play", "volume": "volume"},
        details={"playerid": 7},
        audio_metadata=SimpleNamespace(
            get=lambda _: snapshots[0],
            # This unit boundary has no passive socket or status transport.
            # Actual HA status-bootstrap contracts live in test_audio_cold_start_ha.
            async_ensure_snapshot=AsyncMock(side_effect=AudioCommandError("Synthetic passive stream absent")),
        ),
        audio_commands=commands,
        audio_commands_enabled=True,

    )
    listeners = []

    class PublishedSnapshots(list):
        def __setitem__(self, key, value) -> None:
            super().__setitem__(key, value)
            for callback in tuple(listeners):
                callback()

    snapshots = PublishedSnapshots(snapshots)
    session.snapshot = snapshots
    entity._audio_metadata.get = lambda _: snapshots[0]

    def subscribe(_player, callback):
        listeners.append(callback)
        return lambda: listeners.remove(callback) if callback in listeners else None

    entity._audio_metadata.async_add_listener = subscribe

    async def radio(_player, _service, path, *, is_current, on_send):
        assert is_current()
        on_send()
        snapshots[0] = native(path)

    commands.async_play_radio_station = AsyncMock(side_effect=radio)

    async def catalogue(_player, _service, _account, _path, *, is_current, on_send, **kwargs):
        assert is_current()
        on_send()
        snapshots[0] = native()

    commands.async_play_catalogue = AsyncMock(side_effect=catalogue)

    async def handoff(_player, _account, *, is_current, on_send):
        # Current native interface, not the retired provider PUT/capture path.
        assert is_current()
        on_send()
        state = session.current
        previous = snapshots[0]
        if previous.source == 'Spotify' and previous.native_mode == 'pause':
            # Native resume preserves the current session, not historical data.
            snapshots[0] = replace(previous,native_mode='play',received_at=native().received_at)
            return
        item = state.get('item') if isinstance(state, dict) else None
        context = state.get('context') if isinstance(state, dict) else None
        progress = state.get('progress_ms') if isinstance(state, dict) else None
        snapshots[0] = replace(
            native(), audio_path=item['uri'] if isinstance(item, dict) else previous.audio_path,
            parent_id=context.get('uri') if isinstance(context, dict) else None,
            position=progress / 1000 if type(progress) in (int,float) else None,
        )

    commands.async_spotify_handoff = AsyncMock(side_effect=handoff)
    entity.entity_id = "media_player.synthetic"
    entity.async_write_ha_state = lambda: None
    entity.async_schedule_update_ha_state = lambda: None
    target = CatalogueTarget(
        "item",
        "Old",
        "spotify",
        "spotify@native-owner:playlist:" + "C" * 22,
        audio_path="spotify@native-owner:playlist:" + "C" * 22,
        account="native-owner",
        is_context=True,
    )
    entity._radio_catalogue.source_choices = {"Spotify": target}
    entity._radio_catalogue.source_descriptors = {
        "Spotify": ConfiguredSource("spotify", "native-owner"),
        "TuneIn": ConfiguredSource("tunein"),
    }
    commands.async_search_capabilities = AsyncMock(return_value={"tunein": ["station"]})
    commands.async_radio_services = AsyncMock(return_value=[{"cmd": "world", "root": "root", "name": "World"}])
    commands.async_source_inputs = AsyncMock(return_value=[])
    commands.async_media_folder = AsyncMock(return_value=[{
        'start':0,'totalitems':1,'items':[{
            'type':2,'id':'spotify@native-owner:track:'+'A'*22,
            'audiopath':'spotify@native-owner:track:'+'A'*22,'name':'Synthetic remembered item',
        }],
    }])
    commands.async_recent_sources = AsyncMock(
        return_value={
            "items": [
                {
                    "audiopath": target.audio_path,
                    "type": 7,
                    "title": "Old",
                }
            ]
        }
    )
    return entity, session, snapshots, commands, provider, target


def seed_last_good(entity,snapshot):
    """Seed confirmed native success, never discovered history."""
    entity._radio_catalogue._source_accounts=entity._audio_commands.async_service_accounts.return_value
    entity._radio_catalogue.remember_source(snapshot)


@pytest.mark.asyncio
async def test_capture_ownership_rejection_cannot_fall_through_to_native_radio(hass):
    entity, session, snapshots, commands, _, _ = entity_boundary(hass)

    async def changed():
        snapshots[0] = native("tunein:station:someone-else")
        return commands.async_service_accounts.return_value

    commands.async_service_accounts.side_effect=changed
    commands.async_recent_sources.return_value={'items':[{'type':2,'audiopath':'tunein:station:synthetic'}]}
    item = entity._radio_catalogue._item(
        RadioTarget("station", "Radio", "world", audio_path="tunein:station:synthetic")
    )
    with pytest.raises(HomeAssistantError):
        await entity.async_select_source('TuneIn')
    commands.async_service_accounts.assert_awaited_once()
    commands.async_play_radio_station.assert_not_awaited()








@pytest.mark.asyncio
async def test_capture_without_provider_playback_keeps_native_radio_quiet(hass, caplog):
    entity, session, _snapshots, commands, _provider, _target = entity_boundary(hass)
    session.current = None
    item = entity._radio_catalogue._item(
        RadioTarget("station", "Radio", "world", audio_path="tunein:station:synthetic")
    )
    await entity.async_play_media(RADIO_MEDIA_TYPE, item.media_content_id)
    commands.async_play_radio_station.assert_awaited_once()
    assert all(call[0] == "GET" for call in session.calls)
    assert not [
        r for r in caplog.records if r.levelno >= logging.WARNING and r.name.startswith("custom_components.loxone")
    ]
















@pytest.mark.asyncio
async def test_refreshed_native_spotify_selection_supersedes_retained_history(hass):
    entity, _, snapshots, commands, _, old = entity_boundary(hass)
    seed_last_good(entity,snapshots[0])
    saved=entity._radio_catalogue.source_session('Spotify')
    newer = replace(
        old,
        label="New",
        folder="spotify@native-owner:playlist:" + "D" * 22,
        audio_path="spotify@native-owner:playlist:" + "D" * 22,
    )
    entity._radio_catalogue.source_choices = {"Spotify": newer}
    assert entity._radio_catalogue.source_choices["Spotify"] == newer
    assert entity._radio_catalogue.source_session('Spotify') is saved
    entity._radio_catalogue.remember_source(replace(native(),parent_id='spotify:playlist:'+'D'*22))
    entity._radio_catalogue.remember_source(replace(native(),parent_id='spotify:playlist:'+'D'*22,position=14))
    assert entity._radio_catalogue.source_session('Spotify').parent_id=='spotify:playlist:'+'D'*22
    commands.async_play_catalogue.assert_not_awaited()
