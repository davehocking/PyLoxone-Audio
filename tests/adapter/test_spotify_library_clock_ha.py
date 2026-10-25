"""Synthetic clocks through real HA service/event dispatch; no household access."""
# Fixture redefinitions are the standard imported-HA-fixture pattern.
# ruff: noqa: S101, SLF001, INP001, ANN001, ANN202, D103, PLR2004, F811

import asyncio
from copy import deepcopy
import json

import pytest
from homeassistant.exceptions import HomeAssistantError

from test_audioserver_ha import audio_setup  # noqa: F401 - real HA fixture
from test_spotify_continuity import CONTEXT, TRACK, playback
from custom_components.loxone.pyloxone_api import audioserver as wire
from custom_components.loxone import audio_sources
from test_spotify_library_return_ha import FOLDER, LIBRARY, library_journey


async def emit(hass, audio_setup, row):
    audio_setup.queues[-1].put_nowait(json.dumps({"audio_event": [row]}))
    await hass.async_block_till_done()


def library_row(position):
    return {"playerid": 7, "mode": "play", "eventype": 0, "audiopath": LIBRARY,
            "parent": {"id": FOLDER}, "time": position, "duration": 240, "pbr": 32}


def paused_spotify_row():
    return {"playerid": 7, "mode": "stop", "eventype": 0, "audiopath": TRACK,
            "parent": {"id": CONTEXT}, "sourceName": "native-user", "time": 13.264,
            "duration": 180, "pbr": 32}


@pytest.mark.asyncio
@pytest.mark.parametrize("clock", ["static-control", "ordinary-progress"])
async def test_library_continues_before_posttransfer_native_readiness(
    hass, audio_setup, monkeypatch, tmp_path, clock,
):
    entity, session, _provider, source, writes, saved, entry = await library_journey(
        hass, audio_setup, monkeypatch, tmp_path, "detached",
    )
    before = list(writes)
    queue = deepcopy(session.queue)
    anchor = entity._audio_metadata.get(7)
    observed = []
    session.current=playback()
    session.current['is_playing']=False
    original=wire.AudioServerCommands._async_request

    async def native_send(self,command,key,*,is_current,on_send,**kwargs):
        assert command=='audio/7/serviceplay/spotify/native-owner/'
        assert is_current()
        on_send()
        # Native acknowledgement is not proof of Spotify playback. Continuing
        # Library feedback must not satisfy the exact-source observer.
        if clock == "ordinary-progress":
            await asyncio.sleep(0.25)
            from homeassistant.util import dt as dt_util  # noqa: PLC0415
            elapsed = (dt_util.utcnow() - anchor.position_updated_at).total_seconds()
            await emit(hass, audio_setup, library_row(45.0 + elapsed))
            observed.append(elapsed)
        else:
            await emit(hass, audio_setup, library_row(45.0))

        assert entity._audio_metadata.get(7).source=='Local Library'
        assert not entity._audio_commands.source_observations[7].done()
        return await original(self,command,key,is_current=is_current,on_send=None,**kwargs)

    monkeypatch.setattr(wire.AudioServerCommands,'_async_request',native_send)
    await source("Spotify")
    assert writes==before+['audio/7/serviceplay/spotify/native-owner/']
    assert all(c[0]=='GET' for c in session.calls)
    assert session.queue == queue
    assert not entity._spotify_return.uncertain
    assert entity._spotify_return.bookmark is None
    assert entity._audio_metadata.get(7).audio_path == saved.audio_path
    if clock == "ordinary-progress":
        assert len(observed) == 1
        assert observed[0] >= 0.25
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("discontinuity", ["forward-seek", "backward-seek", "clock-loss", "pause", "new-track"])
@pytest.mark.parametrize("phase", ["pre-send", "post-transfer"])
async def test_library_discontinuity_never_overwrites_or_replays(  # noqa: PLR0913 - exact HA fixture and phase matrix
    hass, audio_setup, monkeypatch, tmp_path, phase, discontinuity,
):
    entity, session, _provider, source, writes, _saved, entry = await library_journey(
        hass, audio_setup, monkeypatch, tmp_path, "detached",
    )
    before = list(writes)
    injected = False
    session.current=playback()
    session.current['is_playing']=False

    async def action():
        nonlocal injected
        if injected:
            return
        injected = True
        await asyncio.sleep(0.1)
        row = library_row(65.0 if discontinuity == "forward-seek" else 40.0)
        if discontinuity == "clock-loss":
            row.pop("time")
        elif discontinuity == "pause":
            row.update(mode="pause", time=45.0)
        elif discontinuity == "new-track":
            row.update(audiopath="library:local:track:newer", time=45.1)
        await emit(hass, audio_setup, row)

    if phase == "pre-send":
        async def during_read(url):
            if url.endswith("/me/player"):
                await action()
        session.on_read = during_read
    else:
        # Migrate the removed transfer boundary to the actual native send.
        async def native_send(_self,command,_key,*,is_current,on_send,**_kwargs):
            assert is_current()
            on_send()
            writes.append(command)
            await action()
            return None
        monkeypatch.setattr(wire.AudioServerCommands,'_async_request',native_send)
        observed_change=audio_sources._async_observed_change
        async def bounded(*args,**kwargs):
            return await observed_change(*args,**{**kwargs,'timeout':0.05})
        monkeypatch.setattr(audio_sources,'_async_observed_change',bounded)

    clock_only = phase == "pre-send" and discontinuity in {"forward-seek", "backward-seek", "clock-loss"}
    if clock_only:
        # Source preparation keeps current item/mode checks, without clock arbitration.
        await source("Spotify")
    else:
        with pytest.raises(HomeAssistantError):
            await source("Spotify")
    assert injected
    expected = before + (["audio/7/serviceplay/spotify/native-owner/"]
                         if phase == "post-transfer" or clock_only else [])
    assert writes==expected
    puts = [c for c in session.calls if c[0] == "PUT"]
    assert not puts
    if phase == "post-transfer":
        assert entity._audio_commands.source_fences
        await asyncio.sleep(0.06)
        assert writes==expected  # No automatic replay or obsolete seek.
    await hass.config_entries.async_unload(entry.entry_id)
