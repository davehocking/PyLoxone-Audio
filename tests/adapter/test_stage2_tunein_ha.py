"""Real catalogue, registered source service and native auth/feedback timing.

Invented peer delays use an explicit wall-clock schedule, NOT audible timing or
accelerated timeout deadlines. The ACK-only case waits the actual 15s deadline.
"""
import asyncio
from datetime import datetime, timedelta
import json
import time

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.components.media_player.errors import BrowseError
from homeassistant.util import dt as dt_util
from test_audioserver_ha import audio_setup
from test_audioserver_playback import SyntheticAudioSocket, rsa_key
from test_audio_modes_ha import mode_harness
from test_stage2_modes_ha import output
from custom_components.loxone.pyloxone_api import audioserver as wire
from pyloxone_audio import native, clock as native_clock

# Capture the real method at collection, before audio_setup's discovery mocks.
REAL_RADIO_SERVICES = wire.AudioServerCommands.async_radio_services


@pytest.mark.parametrize("outcome", ["confirmed", "ack-without-feedback", "authentication-denied"])
async def test_registered_tunein_selection_partitions_native_waits_without_shortening_deadlines(
    hass, audio_setup, monkeypatch, rsa_key, outcome,
):
    start = dt_util.utcnow()
    wall = [start]
    elapsed = [0]
    timeline, routes, sockets = [], [], []
    sent = asyncio.Event()
    real_start = time.monotonic()

    def mark(phase, advance=0):
        elapsed[0] += advance
        wall[0] = start + timedelta(seconds=elapsed[0])
        timeline.append({"phase": phase, "synthetic_wall_seconds": elapsed[0],
                         "actual_elapsed_seconds": time.monotonic() - real_start})

    class SampleClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return wall[0].astimezone(tz) if tz is not None else wall[0].replace(tzinfo=None)

    monkeypatch.setattr(native, "datetime", SampleClock)
    monkeypatch.setattr(native_clock, "datetime", SampleClock)
    monkeypatch.setattr(dt_util, "utcnow", lambda: wall[0])
    h = await mode_harness(hass, audio_setup, monkeypatch, rsa_key, source="library")
    room = h.entities[7]
    # Undo only the harness's shortened wire-test timeout, using the actual
    # constructor default. No product or source-feedback timeout is changed.
    h.commands._timeout = 15.0
    monkeypatch.setattr(h.commands, "async_radio_services", REAL_RADIO_SERVICES.__get__(h.commands))
    station_path = "tunein:station:synthetic/+station"
    station = {"type": 2, "name": "Synthetic station", "audiopath": station_path}
    route = "audio/7/serviceplay/radio/world/tunein%3Astation%3Asynthetic%2F%2Bstation"

    class Peer(SyntheticAudioSocket):
        def __init__(self):
            super().__init__(rsa_key)
            if outcome == "authentication-denied":
                self.auth_result = "authentication failed"

        async def send(self, message):
            if message == "audio/cfg/getradios":
                self.sent.append(message)
                routes.append(message)
                mark("catalogue-provider-reply", 2)
                self.queue.put_nowait(json.dumps({"getradios_result": [
                    {"cmd": "world", "root": "root", "name": "Synthetic radio"}]}))
            elif message == "audio/cfg/getservicefolder/world/world/root/0/50":
                self.sent.append(message)
                routes.append(message)
                mark("catalogue-station-reply", 3)
                self.queue.put_nowait(json.dumps({"getservicefolder_result": [
                    {"start": 0, "totalitems": 1, "items": [station]}]}))
            elif message == route:
                self.sent.append(message)
                routes.append(message)
                mark("station-send-and-ack")
                self.queue.put_nowait(json.dumps({"command": message}))
                sent.set()
            else:
                if message.startswith("secure/authenticate/"):
                    mark("authentication-reply", 1)
                await super().send(message)

    def connect(*_args, **_kwargs):
        socket = Peer()
        sockets.append(socket)
        return socket

    monkeypatch.setattr(wire, "connect", connect)
    # Denied auth gets its own real catalogue attempt, with no station dispatch.
    if outcome == "authentication-denied":
        with pytest.raises(BrowseError) as failure:
            await room.async_browse_media("pyloxone_radio", "pyloxone-audio:radio")
        output("tunein-auth-denied.json", {"timeline": timeline, "routes": routes,
            "failure_type": type(failure.value).__name__, "sockets_closed": all(s.closed for s in sockets)})
        assert routes == [] and all(s.closed for s in sockets)
        return
    providers = await room.async_browse_media("pyloxone_radio", "pyloxone-audio:radio")
    provider = next(child for child in providers.children if child.title == "Synthetic radio")
    page = await room.async_browse_media(provider.media_content_type, provider.media_content_id)
    selection = page.children[0]
    mark("registered-play-media")
    task = asyncio.create_task(hass.services.async_call("media_player", "play_media", {
        "entity_id": room.entity_id, "media_content_type": selection.media_content_type,
        "media_content_id": selection.media_content_id}, blocking=True))
    try:
        await asyncio.wait_for(sent.wait(), 2)
        await asyncio.sleep(0)
        assert not task.done(), "Command ACK is not native playing confirmation"
        if outcome == "ack-without-feedback":
            with pytest.raises(HomeAssistantError):
                await task
            assert 7 in h.commands.source_fences
            # No automatic retry. A NEW explicit owner request is a different
            # contract (latest-intent wins), not an automatic retry probe.
            assert routes.count(route) == 1
        else:
            mark("wrong-room-feedback", 2)
            await h.emit({"playerid": 8, "eventype": 0, "mode": "play", "audiopath": station_path})
            assert not task.done()
            mark("exact-room-playing-feedback", 3)
            feedback = {"playerid": 7, "eventype": 0, "mode": "play", "audiopath": station_path}
            await h.emit(feedback)
            await asyncio.wait_for(task, 2)
            mark("registered-play-media-complete")
            assert room.source == "TuneIn"
            # Qualified source-return uses the SAME registered source service
            # and native wire, not a fast mock or a new provider transport.
            mark("external-switch-away", 1)
            await h.emit(h.rows[7])
            mark("external-switch-corroborated", 1)
            await h.emit(h.rows[7])
            sent.clear()
            mark("registered-select-source")
            task = asyncio.create_task(hass.services.async_call("media_player", "select_source", {
                "entity_id": room.entity_id, "source": "TuneIn"}, blocking=True))
            await asyncio.wait_for(sent.wait(), 2)
            await asyncio.sleep(0)
            assert not task.done()
            mark("source-return-feedback", 4)
            await h.emit(feedback)
            await asyncio.wait_for(task, 2)
            mark("registered-select-source-complete")
            assert room.source == "TuneIn" and routes.count(route) == 2
            assert not h.commands.source_fences
        output(f"tunein-{outcome}.json", {"timeline": timeline, "routes": routes,
            "command_timeout_seconds": h.commands._timeout, "feedback_timeout_seconds": 15,
            "source_state": room.source, "sockets_closed": all(s.closed for s in sockets),
            "audible_onset": "UNKNOWN", "historical_twenty_seconds_reproduced": False})
        assert all(s.closed for s in sockets)
        assert not any("seek" in r or "/position/" in r for r in routes)
        h.apis[0].send_websocket_command.assert_not_awaited()
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
