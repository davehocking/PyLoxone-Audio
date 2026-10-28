"""Owner-contract regressions: real HA and wire commands, synthetic I/O only."""

# Synthetic assertions and private integration state are the vertical test oracle.
# ruff: noqa: S101, INP001, SLF001
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from homeassistant.exceptions import HomeAssistantError
from test_audioserver_ha import audio_setup as _audio_setup
from test_audioserver_playback import SyntheticAudioSocket, rsa_key as _rsa_key
from test_native_source_return_ha import RADIO, install_sources, library_row
from test_source_simple_session_ha import session_room

from custom_components.loxone import audio_sources
from custom_components.loxone.pyloxone_api import audioserver as wire

audio_setup = _audio_setup
rsa_key = _rsa_key
_SOURCE_AND_SEEK = 2


async def simplified_harness(
    hass: Any, setup: Any, monkeypatch: Any, key: Any, *, spotify: bool = False,
) -> tuple[Any, dict[str, Any], list[Any], Any]:
    """Keep actual authentication, parsing, HA services and request settlement."""
    real_request = wire.AudioServerCommands._async_request
    entity, _emit, shortcuts = await install_sources(hass, setup, monkeypatch, spotify=spotify)
    monkeypatch.setattr(wire.AudioServerCommands, "_async_request", real_request)
    entity._audio_commands._credentials = lambda: ("synthetic-user", "synthetic-active-token")
    entity._audio_commands._timeout = 0.2
    observed_change = audio_sources._async_observed_change

    async def bounded_observation(*args: Any, **kwargs: Any) -> Any:
        kwargs["timeout"] = 0.2
        return await observed_change(*args, **kwargs)

    monkeypatch.setattr(audio_sources, "_async_observed_change", bounded_observation)
    target = library_row(time=0)
    if spotify:
        target.update(audiopath="spotify:track:original", parent={"id": "spotify:playlist:original"},
                      sourceName="Synthetic owner")
    controls: dict[str, Any] = {"target": target, "seek_reply": "ack", "source_reply": "ack"}
    sockets: list[Any] = []

    async def emit(row: dict[str, Any]) -> None:
        # Wait only for this frame, never drain HA tasks while a service is held.
        changed = asyncio.Event()
        remove = entity._audio_metadata.async_add_listener(row["playerid"], changed.set)
        try:
            await setup.queues[0].put(json.dumps({"audio_event": [row]}))
            async with asyncio.timeout(1):
                await changed.wait()
        finally:
            remove()

    class Socket(SyntheticAudioSocket):
        """Synthetic responses around the real crypto and request boundary."""

        async def send(self, message: str) -> None:
            """Deliver source feedback separately from optional position replies."""
            if message.startswith("secure/authenticate/"):
                await super().send(message)
                if len(sockets) == _SOURCE_AND_SEEK and controls.get("during_seek"):
                    await controls["during_seek"](entity, emit, target)
                return
            if message.startswith("audio/7/"):
                self.sent.append(message)
                if "/position/" in message:
                    if controls["seek_reply"] == "ack":
                        self.queue.put_nowait(json.dumps({"position_result": [{"position": 45}]}))
                    elif controls["seek_reply"] == "reject":
                        self.queue.put_nowait(json.dumps({"position_result": False}))
                    # Deliberately NO position feedback, even with an ordinary ack.
                else:
                    if controls["source_reply"] != "none":
                        reply = {"command": message}
                        if controls["source_reply"] == "reject":
                            reply["error"] = "synthetic rejection"
                        self.queue.put_nowait(json.dumps(reply))
                    await emit(controls.get("source_frame", target))
                return
            await super().send(message)

    def connect(*_args: Any, **_kwargs: Any) -> Socket:
        socket = Socket(key)
        sockets.append(socket)
        return socket

    monkeypatch.setattr(wire, "connect", connect)
    await emit({**target, "time": 45})
    await emit({"playerid": 7, "mode": "play", "eventype": 0, "audiopath": RADIO})
    assert shortcuts == []
    return entity, controls, sockets, emit


async def select(hass: Any, entity: Any, *, spotify: bool = False) -> None:
    """Bound the real HA service call including synthetic transport cleanup."""
    async with asyncio.timeout(2):
        await hass.services.async_call("media_player", "select_source", {
            "entity_id": entity.entity_id, "source": "Spotify" if spotify else "Local Library",
        }, blocking=True)


def sent_commands(sockets: list[Any]) -> list[str]:
    """Read only actual native commands, excluding synthetic authentication."""
    return [message for socket in sockets for message in socket.sent if message.startswith("audio/7/")]


@pytest.mark.asyncio
@pytest.mark.parametrize("spotify", [False, True], ids=["library", "spotify"])
async def test_confirmed_source_ignores_old_progress_guard_without_position_verification(
    hass: Any, audio_setup: Any, monkeypatch: Any, rsa_key: Any, *, spotify: bool,
) -> None:
    """An ordinary quantized position sample cannot turn playback into failure."""
    entity, controls, sockets, _emit = await simplified_harness(
        hass, audio_setup, monkeypatch, rsa_key, spotify=spotify,
    )

    async def progress(_entity: Any, emit: Any, target: Any) -> None:
        await emit({**target, "time": 1})

    controls["during_seek"] = progress
    await select(hass, entity, spotify=spotify)
    sent = sent_commands(sockets)
    assert len(sent) == _SOURCE_AND_SEEK
    assert sent[-1] == "audio/7/position/45.0"
    assert entity._audio_metadata.get(7).position == 1
    source = "Spotify" if spotify else "Local Library"
    assert entity._radio_catalogue.source_session(source).position == 1
    assert not entity._audio_commands.source_fences
    assert all(socket.closed for socket in sockets)
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ["ack", "reject", "none"])
async def test_optional_restore_is_one_ordinary_attempt_and_never_invents_progress(
    hass: Any, audio_setup: Any, monkeypatch: Any, rsa_key: Any, reply: str,
) -> None:
    """No progress frames are needed and even a missing reply preserves success."""
    entity, controls, sockets, _emit = await simplified_harness(hass, audio_setup, monkeypatch, rsa_key)
    controls["seek_reply"] = reply
    observed_position = 2
    controls["source_frame"] = {**controls["target"], "time": observed_position}
    await select(hass, entity)
    assert sent_commands(sockets)[-1] == "audio/7/position/45.0"
    assert len(sent_commands(sockets)) == _SOURCE_AND_SEEK
    assert entity._audio_metadata.get(7).position == observed_position
    assert entity._radio_catalogue.source_session("Local Library").position == observed_position
    assert not entity._audio_commands.source_fences
    assert not entity._audio_commands.source_observations
    assert all(socket.closed for socket in sockets)


@pytest.mark.asyncio
@pytest.mark.parametrize("spotify", [False, True], ids=["library", "spotify"])
async def test_source_return_accepts_provider_current_track_without_seeking_old_track(
    hass: Any, audio_setup: Any, monkeypatch: Any, rsa_key: Any, *, spotify: bool,
) -> None:
    """Exact saved return is stricter than an unknown provider-session resume."""
    entity, controls, sockets, _emit = await simplified_harness(
        hass, audio_setup, monkeypatch, rsa_key, spotify=spotify,
    )
    prefix = "spotify:" if spotify else "library:local:"
    observed_position = 3
    controls["source_frame"] = {**controls["target"], "audiopath": prefix + "track:next", "time": observed_position}
    previous = entity._radio_catalogue.source_session("Spotify" if spotify else "Local Library")
    with pytest.raises(HomeAssistantError):
        await select(hass, entity, spotify=spotify)
    assert len(sent_commands(sockets)) == 1
    saved = entity._radio_catalogue.source_session("Spotify" if spotify else "Local Library")
    assert saved is previous
    assert entity._audio_metadata.get(7).audio_path == prefix + "track:next"
    assert entity._audio_metadata.get(7).position == observed_position
    assert all(socket.closed for socket in sockets)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["source", "account", "room", "artwork", "volume", "title", "stopped"])
async def test_wrong_or_unrelated_feedback_cannot_confirm_source_return(
    hass: Any, audio_setup: Any, monkeypatch: Any, rsa_key: Any, fault: str,
) -> None:
    """Provider/account/room and actual playing evidence remain mandatory."""
    entity, controls, sockets, _emit = await simplified_harness(
        hass, audio_setup, monkeypatch, rsa_key, spotify=True,
    )
    before = entity._radio_catalogue.source_session("Spotify")
    changes = {
        "source": {"audiopath": "tunein:station:synthetic"},
        "account": {"sourceName": "Another synthetic owner"},
        "room": {"playerid": 8},
        "stopped": {"mode": "stop"},
    }
    if fault in changes:
        controls["source_frame"] = {**controls["target"], **changes[fault]}
    else:
        field = {"artwork": "coverurl", "volume": "volume", "title": "title"}[fault]
        controls["source_frame"] = {"playerid": 7, field: "synthetic"}
    with pytest.raises(HomeAssistantError):
        await select(hass, entity, spotify=True)
    assert len(sent_commands(sockets)) == 1
    assert entity._radio_catalogue.source_session("Spotify") is before
    assert all(socket.closed for socket in sockets)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["reject", "unconfirmed", "closed"])
async def test_failed_initial_command_never_attempts_optional_restore(
    hass: Any, audio_setup: Any, monkeypatch: Any, rsa_key: Any, fault: str,
) -> None:
    """Source success still needs ordinary settlement and fresh playing proof."""
    entity, controls, sockets, _emit = await simplified_harness(hass, audio_setup, monkeypatch, rsa_key)
    before = entity._radio_catalogue.source_session("Local Library")
    if fault == "closed":
        await entity._audio_commands.async_close()
    elif fault == "reject":
        controls["source_reply"] = "reject"
    else:
        controls["source_reply"] = "none"
        controls["source_frame"] = {"playerid": 7, "mode": "play", "eventype": 0, "audiopath": RADIO}
    with pytest.raises(HomeAssistantError):
        await select(hass, entity)
    assert all("/position/" not in command for command in sent_commands(sockets))
    assert len(sent_commands(sockets)) == (0 if fault == "closed" else 1)
    assert entity._radio_catalogue.source_session("Local Library") is before
    assert all(socket.closed for socket in sockets)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["track", "source", "account", "stop", "event", "capability", "close"])
async def test_optional_restore_checks_current_target_after_authentication(
    hass: Any, audio_setup: Any, monkeypatch: Any, rsa_key: Any, change: str,
) -> None:
    """A confirmed source is successful even when its optional seek is inapplicable."""
    entity, controls, sockets, _emit = await simplified_harness(hass, audio_setup, monkeypatch, rsa_key)

    async def changed(current: Any, emit: Any, target: Any) -> None:
        if change == "close":
            await current._audio_commands.async_close()
        else:
            values = {
                "track": {"audiopath": "library:local:track:next"},
                "source": {"audiopath": "spotify:track:next"},
                "account": {"sourceName": "another owner"},
                "stop": {"mode": "stop"},
                "event": {"eventype": 3},
                "capability": {"pbr": 0},
            }
            await emit({**target, **values[change]})

    controls["during_seek"] = changed
    await select(hass, entity)
    assert len(sent_commands(sockets)) == 1
    assert all(socket.closed for socket in sockets)
    assert not entity._audio_commands.source_fences


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["newer", "unload", "cancel"])
async def test_newest_ha_request_and_unload_cancel_optional_restore(
    hass: Any, audio_setup: Any, monkeypatch: Any, rsa_key: Any, action: str,
) -> None:
    """Held authentication never permits an obsolete service to send a seek."""
    entity, controls, sockets, _emit = await simplified_harness(hass, audio_setup, monkeypatch, rsa_key)
    ready, release = asyncio.Event(), asyncio.Event()

    async def held(_entity: Any, _emit: Any, _target: Any) -> None:
        ready.set()
        await release.wait()

    controls["during_seek"] = held
    pending = asyncio.create_task(select(hass, entity))
    try:
        await asyncio.wait_for(ready.wait(), timeout=1)
        async with asyncio.timeout(2):
            if action == "newer":
                await select(hass, entity)
            elif action == "unload":
                (entry,) = hass.config_entries.async_entries("loxone")
                assert await hass.config_entries.async_unload(entry.entry_id)
            else:
                pending.cancel()
            release.set()
            (result,) = await asyncio.gather(pending, return_exceptions=True)
        assert isinstance(result, (HomeAssistantError, asyncio.CancelledError))
        assert len(sent_commands(sockets)) == 1
        assert all(socket.closed for socket in sockets)
        assert not entity._audio_commands.source_fences
    finally:
        release.set()
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)




@pytest.mark.asyncio
@pytest.mark.parametrize("correct_provider", [False, True], ids=["other-radio-provider", "same-radio-provider"])
async def test_radio_source_return_uses_native_namespace_not_generic_radio_label(
    hass: Any, audio_setup: Any, monkeypatch: Any, rsa_key: Any, *, correct_provider: bool,
) -> None:
    """Radio source selection accepts its own stations, never a different provider."""
    entity, controls, sockets, emit = await simplified_harness(hass, audio_setup, monkeypatch, rsa_key)
    # The harness has remembered TuneIn; leave it before selecting that source.
    await emit(library_row())
    controls["source_frame"] = {
        "playerid": 7, "mode": "play", "eventype": 0, "sourceName": "Radio",
        "audiopath": ("tunein:" if correct_provider else "loxoneradio:") + "station:next",
    }

    async def action() -> None:
        async with asyncio.timeout(2):
            await hass.services.async_call("media_player", "select_source", {
                "entity_id": entity.entity_id, "source": "TuneIn",
            }, blocking=True)

    if correct_provider:
        await action()
        assert entity._radio_catalogue.source_session("TuneIn").audio_path == "tunein:station:next"
    else:
        with pytest.raises(HomeAssistantError):
            await action()
    assert len(sent_commands(sockets)) == 1
    assert all(socket.closed for socket in sockets)


@pytest.mark.asyncio
async def test_explicit_browser_item_still_requires_exact_item_feedback(
    hass: Any, audio_setup: Any, monkeypatch: Any, rsa_key: Any,
) -> None:
    """Provider-level return confirmation must never loosen explicit play-item."""
    entity, controls, sockets, _emit = await simplified_harness(hass, audio_setup, monkeypatch, rsa_key)
    media_id = await entity._radio_catalogue.async_source_return("Local Library")
    controls["source_frame"] = {**controls["target"], "audiopath": "library:local:track:different"}
    with pytest.raises(HomeAssistantError):
        async with asyncio.timeout(2):
            await entity._async_play_radio(media_id)
    assert len(sent_commands(sockets)) == 1
    assert all(socket.closed for socket in sockets)


@pytest.mark.asyncio
async def test_paused_native_spotify_return_accepts_advanced_track(
    hass: Any, audio_setup: Any, monkeypatch: Any, rsa_key: Any,
) -> None:
    """Native resume also follows the provider session rather than a paused item."""
    entity, controls, sockets, emit = await simplified_harness(
        hass, audio_setup, monkeypatch, rsa_key, spotify=True,
    )
    await emit({**controls["target"], "mode": "pause", "time": 10})
    controls["source_frame"] = {**controls["target"], "audiopath": "spotify:track:next", "time": 1}
    await select(hass, entity, spotify=True)
    assert sent_commands(sockets) == ["audio/7/serviceplay/spotify/synthetic-account/"]
    assert entity._radio_catalogue.source_session("Spotify").audio_path == "spotify:track:next"
    assert all(socket.closed for socket in sockets)
