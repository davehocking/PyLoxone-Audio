"""Delayed reconciliation must settle through the owning HA receiver under noise.

All rows and I/O are synthetic. Bare/default rows do not establish freshness;
meaningful sparse values and account/context changes still supersede a read.
"""

import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock

import pytest

from custom_components.loxone.const import EVENT
from custom_components.loxone.pyloxone_api import audioserver as wire
from pyloxone_audio import metadata as metadata_module
from test_audioserver_ha import audio_setup as audio_setup, zone_entity_id
from test_metadata_reconciliation_ha import frame, row


@pytest.mark.asyncio
@pytest.mark.parametrize("noise", [
    {"playerid": 7},
    {"playerid": 7, "title": False, "pbr": "bad", "plshuffle": "bad"},
])
async def test_delayed_recovery_publishes_while_unusable_frames_continue(
    hass, audio_setup, monkeypatch, noise
):
    monkeypatch.setattr(metadata_module, "_ACTIVE_SAMPLE_SECONDS", 0.04)
    entered, release, published = asyncio.Event(), asyncio.Event(), asyncio.Event()
    count = [0]

    async def status(player, *, is_current):
        assert player == 7 and is_current()
        entered.set()
        await release.wait()
        return wire.parse_audio_events({"audio_event": [row(
            title="Recovered under continuing noise", audiopath="spotify:track:recovered", time=11
        )]})[0]

    read, execute, seek = AsyncMock(side_effect=status), AsyncMock(), AsyncMock()
    monkeypatch.setattr(wire.AudioServerCommands, "async_player_status", read)
    monkeypatch.setattr(wire.AudioServerCommands, "async_execute", execute)
    monkeypatch.setattr(wire.AudioServerCommands, "async_seek", seek)
    entry = await audio_setup.setup(playback=True)
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    coordinator = entity._audio_metadata
    accepted = []

    def observed():
        current = coordinator.get(7)
        if current is not None and current.title == "Recovered under continuing noise":
            accepted.append((current, count[0]))
            published.set()

    remove = coordinator.async_add_listener(7, observed)
    await frame(hass, audio_setup, row())
    hass.bus.async_fire(EVENT, {"play-7": 2})
    await hass.async_block_till_done()
    producer = None
    try:
        await asyncio.wait_for(entered.wait(), 0.5)

        async def continuous_noise():
            while True:
                await frame(hass, audio_setup, noise)
                count[0] += 1
                await asyncio.sleep(0.001)

        producer = asyncio.create_task(continuous_noise())
        async with asyncio.timeout(0.5):
            while count[0] < 4:
                await asyncio.sleep(0.001)
        assert not published.is_set()
        release.set()
        with suppress(TimeoutError):
            await asyncio.wait_for(published.wait(), 0.25)
        assert published.is_set(), "Unusable in-flight rows must not veto useful recovery publication"
        # Keep the producer alive past the actual subscriber notification, not
        # merely until the mock reader starts or returns.
        after_publication = count[0]
        async with asyncio.timeout(0.5):
            while count[0] < after_publication + 4:
                await asyncio.sleep(0.001)
        assert accepted[0][1] >= 4 and not producer.done()
        assert accepted[0][0].position == 11
        assert entity.state == "playing" and read.await_count == 1
        assert not coordinator._retry_delay
        execute.assert_not_awaited()
        seek.assert_not_awaited()
        audio_setup.apis[0].send_websocket_command.assert_not_awaited()
    finally:
        release.set()
        if producer is not None:
            producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)
        remove()
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert not coordinator._recoveries and coordinator._timer is None
        assert coordinator._task is None
        assert len(audio_setup.opened) == len(audio_setup.closed)


@pytest.mark.asyncio
@pytest.mark.parametrize("newer", [
    row(title="New passive content", audiopath="spotify:track:newer"),
    row(title="Same content newer timing", time=42),
    {"playerid": 7, "artist": "Sparse artist"},
    {"playerid": 7, "album": "Sparse album"},
    {"playerid": 7, "pbr": 0},
    {"playerid": 7, "plshuffle": False},
    {"playerid": 7, "plrepeat": 0},
    {"playerid": 7, "sourceName": "Changed synthetic account"},
    {"playerid": 7, "parent": {"id": "Changed synthetic context"}},
    row(eventype=3, title="New interruption"),
], ids=["different-track", "same-track", "artist", "album", "zero-mask",
        "false-shuffle", "zero-repeat", "account", "context", "interruption"])
async def test_useful_inflight_feedback_stays_a_fence_even_after_empty_frame(
    hass, audio_setup, monkeypatch, newer
):
    monkeypatch.setattr(metadata_module, "_ACTIVE_SAMPLE_SECONDS", 0.03)
    entered, release, returned = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def status(player, *, is_current):
        assert player == 7 and is_current()
        entered.set()
        await release.wait()
        returned.set()
        return wire.parse_audio_events({"audio_event": [row(
            title="Obsolete delayed status", audiopath="spotify:track:obsolete"
        )]})[0]

    read = AsyncMock(side_effect=status)
    monkeypatch.setattr(wire.AudioServerCommands, "async_player_status", read)
    entry = await audio_setup.setup(playback=True)
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    coordinator = entity._audio_metadata
    seen = []
    remove = coordinator.async_add_listener(7, lambda: seen.append(
        coordinator._client.get(7).title if coordinator._client.get(7) else None
    ))
    await frame(hass, audio_setup, row())
    hass.bus.async_fire(EVENT, {"play-7": 2})
    await hass.async_block_till_done()
    try:
        await asyncio.wait_for(entered.wait(), 0.5)
        await frame(hass, audio_setup, newer)
        await frame(hass, audio_setup, {"playerid": 7})
        release.set()
        await asyncio.wait_for(returned.wait(), 0.5)
        await hass.async_block_till_done()
        assert "Obsolete delayed status" not in seen, (
            "Even sparse/zero/False or account/context-only newer observations veto an older read",
            newer, seen,
        )
        assert read.await_count == 1
        audio_setup.apis[0].send_websocket_command.assert_not_awaited()
    finally:
        release.set()
        remove()
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert not coordinator._recoveries and coordinator._timer is None
