"""Synthetic review11 conflicts, inherited uncertainty and removed-action guards."""

# ruff: noqa: S101, INP001, ANN001, D103, SLF001
import asyncio
import logging
from copy import deepcopy
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from homeassistant.exceptions import HomeAssistantError
from test_spotify_continuity import NEXT, native
from test_spotify_continuity_review import entity_boundary
from custom_components.loxone.pyloxone_api import audioserver as wire
from custom_components.loxone.audio_radio import RadioTarget
from custom_components.loxone.spotify_continuity import SpotifySourceReturn, spotify_room_uncertain


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["capture", "initial", "final"])
@pytest.mark.parametrize("content", ["restricted-track", "episode"])
async def test_positive_paused_content_conflict_is_not_optional_fallback(hass, phase, content):
    entity, session, snapshots, commands, _, old = entity_boundary(hass)
    if phase != "capture":
        await entity._spotify_return.async_capture(lambda: True)
        entity._spotify_choice = ("Spotify", old)
        snapshots[0] = native("tunein:station:synthetic")
    session.current["is_playing"] = False

    async def change() -> None:
        session.current["item"]["uri"] = NEXT if content == "restricted-track" else "spotify:episode:" + "E" * 22
        if content == "restricted-track":
            session.current["device"]["is_restricted"] = True
        else:
            session.current["currently_playing_type"] = "episode"
            session.current["item"]["type"] = "episode"

    if phase == "final":
        async def change_during_read(url):
            if url.endswith('/me'):await change()
        session.on_read=change_during_read
    else:
        await change()
    if phase == "capture":
        item = entity._radio_catalogue._item(
            RadioTarget("station", "Radio", "world", audio_path="tunein:station:synthetic")
        )
        with pytest.raises(wire.AudioCommandError):
            await entity._spotify_return.async_capture(lambda:True)
        await entity.async_play_media(item.media_content_type, item.media_content_id)
        commands.async_play_radio_station.assert_awaited_once()
    else:
        await entity.async_select_source("Spotify")
        commands.async_spotify_handoff.assert_awaited_once()
        assert snapshots[0].audio_path==session.current['item']['uri']
        commands.async_play_radio_station.assert_not_awaited()
    assert any(url.endswith("/me/player") for _, url, _ in session.calls)
    assert all(method == "GET" for method, _, _ in session.calls)
    commands.async_play_catalogue.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("position", ["currently_playing", "upcoming", "upcoming-mixed"])
async def test_observable_episode_queue_conflict_cannot_become_native_fallback(hass, position):
    entity, session, snapshots, commands, _, old = entity_boundary(hass)
    await entity._spotify_return.async_capture(lambda: True)
    entity._spotify_choice = ("Spotify", old)
    snapshots[0] = native("tunein:station:synthetic")
    session.current["is_playing"] = False
    row = {"type": "episode", "uri": "spotify:episode:" + "E" * 22}
    if position == "currently_playing":
        session.queue[position] = row
    else:
        session.queue["queue"][0] = row
        if position == "upcoming-mixed":
            session.queue["queue"][1] = None
    queue=deepcopy(session.queue)
    await entity.async_select_source("Spotify")
    commands.async_spotify_handoff.assert_awaited_once()
    assert session.queue==queue
    assert all(method == "GET" for method, _, _ in session.calls)
    commands.async_play_catalogue.assert_not_awaited()


@pytest.mark.asyncio
async def test_device_rebind_client_close_binding_removal_recreation_keeps_room_fence(hass):
    first, _, _, _, _, _ = entity_boundary(hass)
    first._spotify_return.uncertain = True
    second, _, snapshots, _, _, _ = entity_boundary(hass)
    second.unique_id = "synthetic-rebound-room"
    second._audio_player_id = 8
    snapshots[0] = replace(native(), player_id=8)
    client = wire.AudioServerCommands("audio.example.invalid", lambda: ("synthetic-user", "synthetic-token"))
    second._audio_commands = client
    second._spotify_return = SpotifySourceReturn(
        hass, second._spotify_binding, second.unique_id, 8, client, lambda: snapshots[0]
    )
    assert second._spotify_return.uncertain
    await client.async_close()
    second._spotify_return.close()
    third, _, third_snapshots, commands, _, _ = entity_boundary(hass, binding=None)
    third.unique_id = second.unique_id
    third._audio_player_id = 8
    third_snapshots[0] = replace(native(), player_id=8)
    commands.async_execute = AsyncMock()
    assert not client.source_fences
    assert spotify_room_uncertain(hass, third.unique_id, third._audio_player_id)
    with patch.object(type(hass.bus), "async_fire") as fire:
        for action in ("async_media_play", "async_media_next_track", "async_media_previous_track"):
            with pytest.raises(HomeAssistantError):
                await getattr(third, action)()
        fire.assert_not_called()
    commands.async_execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action", ["async_media_stop", "async_set_volume_level", "async_volume_up", "async_volume_down"]
)
async def test_removed_entity_never_sends_stop_or_volume(hass, monkeypatch, action):
    entity, _, _, _, _, _ = entity_boundary(hass)
    await entity.async_will_remove_from_hass()
    fire = MagicMock()
    monkeypatch.setattr(type(hass.bus), "async_fire", fire)
    with pytest.raises(HomeAssistantError):
        await getattr(entity, action)(*([0.05] if action == "async_set_volume_level" else []))
    fire.assert_not_called()


@pytest.mark.asyncio
async def test_bookmark_expiring_during_reads_uses_native_without_provider_dispatch(hass):
    entity, session, snapshots, commands, _, old = entity_boundary(hass)
    await entity._spotify_return.async_capture(lambda: True)
    saved = entity._spotify_return.bookmark
    # Keep the historical ID for reconciliation. Expiry is now dormant helper
    # state, not an entity timing boundary or native-return prerequisite.
    entity._spotify_return.bookmark = replace(saved, captured=asyncio.get_running_loop().time() - 91)
    entity._spotify_choice = ("Spotify", old)
    snapshots[0] = native("tunein:station:synthetic")
    session.current["is_playing"] = False

    ensure_before=session.ensure.await_count
    session.on_put = AsyncMock()
    await entity.async_select_source("Spotify")
    assert session.ensure.await_count==ensure_before
    assert all(method=='GET' for method,_url,_kwargs in session.calls)
    session.on_put.assert_not_awaited()
    commands.async_play_catalogue.assert_not_awaited()
    commands.async_spotify_handoff.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["stable", "stop", "source", "native-failure"])
async def test_optional_inventory_read_failure_preserves_radio_without_stale_fallback(hass, caplog, change):
    entity, session, snapshots, commands, _, _ = entity_boundary(hass)

    async def failed() -> None:
        if change == "stop":
            await entity.async_media_stop()
            entity._source_generation+=1
        elif change == "source":
            snapshots[0] = native("tunein:station:newer-owner-selection")
        msg = "Synthetic optional account inventory unavailable"
        raise wire.AudioCommandError(msg)

    commands.async_service_accounts.side_effect = failed
    commands.async_recent_sources.return_value={'items':[{'type':2,'audiopath':'tunein:station:synthetic'}]}
    session.ensure.side_effect=failed
    sent=[]
    radio=commands.async_play_radio_station.side_effect
    async def prepare_radio(player,service,path,*,is_current,on_send):
        await asyncio.sleep(0)  # Actual native preparation boundary, not removed capture.
        if change=='stop':entity._source_generation+=1
        elif change=='source':snapshots[0]=native('tunein:station:newer-owner-selection')
        if not is_current():raise wire.AudioCommandError('Synthetic native preparation superseded')
        if change=='native-failure':raise wire.AudioCommandError('Synthetic real native command rejection')
        sent.append(path)
        await radio(player,service,path,is_current=is_current,on_send=on_send)
    commands.async_play_radio_station.side_effect=prepare_radio
    item = entity._radio_catalogue._item(
        RadioTarget("station", "Radio", "world", audio_path="tunein:station:synthetic")
    )
    if change == "stable":
        await entity.async_play_media(item.media_content_type,item.media_content_id)
        commands.async_play_radio_station.assert_awaited_once()
        assert sent==['tunein:station:synthetic']
    else:
        with pytest.raises(HomeAssistantError):
            await entity.async_play_media(item.media_content_type,item.media_content_id)
        commands.async_play_radio_station.assert_awaited_once()  # Preparation entered.
        assert not sent  # No stale or rejected media dispatch.
    session.ensure.assert_not_awaited()  # Optional departure inventory is not a prerequisite.
    commands.async_service_accounts.assert_not_awaited()
    assert not session.calls
    warnings = [
        record
        for record in caplog.records
        if record.name.startswith("custom_components.loxone") and record.levelno >= logging.WARNING
    ]
    assert [record.getMessage() for record in warnings] == (
        [] if change == "stable" else ["Audio content selection failed; no automatic retry was sent"]
    )
