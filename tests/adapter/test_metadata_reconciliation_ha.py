"""0.1.2 shared freshness/recovery through the real owning HA lifecycle."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from homeassistant.components.media_player import MediaPlayerEntityFeature
from custom_components.loxone.const import EVENT
from custom_components.loxone.pyloxone_api import audioserver as wire
from pyloxone_audio import metadata as metadata_module
from test_audioserver_ha import audio_setup as audio_setup, zone_entity_id
from test_audioserver_playback import SyntheticAudioSocket, rsa_key as rsa_key


def row(player=7, **extra):
    return {
        "playerid": player,
        "title": "Prior synthetic track",
        "artist": "Synthetic",
        "audiopath": "spotify:track:prior",
        "sourceName": "Synthetic account",
        "mode": "play",
        "time": 20,
        "duration": 200,
        "pbr": 32,
        **extra,
    }


async def frame(hass, setup, data, index=0):
    setup.queues[index].put_nowait(json.dumps({"audio_event": [data]}))
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_active_silent_stream_recovers_current_track_without_state_transition(
    hass, audio_setup, monkeypatch
):
    monkeypatch.setattr(metadata_module, "_ACTIVE_SAMPLE_SECONDS", 0.04)
    seen = asyncio.Event()

    async def status(player, *, is_current):
        assert player == 7 and is_current()
        seen.set()
        return wire.parse_audio_events(
            {
                "audio_event": [
                    row(
                        title="Current synthetic track",
                        audiopath="spotify:track:current",
                        time=11,
                    )
                ]
            }
        )[0]

    read = AsyncMock(side_effect=status)
    execute, seek = AsyncMock(), AsyncMock()
    monkeypatch.setattr(wire.AudioServerCommands, "async_player_status", read)
    monkeypatch.setattr(wire.AudioServerCommands, "async_execute", execute)
    monkeypatch.setattr(wire.AudioServerCommands, "async_seek", seek)
    entry = await audio_setup.setup(playback=True)
    entity_id = zone_entity_id(hass, 7)
    await frame(hass, audio_setup, row())
    hass.bus.async_fire(EVENT, {"play-7": 2})
    await hass.async_block_till_done()
    assert (
        hass.states.get(entity_id).attributes["media_title"] == "Prior synthetic track"
    )
    try:
        await asyncio.wait_for(seen.wait(), timeout=0.4)
    except TimeoutError:
        pass
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state.attributes.get("media_title") == "Current synthetic track", (
        "Active silent streams must recover current content without another playState transition"
    )
    assert state.state == "playing"
    assert state.attributes["media_position"] == 11
    assert read.await_count == 1
    receiver = hass.data["loxone"][entry.entry_id].audio_metadata._client._receiver
    assert receiver._listening
    execute.assert_not_awaited()
    seek.assert_not_awaited()
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_known_track_boundary_expires_before_general_freshness_timeout(
    hass, audio_setup, monkeypatch
):
    read = AsyncMock(side_effect=TimeoutError("synthetic unavailable"))
    monkeypatch.setattr(wire.AudioServerCommands, "async_player_status", read)
    await audio_setup.setup(playback=True)
    entity_id = zone_entity_id(hass, 7)
    await frame(hass, audio_setup, row(time=0.04, duration=0.08))
    hass.bus.async_fire(EVENT, {"play-7": 2})
    await hass.async_block_till_done()
    await asyncio.sleep(0.09)
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state.state == "playing"
    assert state.attributes.get("media_title") is None, (
        "Do not extrapolate an old track across its trustworthy end"
    )
    assert state.attributes.get("media_position") is None
    assert not state.attributes["supported_features"] & MediaPlayerEntityFeature.SEEK
    assert read.await_count == 1
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("playback", [False, True], ids=["passive-only", "opted-in"])
async def test_unavailable_active_status_stays_unknown_and_cannot_seek_or_resurrect_on_stop(
    hass, audio_setup, monkeypatch, playback
):
    monkeypatch.setattr(metadata_module, "_ACTIVE_SAMPLE_SECONDS", 0.035)
    read = AsyncMock(side_effect=wire.AudioCommandError("synthetic denied"))
    seek = AsyncMock()
    monkeypatch.setattr(wire.AudioServerCommands, "async_player_status", read)
    monkeypatch.setattr(wire.AudioServerCommands, "async_seek", seek)
    await audio_setup.setup(playback=playback)
    entity_id = zone_entity_id(hass, 7)
    await frame(hass, audio_setup, row())
    hass.bus.async_fire(EVENT, {"play-7": 2, "volume-7": 37})
    await hass.async_block_till_done()
    await asyncio.sleep(0.08)
    await hass.async_block_till_done()
    entity = hass.data["media_player"].get_entity(entity_id)
    state = hass.states.get(entity_id)
    assert state.state == "playing" and state.attributes["volume_level"] == 0.37
    assert state.attributes.get("media_title") is None
    assert entity._audio_metadata.get(7) is None
    assert not entity.supported_features & MediaPlayerEntityFeature.SEEK
    from homeassistant.exceptions import HomeAssistantError

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "media_player",
            "media_seek",
            {"entity_id": entity_id, "seek_position": 5},
            blocking=True,
        )
    hass.bus.async_fire(EVENT, {"play-7": 0})
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).attributes.get("media_title") is None
    assert entity._audio_metadata.get(7) is None
    assert read.await_count == (1 if playback else 0)
    seek.assert_not_awaited()
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["pause", "stop"])
async def test_long_idle_or_pause_does_not_poll_but_active_wake_recovers(
    hass, audio_setup, monkeypatch, mode
):
    from datetime import timedelta
    from homeassistant.util import dt as dt_util

    clock = [dt_util.utcnow()]
    monkeypatch.setattr(metadata_module, "utcnow", lambda: clock[0])
    current = row(title="Recovered after sleep", audiopath="spotify:track:new", time=14)
    read = AsyncMock(
        side_effect=lambda *a, **k: wire.parse_audio_events({"audio_event": [current]})[
            0
        ]
    )
    monkeypatch.setattr(wire.AudioServerCommands, "async_player_status", read)
    await audio_setup.setup(playback=True)
    entity_id = zone_entity_id(hass, 7)
    hass.bus.async_fire(EVENT, {"play-7": 0})
    await frame(hass, audio_setup, row(mode=mode))
    clock[0] += timedelta(hours=7)
    hass.bus.async_fire(EVENT, {"volume-7": 32})
    await hass.async_block_till_done()
    assert (
        hass.states.get(entity_id).attributes.get("media_title")
        == "Prior synthetic track"
    )
    read.assert_not_awaited()
    # Returned row's observed time must be current too (synthetic wall-clock jump).
    from dataclasses import replace

    read.side_effect = lambda *a, **k: replace(
        wire.parse_audio_events({"audio_event": [current]})[0],
        received_at=clock[0],
        position_updated_at=clock[0],
    )
    hass.bus.async_fire(EVENT, {"play-7": 2})
    await hass.async_block_till_done()
    assert (
        hass.states.get(entity_id).attributes["media_title"] == "Recovered after sleep"
    )
    assert hass.states.get(entity_id).attributes["media_position"] == 14
    assert read.await_count == 1
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "interruption",
    ["passive-newer", "same-content-newer", "stop", "disconnect", "unload"],
)
async def test_delayed_recovery_cannot_overwrite_intervening_feedback_or_lifecycle(
    hass, audio_setup, monkeypatch, interruption
):
    monkeypatch.setattr(metadata_module, "_ACTIVE_SAMPLE_SECONDS", 0.035)
    entered, release = asyncio.Event(), asyncio.Event()
    guards = []

    async def waiting(player, *, is_current):
        guards.append(is_current)
        entered.set()
        await release.wait()
        return wire.parse_audio_events(
            {
                "audio_event": [
                    row(
                        title="Late status must not win", audiopath="spotify:track:late"
                    )
                ]
            }
        )[0]

    read = AsyncMock(side_effect=waiting)
    monkeypatch.setattr(wire.AudioServerCommands, "async_player_status", read)
    entry = await audio_setup.setup(playback=True)
    entity_id = zone_entity_id(hass, 7)
    entity = hass.data["media_player"].get_entity(entity_id)
    metadata = entity._audio_metadata
    await frame(hass, audio_setup, row())
    hass.bus.async_fire(EVENT, {"play-7": 2})
    await hass.async_block_till_done()
    try:
        await asyncio.wait_for(entered.wait(), 0.5)
        if interruption in ("passive-newer", "same-content-newer"):
            await frame(
                hass,
                audio_setup,
                row(
                    title="New passive sample",
                    audiopath=(
                        "spotify:track:prior"
                        if interruption == "same-content-newer"
                        else "spotify:track:external"
                    ),
                ),
            )
        elif interruption == "stop":
            await hass.services.async_call(
                "media_player", "media_stop", {"entity_id": entity_id}, blocking=True
            )
        elif interruption == "disconnect":
            await audio_setup.queues[0].put(None)
            await hass.async_block_till_done()
        else:
            assert await hass.config_entries.async_unload(entry.entry_id)
        release.set()
        await hass.async_block_till_done()
        assert entity.media_title != "Late status must not win"
        if interruption in ("passive-newer", "same-content-newer"):
            assert entity.media_title == "New passive sample"
        if interruption == "unload":
            assert not metadata._recoveries and metadata._timer is None
            assert metadata._task is None
        assert read.await_count == 1
    finally:
        release.set()


@pytest.mark.asyncio
@pytest.mark.parametrize("change_at", ["authentication", "status-reply"])
async def test_actual_ha_recovery_rejects_changed_auth_context(
    hass, audio_setup, monkeypatch, rsa_key, change_at
):
    monkeypatch.setattr(metadata_module, "_ACTIVE_SAMPLE_SECONDS", 0.025)
    await audio_setup.setup(playback=True)
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    credentials = [("synthetic-user", "synthetic-active-token")]
    entity._audio_commands._credentials = lambda: credentials[0]
    observed = []
    entity.async_on_remove(
        entity._audio_metadata.async_add_listener(
            7,
            lambda: observed.append(
                entity._audio_metadata._client.get(7).title
                if entity._audio_metadata._client.get(7)
                else None
            ),
        )
    )
    sockets = []

    class Socket(SyntheticAudioSocket):
        async def send(self, message):
            if message == "audio/7/status":
                self.sent.append(message)
                self.queue.put_nowait(
                    json.dumps(
                        {
                            "status_result": [
                                row(title="Must reject changed credential result")
                            ]
                        }
                    )
                )
                if change_at == "status-reply":
                    credentials[0] = ("synthetic-other-user", "synthetic-other-token")
            else:
                await super().send(message)
                if (
                    message.startswith("secure/authenticate/")
                    and change_at == "authentication"
                ):
                    credentials[0] = ("synthetic-other-user", "synthetic-other-token")

    def connect(*a, **k):
        socket = Socket(rsa_key)
        sockets.append(socket)
        return socket

    monkeypatch.setattr(wire, "connect", connect)
    await frame(hass, audio_setup, row())
    hass.bus.async_fire(EVENT, {"play-7": 2})
    await hass.async_block_till_done()
    await asyncio.sleep(0.1)
    await hass.async_block_till_done()
    assert entity.media_title is None
    assert "Must reject changed credential result" not in observed
    assert len(sockets) == 1 and sockets[0].closed
    assert [m for m in sockets[0].sent if m.startswith("audio/7/")] == (
        [] if change_at == "authentication" else ["audio/7/status"]
    )
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_end_of_track_status_cannot_starve_another_active_room(
    hass, audio_setup, monkeypatch
):
    monkeypatch.setattr(metadata_module, "_ACTIVE_SAMPLE_SECONDS", 0.03)
    monkeypatch.setattr(metadata_module, "_READ_SPACING_SECONDS", 0.01)
    requested = []

    async def read(self, player, **kwargs):
        requested.append(player)
        return wire.parse_audio_events(
            {
                "audio_event": [
                    row(
                        player,
                        title=f"Current room {player}",
                        time=(200 if player == 7 else 15),
                    )
                ]
            }
        )[0]

    monkeypatch.setattr(wire.AudioServerCommands, "async_player_status", read)
    await audio_setup.setup(playback=True)
    await frame(hass, audio_setup, row(7))
    await frame(hass, audio_setup, row(8))
    hass.bus.async_fire(EVENT, {"play-7": 2, "play-8": 2})
    await hass.async_block_till_done()
    await asyncio.sleep(0.12)
    await hass.async_block_till_done()
    coordinator = (
        hass.data["media_player"].get_entity(zone_entity_id(hass, 7))._audio_metadata
    )
    assert 8 in requested, (
        requested,
        coordinator._playing,
        coordinator._retry_at,
        list(coordinator._recoveries),
        coordinator._timer,
        asyncio.get_running_loop().time(),
    )
    assert requested.count(7) <= 4 and requested.count(8) <= 4
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_read_failures_have_capped_backoff_and_unload_cancels_all_work(
    hass, audio_setup, monkeypatch
):
    monkeypatch.setattr(metadata_module, "_ACTIVE_SAMPLE_SECONDS", 0.025)
    monkeypatch.setattr(metadata_module, "_READ_SPACING_SECONDS", 0.005)
    monkeypatch.setattr(metadata_module, "_MAX_RETRY_SECONDS", 0.07)
    monkeypatch.setattr(metadata_module, "_RECOVERY_TIMEOUT_SECONDS", 0.015)
    times, active = [], []
    fourth = asyncio.Event()

    async def read(player, **kwargs):
        times.append(asyncio.get_running_loop().time())
        active.append(1)
        assert len(active) == 1
        if len(times) == 4:
            fourth.set()
        try:
            await asyncio.Future()
        finally:
            active.pop()

    monkeypatch.setattr(
        wire.AudioServerCommands, "async_player_status", AsyncMock(side_effect=read)
    )
    entry = await audio_setup.setup(playback=True)
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    coordinator = entity._audio_metadata
    await frame(hass, audio_setup, row())
    hass.bus.async_fire(EVENT, {"play-7": 2})
    await hass.async_block_till_done()
    await asyncio.wait_for(fourth.wait(), 1.0)
    assert all(
        b - a >= minimum for a, b, minimum in zip(times, times[1:], (0.025, 0.05, 0.07))
    )
    assert coordinator._retry_delay[7] == 0.07
    assert entity.media_title is None
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not active and not coordinator._recoveries and coordinator._timer is None
    count = len(times)
    await asyncio.sleep(0.09)
    assert len(times) == count == 4
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        row(8, title="Wrong player"),
        row(mode="unknown", title="Unknown mode"),
        row(audiopath="", title="Missing content"),
    ],
)
async def test_unusable_reconciliation_does_not_replace_cache_or_bookmark(
    hass, audio_setup, monkeypatch, bad
):
    monkeypatch.setattr(metadata_module, "_ACTIVE_SAMPLE_SECONDS", 0.025)
    read = AsyncMock(return_value=wire.parse_audio_events({"audio_event": [bad]})[0])
    monkeypatch.setattr(wire.AudioServerCommands, "async_player_status", read)
    from test_audio_catalogue import catalogue_commands

    for name, value in vars(catalogue_commands()).items():
        monkeypatch.setattr(wire.AudioServerCommands, name, value)
    await audio_setup.setup(playback=True)
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    await frame(hass, audio_setup, row(sourceName="Synthetic owner"))
    saved = dict(entity._radio_catalogue.source_sessions)
    assert saved, "Negative control must protect a real populated last-good record"
    hass.bus.async_fire(EVENT, {"play-7": 2})
    await hass.async_block_till_done()
    # Invalid envelopes/other-player traffic do not make player 7 fresh.
    for message in (
        "malformed",
        '{"audio_event":{}}',
        json.dumps({"audio_event": [row(8)]}),
    ):
        audio_setup.queues[0].put_nowait(message)
    await asyncio.sleep(0.07)
    await hass.async_block_till_done()
    assert read.await_count == 1
    assert entity.media_title is None and entity._audio_metadata.get(7) is None
    assert entity._audio_metadata._client.get(7).title == "Prior synthetic track"
    assert entity._radio_catalogue.source_sessions == saved
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_same_numeric_player_on_two_entries_reconciles_only_its_own_receiver(
    hass, audio_setup, monkeypatch
):
    import copy
    import test_audioserver_ha as fixtures
    from homeassistant.helpers import entity_registry as er

    monkeypatch.setattr(metadata_module, "_ACTIVE_SAMPLE_SECONDS", 0.03)
    await audio_setup.setup("audio-one.example.invalid", playback=True)
    first = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    structure = copy.deepcopy(fixtures.STRUCTURE)
    structure["controls"] = {
        key.replace("synthetic-zone-", "synthetic-second-"): {
            **value,
            "uuidAction": key.replace("synthetic-zone-", "synthetic-second-"),
        }
        for key, value in structure["controls"].items()
    }
    monkeypatch.setattr(fixtures, "STRUCTURE", structure)
    await audio_setup.setup("audio-two.example.invalid", playback=True)
    second_id = er.async_get(hass).async_get_entity_id(
        "media_player", "loxone", "synthetic-second-7"
    )
    second = hass.data["media_player"].get_entity(second_id)
    reads, complete = [], asyncio.Event()

    async def read(self, player, **kwargs):
        reads.append((self._uri, player))
        if len(reads) == 2:
            complete.set()
        return wire.parse_audio_events(
            {"audio_event": [row(player, title=self._uri, time=5)]}
        )[0]

    monkeypatch.setattr(wire.AudioServerCommands, "async_player_status", read)
    await frame(hass, audio_setup, row(title="First old"), 0)
    await frame(hass, audio_setup, row(title="Second old"), 1)
    hass.bus.async_fire(EVENT, {"play-7": 2})
    await hass.async_block_till_done()
    await asyncio.wait_for(complete.wait(), 0.5)
    await hass.async_block_till_done()
    assert first._audio_metadata is not second._audio_metadata
    assert first.media_title == "ws://audio-one.example.invalid:7091/"
    assert second.media_title == "ws://audio-two.example.invalid:7091/"
    assert sorted(reads) == [
        ("ws://audio-one.example.invalid:7091/", 7),
        ("ws://audio-two.example.invalid:7091/", 7),
    ]
    for api in audio_setup.apis:
        api.send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_source_selection_requalifies_expired_existing_snapshot(
    hass, audio_setup, monkeypatch
):
    from datetime import datetime, timedelta
    from test_audio_catalogue import catalogue_commands

    for name, value in vars(catalogue_commands()).items():
        monkeypatch.setattr(wire.AudioServerCommands, name, value)
    await audio_setup.setup(playback=True)
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    hass.bus.async_fire(EVENT, {"play-7": 2})
    await hass.async_block_till_done()

    class OldClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) - timedelta(hours=7)

    with monkeypatch.context() as old:
        old.setattr(wire, "datetime", OldClock)
        await frame(hass, audio_setup, row())
    assert entity._audio_metadata.get(7) is None
    read = AsyncMock(
        return_value=wire.parse_audio_events(
            {"audio_event": [row(title="Fresh current before selection")]}
        )[0]
    )
    monkeypatch.setattr(wire.AudioServerCommands, "async_player_status", read)

    async def play(player, service, account, item, *, is_current, on_send):
        assert is_current()
        on_send()
        audio_setup.queues[0].put_nowait(
            json.dumps(
                {
                    "audio_event": [
                        row(audiopath="linein:ABCDEF123456#1000001", title="Line input")
                    ]
                }
            )
        )

    write = AsyncMock(side_effect=play)
    monkeypatch.setattr(wire.AudioServerCommands, "async_play_catalogue", write)
    await hass.services.async_call(
        "media_player",
        "select_source",
        {"entity_id": entity.entity_id, "source": "Line-In"},
        blocking=True,
    )
    assert read.await_count == 1, (
        "Existing-but-expired is not the same as usable initial state"
    )
    assert write.await_count == 1 and entity.source == "Line-In"
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconnected_silent_receiver_recovers_while_miniserver_remains_playing(
    hass, audio_setup, monkeypatch
):
    monkeypatch.setattr(metadata_module, "_ACTIVE_SAMPLE_SECONDS", 0.04)
    monkeypatch.setattr(metadata_module, "_READ_SPACING_SECONDS", 0.01)
    recovered = asyncio.Event()

    async def read(player, **kwargs):
        recovered.set()
        return wire.parse_audio_events(
            {
                "audio_event": [
                    row(
                        title="Current after reconnect",
                        audiopath="spotify:track:reconnected",
                        time=9,
                    )
                ]
            }
        )[0]

    monkeypatch.setattr(
        wire.AudioServerCommands, "async_player_status", AsyncMock(side_effect=read)
    )
    entry = await audio_setup.setup(playback=True)
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    await frame(hass, audio_setup, row())
    hass.bus.async_fire(EVENT, {"play-7": 2})
    await hass.async_block_till_done()
    coordinator = entity._audio_metadata
    coordinator._client._retry_delay = 0.01
    audio_setup.queues[0].put_nowait(None)
    await asyncio.sleep(0.02)
    await hass.async_block_till_done()
    assert len(audio_setup.queues) == 2 and entity.media_title is None
    await asyncio.wait_for(recovered.wait(), 0.5)
    await hass.async_block_till_done()
    assert entity.state == "playing" and entity.media_title == "Current after reconnect"
    assert coordinator._client._receiver._listening
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert len(audio_setup.opened) == len(audio_setup.closed) == 2
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_waiting_on_native_lock_cannot_adopt_a_newer_stop_generation(
    hass, audio_setup, monkeypatch, rsa_key
):
    monkeypatch.setattr(metadata_module, "_ACTIVE_SAMPLE_SECONDS", 0.025)
    await audio_setup.setup(playback=True)
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    commands = entity._audio_commands
    commands._credentials = lambda: ("synthetic-user", "synthetic-active-token")
    socket = SyntheticAudioSocket(rsa_key)
    monkeypatch.setattr(wire, "connect", lambda *a, **k: socket)
    await commands._lock.acquire()
    try:
        await frame(hass, audio_setup, row())
        hass.bus.async_fire(EVENT, {"play-7": 2})
        await hass.async_block_till_done()
        await asyncio.sleep(0.05)
        assert entity._audio_metadata._recoveries
        await hass.services.async_call(
            "media_player", "media_stop", {"entity_id": entity.entity_id}, blocking=True
        )
    finally:
        commands._lock.release()
    await asyncio.sleep(0.02)
    await hass.async_block_till_done()
    assert socket.closed
    assert not any(m.startswith("audio/7/") for m in socket.sent)
    assert entity.media_title is None
    audio_setup.apis[0].send_websocket_command.assert_awaited_once()


@pytest.mark.asyncio
async def test_unusable_same_player_frames_cannot_postpone_current_track_recovery(
    hass, audio_setup, monkeypatch
):
    monkeypatch.setattr(metadata_module, "_ACTIVE_SAMPLE_SECONDS", 0.04)
    monkeypatch.setattr(metadata_module, "_READ_SPACING_SECONDS", 0.01)
    recovered = asyncio.Event()

    async def read(player, **kwargs):
        recovered.set()
        return wire.parse_audio_events(
            {
                "audio_event": [
                    row(title="Useful current track", audiopath="spotify:track:useful")
                ]
            }
        )[0]

    status = AsyncMock(side_effect=read)
    monkeypatch.setattr(wire.AudioServerCommands, "async_player_status", status)
    await audio_setup.setup(playback=True)
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    await frame(hass, audio_setup, row())
    hass.bus.async_fire(EVENT, {"play-7": 2})
    await hass.async_block_till_done()

    async def noise():
        while not recovered.is_set():
            await frame(hass, audio_setup, {"playerid": 7})
            await asyncio.sleep(0.005)

    producer = asyncio.create_task(noise())
    try:
        try:
            await asyncio.wait_for(recovered.wait(), 0.25)
        except TimeoutError:
            pass
        assert recovered.is_set(), (
            "Receiving empty player rows is not confirmation of current content"
        )
        await producer
        await hass.async_block_till_done()
        assert entity.media_title == "Useful current track"
        assert status.await_count == 1
        audio_setup.apis[0].send_websocket_command.assert_not_awaited()
    finally:
        producer.cancel()
        await asyncio.gather(producer, return_exceptions=True)
