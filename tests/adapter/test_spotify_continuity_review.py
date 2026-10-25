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
        spotify_return_binding=binding,
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
async def test_persistent_uncertainty_blocks_explicit_native_play_after_client_recreation(hass):
    entity, _, snapshots, commands, _, target = entity_boundary(hass)
    entity._spotify_return.uncertain = True
    snapshots[0] = native("tunein:station:synthetic")
    assert not commands.source_fences
    item = entity._radio_catalogue._item(target)
    await entity.async_play_media(RADIO_MEDIA_TYPE, item.media_content_id)
    commands.async_play_catalogue.assert_awaited_once()
    assert entity._spotify_return.uncertain


@pytest.mark.asyncio
async def test_deliberate_spotify_content_retires_old_bookmark_and_retained_choice(hass):
    entity, _, snapshots, commands, _, old = entity_boundary(hass)
    entity._audio_metadata.artwork_url=lambda _url:None
    await entity._spotify_return.async_capture(lambda: True)
    seed_last_good(entity,snapshots[0])
    snapshots[0] = native("tunein:station:synthetic")
    newer = replace(
        old,
        label="New",
        folder="spotify@native-owner:playlist:" + "D" * 22,
        audio_path="spotify@native-owner:playlist:" + "D" * 22,
    )

    async def play(_player, _service, _account, _path, *, is_current, on_send):
        assert is_current()
        on_send()
        snapshots[0] = replace(native(), parent_id="spotify:playlist:" + "D" * 22)
        entity._update_audio_metadata()  # Actual coordinator/entity callback.

    commands.async_play_catalogue = play
    item = entity._radio_catalogue._item(newer)
    await entity.async_play_media(RADIO_MEDIA_TYPE, item.media_content_id)
    assert entity._spotify_return.bookmark is None
    assert entity._radio_catalogue.source_session('Spotify').parent_id=='spotify:playlist:'+'D'*22


@pytest.mark.asyncio
async def test_optional_unload_retains_native_return_when_recent_history_loses_spotify(hass):
    from homeassistant.config_entries import ConfigEntryState

    entity, session, snapshots, commands, provider, old = entity_boundary(hass)
    await entity._spotify_return.async_capture(lambda: True)
    entity._spotify_choice = ("Spotify", old)
    snapshots[0] = native("tunein:station:synthetic")
    session.current["is_playing"] = False
    provider.state = ConfigEntryState.NOT_LOADED
    seed_last_good(entity,native())
    commands.async_source_inputs = AsyncMock(return_value=[])
    commands.async_recent_sources = AsyncMock(
        return_value={"items": [{"audiopath": "tunein:station:synthetic", "type": 2}]}
    )
    await entity.async_select_source("Spotify")
    commands.async_play_catalogue.assert_awaited_once()
    assert not [call for call in session.calls if call[0] == "PUT"]


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
async def test_missing_optional_receiver_keeps_native_source_quiet(hass, caplog):
    entity, session, snapshots, commands, _provider, old = entity_boundary(hass)
    await entity._spotify_return.async_capture(lambda: True)
    entity._spotify_choice = ("Spotify", old)
    snapshots[0] = native("tunein:station:synthetic")
    session.current["is_playing"] = False
    original_request = session.async_request

    async def request(method, url, **kwargs):
        if url.endswith("/devices"):
            return SimpleNamespace(status=200, json=AsyncMock(return_value={"devices": []}), release=lambda: None)
        return await original_request(method, url, **kwargs)

    session.async_request = request
    await entity.async_select_source("Spotify")
    commands.async_spotify_handoff.assert_awaited_once()
    commands.async_play_catalogue.assert_not_awaited()
    assert all(call[0] == "GET" for call in session.calls)
    assert not [
        r for r in caplog.records if r.levelno >= logging.WARNING and r.name.startswith("custom_components.loxone")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("binding", [None, {"invalid": True}])
@pytest.mark.parametrize("action", ["source", "content", "play", "next"])
async def test_uncertain_room_survives_client_and_binding_removal(hass, monkeypatch, binding, action):
    import asyncio

    entity, session, snapshots, commands, _provider, old = entity_boundary(hass)
    await entity._spotify_return.async_capture(lambda: True)
    entity._spotify_choice = ("Spotify", old)
    snapshots[0] = native("tunein:station:synthetic")
    session.current["is_playing"] = False
    session.update_native = False
    async def ambiguous_native(_player,_account,*,is_current,on_send):
        assert is_current()
        on_send()
        await asyncio.Event().wait()
    commands.async_spotify_handoff.side_effect=ambiguous_native
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.05):
            await entity.async_select_source("Spotify")
    assert commands.source_fences
    commands.async_play_catalogue.assert_not_awaited()
    entity._spotify_return.close()
    for release in tuple(commands.source_fences.values()):
        release()
    fire=MagicMock()
    monkeypatch.setattr(type(hass.bus),'async_fire',fire)
    recreated, new_session, new_snapshots, new_commands, _, target = entity_boundary(hass, binding)
    new_snapshots[0] = native("tunein:station:synthetic")
    new_commands.async_execute = AsyncMock()
    item = recreated._radio_catalogue._item(target)
    actions = {
        "source": lambda: recreated.async_select_source("Spotify"),
        "content": lambda: recreated.async_play_media(RADIO_MEDIA_TYPE, item.media_content_id),
        "play": recreated.async_media_play,
        "next": recreated.async_media_next_track,
    }
    # Recreation is not a request. A NEW explicit action is not automatic replay.
    new_commands.async_play_catalogue.assert_not_awaited()
    new_commands.async_spotify_handoff.assert_not_awaited()
    new_commands.async_execute.assert_not_awaited()
    fire.assert_not_called()
    assert not new_session.calls
    await actions[action]()
    if action in ('source','content'):new_commands.async_play_catalogue.assert_awaited_once()
    elif action=='play':new_commands.async_execute.assert_awaited_once()
    else:
        # Direct explicit method calls retain the Miniserver bus route even
        # though radio does not advertise HA's track-skip capability.
        new_commands.async_execute.assert_not_awaited()
        fire.assert_called_once_with(SENDDOMAIN,dict(uuid=recreated.uuidAction,value='next'))
    if action!='next':fire.assert_not_called()
    assert all(call[0]=='GET' for call in new_session.calls)


@pytest.mark.asyncio
async def test_native_metadata_loss_during_resume_is_controlled_without_dispatch(hass):
    entity, session, snapshots, _commands, _provider, _old = entity_boundary(hass)
    await entity._spotify_return.async_capture(lambda: True)
    snapshots[0] = native("tunein:station:synthetic")

    async def lose_metadata(url):
        if url.endswith("/me/player"):
            snapshots[0] = None

    session.on_read = lose_metadata
    from custom_components.loxone.pyloxone_api.audioserver import AudioCommandError

    with pytest.raises(AudioCommandError):
        await entity._spotify_return.async_resume(lambda: True)
    assert all(call[0] == "GET" for call in session.calls)


@pytest.mark.asyncio
async def test_positive_queue_identity_change_never_falls_back_to_native_start(hass):
    from test_spotify_continuity import NEXT

    entity, session, snapshots, commands, _, old = entity_boundary(hass)
    await entity._spotify_return.async_capture(lambda: True)
    entity._spotify_choice = ("Spotify", old)
    snapshots[0] = native("tunein:station:synthetic")
    session.current["is_playing"] = False
    session.queue["currently_playing"]["uri"] = NEXT
    before=deepcopy(session.queue)
    await entity.async_select_source("Spotify")
    commands.async_spotify_handoff.assert_awaited_once()
    assert session.queue==before
    commands.async_play_catalogue.assert_not_awaited()
    assert all(call[0] == "GET" for call in session.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["async_media_next_track", "async_media_previous_track", "async_media_play"])
async def test_transport_action_cannot_race_resume_preparation(hass, action):
    import asyncio
    from unittest.mock import patch

    entity, session, snapshots, commands, _, old = entity_boundary(hass)
    await entity._spotify_return.async_capture(lambda: True)
    entity._spotify_choice = ("Spotify", old)
    snapshots[0] = native("tunein:station:synthetic")
    session.current["is_playing"] = False
    commands.async_execute = AsyncMock()
    entered, release = asyncio.Event(), asyncio.Event()

    async def hold(_url):
        entered.set()
        await release.wait()

    session.on_read = hold
    task = asyncio.create_task(entity.async_select_source("Spotify"))
    try:
        async with asyncio.timeout(1):
            await entered.wait()
        with patch.object(type(hass.bus), "async_fire", autospec=True) as fire:
            with pytest.raises(HomeAssistantError):
                await getattr(entity, action)()
            fire.assert_not_called()
        commands.async_execute.assert_not_awaited()
    finally:
        release.set()
        await task


@pytest.mark.asyncio
async def test_missing_identity_after_owned_activation_never_uses_native_fallback(hass, tmp_path):
    from pathlib import Path
    from test_spotify_continuity_activation import ActivationSession

    entity, session, snapshots, commands, provider, old = entity_boundary(hass)
    await entity._spotify_return.async_capture(lambda: True)
    entity._spotify_choice = ("Spotify", old)
    snapshots[0] = native("tunein:station:synthetic")
    session.current['is_playing']=False
    hass.config.config_dir = str(tmp_path)
    session = ActivationSession(session, Path(hass.config.path(".storage", "pyloxone_spotify_return_dispatch")))
    provider.runtime_data.session = session

    async def still_detached(_player,_account,*,is_current,on_send):
        assert is_current()
        on_send()
        snapshots[0]=None
    commands.async_spotify_handoff.side_effect=still_detached
    with pytest.raises(HomeAssistantError):
        await entity.async_select_source("Spotify")
    commands.async_play_catalogue.assert_not_awaited()
    assert session.transfer_count == 0
    assert commands.source_fences
    commands.async_spotify_handoff.assert_awaited_once()
    assert all(call[0]=='GET' for call in session.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["capture", "resume"])
async def test_stop_followed_by_read_failure_never_enters_native_fallback(hass, phase):
    from aiohttp import ClientError

    entity, session, snapshots, commands, _, old = entity_boundary(hass)
    if phase == "resume":
        await entity._spotify_return.async_capture(lambda: True)
        entity._spotify_choice = ("Spotify", old)
        snapshots[0] = native("tunein:station:synthetic")

    async def stopped(_url):
        await entity.async_media_stop()
        entity._source_generation+=1  # Independent intent, not nested helper.
        msg = "synthetic provider unavailable after stop"
        raise ClientError(msg)

    session.on_read = stopped
    if phase=='capture':
        async def stopped_inventory():
            await stopped('native source inventory')
        commands.async_service_accounts.side_effect=stopped_inventory
    entity._radio_catalogue.async_source_selection = AsyncMock(
        return_value=entity._radio_catalogue._item(old).media_content_id
    )
    with pytest.raises(HomeAssistantError):  # noqa: PT012 - two distinct HA action signatures
        if phase == "resume":
            await entity.async_select_source("Spotify")
        else:
            await entity.async_select_source('TuneIn')
    commands.async_play_catalogue.assert_not_awaited()
    commands.async_play_radio_station.assert_not_awaited()
    assert all(call[0] == "GET" for call in session.calls)


@pytest.mark.asyncio
async def test_refreshed_native_spotify_selection_supersedes_retained_history(hass):
    entity, _, snapshots, commands, _, old = entity_boundary(hass)
    await entity._spotify_return.async_capture(lambda: True)
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


@pytest.mark.asyncio
async def test_stop_during_capture_account_lock_wait_prevents_native_start(hass):
    import asyncio

    entity, session, snapshots, commands, _, _old = entity_boundary(hass)
    controller = entity._spotify_return
    snapshots[0]=native('tunein:station:synthetic')
    session.current['is_playing']=False
    item = entity._radio_catalogue._item(
        RadioTarget("station", "Radio", "world", audio_path="tunein:station:synthetic")
    )
    lock = controller._account["lock"]
    await lock.acquire()
    task = asyncio.create_task(entity.async_select_source('Spotify'))
    try:
        await asyncio.sleep(0)
        assert entity._source_task is task
        await entity.async_media_stop()
    finally:
        lock.release()
    # Stop now actively cancels native preparation, in addition to invalidating
    # the provider generation. Both outcomes must retain zero playback sends.
    with pytest.raises((HomeAssistantError, asyncio.CancelledError)):
        await task
    commands.async_spotify_handoff.assert_not_awaited()
    commands.async_play_radio_station.assert_not_awaited()
    assert all(call[0] == "GET" for call in session.calls)


@pytest.mark.asyncio
async def test_explicit_stop_invalidates_pending_resume_before_dispatch(hass):
    from custom_components.loxone.pyloxone_api.audioserver import AudioCommandError

    entity, session, snapshots, _commands, _, _old = entity_boundary(hass)
    await entity._spotify_return.async_capture(lambda: True)
    snapshots[0] = native("tunein:station:synthetic")
    session.current["is_playing"] = False

    async def stop(_url):
        await entity.async_media_stop()

    session.on_read = stop
    with pytest.raises(AudioCommandError):
        await entity._spotify_return.async_resume(lambda: True)
    assert all(call[0] == "GET" for call in session.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["capture", "resume"])
async def test_matching_restricted_optional_receiver_keeps_native_actions_quiet(hass, caplog, phase):
    entity, session, snapshots, commands, _, old = entity_boundary(hass)
    if phase == "resume":
        await entity._spotify_return.async_capture(lambda: True)
        entity._spotify_choice = ("Spotify", old)
        snapshots[0] = native("tunein:station:synthetic")
        # Capability-only fallback requires no positively active foreign work.
        # Active restricted playback is covered separately as an ownership error.
        session.current["is_playing"] = False
    session.current["device"]["is_restricted"] = True
    if phase == "capture":
        item = entity._radio_catalogue._item(
            RadioTarget("station", "Radio", "world", audio_path="tunein:station:synthetic")
        )
        await entity.async_play_media(RADIO_MEDIA_TYPE, item.media_content_id)
        commands.async_play_radio_station.assert_awaited_once()
    else:
        await entity.async_select_source("Spotify")
        commands.async_spotify_handoff.assert_awaited_once()
        commands.async_play_catalogue.assert_not_awaited()
    assert all(call[0] == "GET" for call in session.calls)
    assert not [
        r for r in caplog.records if r.levelno >= logging.WARNING and r.name.startswith("custom_components.loxone")
    ]
