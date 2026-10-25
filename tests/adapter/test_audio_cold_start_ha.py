"""Frozen actual-HA cold-action contracts; synthetic transport/state only."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError
from test_audioserver_ha import audio_setup, zone_entity_id
from custom_components.loxone.pyloxone_api import audioserver as wire


STOPPED = {"playerid": 7, "mode": "stop", "audiopath": "tunein:station:before"}


def snapshot(row):
    return wire.parse_audio_events({"audio_event": [row]})[0]


async def prepare(hass, audio_setup, monkeypatch, *, reload=False):
    monkeypatch.setattr(
        wire.AudioServerCommands, "async_recent_sources",
        AsyncMock(return_value={"items": [{"type": 2, "title": "Synthetic Radio", "audiopath": "tunein:station:one"}], "ts": 0}),
    )
    entry = await audio_setup.setup(playback=True)
    if reload:
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    assert entity._audio_metadata.get(7) is None
    assert entity._audio_metadata.get(8) is None
    sent = AsyncMock()

    async def play(self, player, service, path, *, is_current, on_send):
        assert player == 7 and service == "world" and path == "tunein:station:one"
        assert is_current()
        on_send()
        await sent(player, service, path)
        audio_setup.queues[-1].put_nowait(json.dumps({"audio_event": [{"playerid": player, "mode": "play", "audiopath": path}]}))

    monkeypatch.setattr(wire.AudioServerCommands, "async_play_radio_station", play)
    return entry, entity, sent


async def action(hass, entity, kind):
    if kind == "source":
        service, data = "select_source", {"source": "TuneIn"}
    else:
        media_id = await entity._radio_catalogue.async_source_selection("TuneIn")
        service, data = "play_media", {"media_content_type": "pyloxone_radio", "media_content_id": media_id}
    await hass.services.async_call("media_player", service, {"entity_id": entity.entity_id, **data}, blocking=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("reload", [False, True])
@pytest.mark.parametrize("kind", ["source", "browse"])
async def test_cold_actual_setup_action_uses_exact_status_once_without_initial_events(hass, audio_setup, monkeypatch, reload, kind):
    read = AsyncMock(return_value=snapshot(STOPPED))
    monkeypatch.setattr(wire.AudioServerCommands, "async_player_status", read, raising=False)
    _, entity, sent = await prepare(hass, audio_setup, monkeypatch, reload=reload)
    await action(hass, entity, kind)
    assert read.await_count == 1 and read.await_args.args[0] == 7
    assert sent.await_count == 1
    assert entity._audio_metadata.get(7).native_mode == "play"
    assert entity._audio_metadata.get(8) is None
    audio_setup.apis[-1].send_websocket_command.assert_not_awaited()
    # A later action uses real passive feedback, not another bootstrap/poll.
    await action(hass, entity, kind)
    assert read.await_count == 1 and sent.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["source", "browse"])
@pytest.mark.parametrize("interruption", ["stop", "native_change", "stream_reset", "unload"])
async def test_cold_status_wait_does_not_overwrite_newer_action_or_stream(hass, audio_setup, monkeypatch, kind, interruption):
    entered, release = asyncio.Event(), asyncio.Event()

    async def waiting(*args, **kwargs):
        entered.set()
        await release.wait()
        return snapshot(STOPPED)

    read = AsyncMock(side_effect=waiting)
    monkeypatch.setattr(wire.AudioServerCommands, "async_player_status", read, raising=False)
    entry, entity, sent = await prepare(hass, audio_setup, monkeypatch)
    task = asyncio.create_task(action(hass, entity, kind))
    try:
        async with asyncio.timeout(1):
            await entered.wait()
        if interruption == "stop":
            await entity.async_media_stop()
        elif interruption == "native_change":
            observed = asyncio.Event()
            remove = entity._audio_metadata.async_add_listener(7, observed.set)
            await audio_setup.queues[-1].put(json.dumps({"audio_event": [{**STOPPED, "audiopath": "spotify:track:newer", "eventype": 0}]}))
            async with asyncio.timeout(1):
                await observed.wait()
            remove()
        elif interruption == "stream_reset":
            observed = asyncio.Event()
            remove = entity._audio_metadata.async_add_listener(7, observed.set)
            await audio_setup.queues[-1].put(None)
            async with asyncio.timeout(1):
                await observed.wait()
            remove()
        else:
            assert await hass.config_entries.async_unload(entry.entry_id)
        release.set()
        with pytest.raises((HomeAssistantError, asyncio.CancelledError)):
            await task
        sent.assert_not_awaited()
        if interruption == "native_change":
            assert entity._audio_metadata.get(7).audio_path == "spotify:track:newer"
        else:
            assert entity._audio_metadata.get(7) is None
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("row", [
    {"playerid": 7, "mode": "stop"},
    {**STOPPED, "eventype": "unknown"},
    {**STOPPED, "eventype": 3, "mode": "play"},
    {"playerid": 7, "mode": "play", "audiopath": "airplay", "type": 7},
])
async def test_status_bootstrap_never_infers_event_idle_from_unknown_or_interruption(hass, audio_setup, monkeypatch, row):
    read = AsyncMock(return_value=snapshot(row))
    monkeypatch.setattr(wire.AudioServerCommands, "async_player_status", read, raising=False)
    _, entity, sent = await prepare(hass, audio_setup, monkeypatch)
    with pytest.raises(HomeAssistantError):
        await action(hass, entity, "browse")
    sent.assert_not_awaited()
    assert read.await_count == 1
    assert not entity._audio_metadata.get(7).event_idle


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    [], None, {}, [{**STOPPED, "playerid": 8}], [STOPPED, STOPPED],
    [STOPPED, {**STOPPED, "playerid": 8}], [{**STOPPED, "playerid": True}],
])
async def test_status_wire_rejects_missing_wrong_or_ambiguous_exact_player(monkeypatch, payload):
    owner = wire.AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "token"))
    request = AsyncMock(return_value=payload)
    monkeypatch.setattr(owner, "_async_request", request)
    with pytest.raises(wire.AudioCommandError):
        await owner.async_player_status(7, is_current=lambda: True)
    request.assert_awaited_once()
    assert request.await_args.args == ("audio/7/status", "status_result")


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [STOPPED, [STOPPED]])
async def test_status_wire_projects_only_source_established_read_into_existing_classifier(monkeypatch, payload):
    owner = wire.AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "token"))
    request = AsyncMock(return_value=payload)
    monkeypatch.setattr(owner, "_async_request", request)
    guard = lambda: True
    result = await owner.async_player_status(7, is_current=guard)
    assert result.player_id == 7 and result.event_idle and result.event_active is False
    request.assert_awaited_once_with("audio/7/status", "status_result", is_current=guard)
    assert not owner.source_fences and not owner.announcement_fences
