"""Contributor #523/6285915820 regressions, synthetic replay (not a device capture)."""

# ruff: noqa: S101, INP001, ANN001, ANN003, ANN202, PLC0415, D103, PLR2004, ARG001, F811, F401, SLF001

import asyncio
import json
from unittest.mock import AsyncMock
import pytest
from test_audioserver_ha import audio_setup, zone_entity_id
from custom_components.loxone.pyloxone_api import audioserver


async def player(hass, audio_setup):
    await audio_setup.setup(playback=True)
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    row = {
        "playerid": 7,
        "mode": "play",
        "audiopath": "spotify:track:synthetic",
        "time": 63.25,
        "duration": 180,
        "pbr": 32,
    }
    await audio_setup.queues[0].put(json.dumps({"audio_event": [row]}))
    await hass.async_block_till_done()
    return entity, row


@pytest.mark.asyncio
async def test_seek_echo_without_matching_event_does_not_move_clock(hass, audio_setup, monkeypatch):
    entity, row = await player(hass, audio_setup)
    called = asyncio.Event()

    async def echo(self, p, seconds, **kwargs):
        if kwargs.get("on_send"):
            kwargs["on_send"]()
        called.set()
        return seconds

    monkeypatch.setattr(audioserver.AudioServerCommands, "async_seek", echo)
    task = asyncio.create_task(entity.async_media_seek(30))
    try:
        await called.wait()
        for _ in range(5):
            await asyncio.sleep(0)
        assert not task.done(), "position_result is an echo, not observed seek success"
        assert entity.media_position == 63.25
        await audio_setup.queues[0].put(json.dumps({"audio_event": [{**row, "time": 30}]}))
        await asyncio.wait_for(task, 1)
        assert entity.media_position == 30
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("requested", [180, 99999])
async def test_seek_clamps_before_end_to_avoid_native_track_skip(hass, audio_setup, monkeypatch, requested):
    entity, row = await player(hass, audio_setup)
    sent = []

    async def echo(self, p, seconds, **kwargs):
        if kwargs.get("on_send"):
            kwargs["on_send"]()
        sent.append(seconds)
        asyncio.get_running_loop().call_later(
            0.01, audio_setup.queues[0].put_nowait, json.dumps({"audio_event": [{**row, "time": seconds}]})
        )
        return seconds

    monkeypatch.setattr(audioserver.AudioServerCommands, "async_seek", echo)
    await entity.async_media_seek(requested)
    assert sent == [179]
    assert entity.media_position == 179


@pytest.mark.asyncio
async def test_paused_seek_accepts_matching_event_before_reply_without_extra_play(hass, audio_setup, monkeypatch):
    entity, row = await player(hass, audio_setup)
    await audio_setup.queues[0].put(json.dumps({"audio_event": [{**row, "mode": "stop"}]}))
    await hass.async_block_till_done()
    play = AsyncMock()
    monkeypatch.setattr(audioserver.AudioServerCommands, "async_execute", play)

    async def echo(self, p, seconds, **kwargs):
        if kwargs.get("on_send"):
            kwargs["on_send"]()
        await audio_setup.queues[0].put(json.dumps({"audio_event": [{**row, "time": seconds}]}))
        await hass.async_block_till_done()
        return seconds

    monkeypatch.setattr(audioserver.AudioServerCommands, "async_seek", echo)
    await asyncio.wait_for(entity.async_media_seek(0), 1)
    assert entity.media_position == 0
    play.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_source_event_before_serviceplay_reply_is_valid(monkeypatch):
    from types import SimpleNamespace
    from custom_components.loxone import audio_sources as sources
    from test_audio_sources import Metadata, favourites

    metadata = Metadata()

    async def play(player, favourite, *, is_current, on_send):
        assert is_current()
        on_send()
        metadata.set({"audiopath": "tunein:station:synthetic", "mode": "play"})
        await asyncio.sleep(0)

    commands = SimpleNamespace(
        async_room_favourites=AsyncMock(return_value=favourites()),
        async_play_room_favourite=play,
        announcement_fences={},
        source_fences={},
    )
    await asyncio.wait_for(
        sources.async_select_favourite(
            commands, metadata, sources.parse_room_favourites(favourites(), 7)[0], is_available=lambda: True
        ),
        0.1,
    )
    assert not commands.source_fences


@pytest.mark.asyncio
async def test_seek_keeps_observed_target_evidence_then_newer_progress_before_reply(hass, audio_setup, monkeypatch):
    entity, row = await player(hass, audio_setup)

    async def echo(self, player_id, seconds, **kwargs):
        kwargs["on_send"]()
        for offset in (seconds, seconds + 3):
            await audio_setup.queues[0].put(json.dumps({"audio_event": [{**row, "time": offset}]}))
            await hass.async_block_till_done()
        return seconds

    monkeypatch.setattr(audioserver.AudioServerCommands, "async_seek", echo)
    await asyncio.wait_for(entity.async_media_seek(30), 0.5)
    assert entity.media_position == 33


@pytest.mark.asyncio
@pytest.mark.parametrize("requested", [0, 1, 30])
async def test_seek_does_not_commit_late_zero_placeholder_after_progress_before_reply(
    hass, audio_setup, monkeypatch, requested,
):
    entity, row = await player(hass, audio_setup)

    async def echo(self, player_id, seconds, **kwargs):
        kwargs["on_send"]()
        for offset in (seconds, seconds + 3, 0):
            await audio_setup.queues[0].put(json.dumps({"audio_event": [{**row, "time": offset}]}))
            await hass.async_block_till_done()
        return seconds

    monkeypatch.setattr(audioserver.AudioServerCommands, "async_seek", echo)
    await asyncio.wait_for(entity.async_media_seek(requested), 0.5)
    assert entity.media_position == requested + 3


@pytest.mark.asyncio
@pytest.mark.parametrize("requested", [0, 1, 30])
async def test_seek_retains_progress_after_reply_before_waiter_resumes(hass, audio_setup, monkeypatch, requested):
    entity, row = await player(hass, audio_setup)

    def feedback():
        coordinator = entity._audio_metadata
        for offset in (requested, requested + 3, 0):
            snapshot = audioserver.parse_audio_events({"audio_event": [{**row, "time": offset}]})[0]
            coordinator._client._receiver._metadata[7] = snapshot
            coordinator._on_update((snapshot,))

    async def echo(self, player_id, seconds, **kwargs):
        kwargs["on_send"]()
        asyncio.get_running_loop().call_later(0.01, feedback)
        return seconds

    monkeypatch.setattr(audioserver.AudioServerCommands, "async_seek", echo)
    await asyncio.wait_for(entity.async_media_seek(requested), 0.5)
    assert entity.media_position == requested + 3
    assert not entity._audio_commands.source_fences


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["play", "stop"])
async def test_observed_seek_does_not_hide_later_native_positive_offset_or_stop(hass, audio_setup, monkeypatch, mode):
    entity, row = await player(hass, audio_setup)

    async def echo(self, player_id, seconds, **kwargs):
        kwargs["on_send"]()
        await audio_setup.queues[0].put(json.dumps({"audio_event": [{**row, "time": seconds}]}))
        await hass.async_block_till_done()
        return seconds

    monkeypatch.setattr(audioserver.AudioServerCommands, "async_seek", echo)
    await entity.async_media_seek(30)
    await audio_setup.queues[0].put(json.dumps({"audio_event": [{**row, "mode": mode}]}))
    await hass.async_block_till_done()
    assert entity.media_position == row["time"]
