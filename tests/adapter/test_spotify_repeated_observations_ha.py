"""
Repeated entity actions with reordered feedback and optional failures.

All observations and commands are synthetic. No household transport is opened.
"""
# ruff: noqa: S101, SLF001, INP001, ANN001, ANN003, ANN202, D103, F811
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

from aiohttp import ClientError
import pytest
from homeassistant.exceptions import HomeAssistantError

from test_audioserver_ha import audio_setup  # noqa: F401 - fixture
from test_spotify_continuity import TRACK, CONTEXT, playback
from test_spotify_library_return_ha import library_journey
from custom_components.loxone.pyloxone_api import audioserver as wire
from test_source_failure_qualification_ha import direct_capture


@pytest.mark.asyncio
@pytest.mark.parametrize("order", ["native-first", "provider-first", "provider-204", "read-failure", "missing-native"])
async def test_second_return_releases_same_controller_after_late_or_missing_feedback(  # noqa: PLR0915 - retain one complete repeated-action lifecycle
    hass, audio_setup, monkeypatch, tmp_path, order,
):
    entity, session, _provider, source, writes, _saved, entry = await library_journey(
        hass, audio_setup, monkeypatch, tmp_path, "paused",
    )
    controller = entity._spotify_return
    await source("Spotify")
    await source("Local Library")
    before = list(writes)
    puts_before = sum(c[0] == "PUT" for c in session.calls)
    queue_before = deepcopy(session.queue)
    pending_native = None
    failed_request = None
    retained = entity._radio_catalogue.source_session('Spotify')
    calls_at_send=[]
    async def feedback():
        await asyncio.sleep(0)
        audio_setup.queues[-1].put_nowait(json.dumps({'audio_event':[{
            'playerid':7,'audiopath':TRACK,'parent':{'id':CONTEXT},
            'sourceName':'native-user','mode':'play','eventype':0,
            'time':13.264,'duration':180,'pbr':32,
        }]}))
        await hass.async_block_till_done()
    async def request(_self,command,_key,*,is_current,on_send,**_kwargs):
        nonlocal pending_native,failed_request
        assert command=='audio/7/serviceplay/spotify/native-owner/'
        assert is_current()
        on_send()
        writes.append(command)
        calls_at_send.append(len(session.calls))
        # No optional provider re-read is required after native dispatch.
        if order=='provider-204':session.current=None
        elif order=='read-failure':
            from unittest.mock import AsyncMock
            failed_request=AsyncMock(side_effect=ClientError('Synthetic post-send optional loss'))
            session.async_request=failed_request
        if order=='missing-native':return
        if order=='native-first':await feedback()
        else:pending_native=asyncio.create_task(feedback())
    monkeypatch.setattr(wire.AudioServerCommands,'_async_request',request)
    if order=='missing-native':
        with pytest.raises(HomeAssistantError):await source('Spotify')
        assert entity._radio_catalogue.source_session('Spotify') is retained
    else:await source('Spotify')
    if pending_native is not None:await pending_native
    assert not controller.uncertain
    assert bool(controller.commands.source_fences)==(order=='missing-native')
    assert controller.bookmark is None
    assert entity._source_task is None
    assert controller._account['owner'] is None
    assert len(session.calls)==calls_at_send[0]
    if order!='missing-native':assert entity._audio_metadata.get(7).audio_path==TRACK
    assert entity._spotify_return is controller
    assert writes == before+['audio/7/serviceplay/spotify/native-owner/']
    await asyncio.sleep(0)
    assert len(writes)==len(before)+1
    if failed_request is not None:failed_request.assert_not_awaited()
    assert sum(c[0] == "PUT" for c in session.calls) == puts_before == 0
    assert session.queue == queue_before
    assert not controller._account["lock"].locked()
    await hass.config_entries.async_unload(entry.entry_id)
    assert not controller.commands.source_fences


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["read-unavailable", "positive-clock-conflict", "zero-native-sample"])
async def test_second_departure_failure_is_not_inherited_dispatch_uncertainty(  # noqa: PLR0915 - preserve failure plus explicit recovery without fixture mutation
    hass, audio_setup, monkeypatch, tmp_path, failure,
):
    entity, session, _provider, source, writes, _saved, entry = await library_journey(
        hass, audio_setup, monkeypatch, tmp_path, "paused",
    )
    await source("Spotify")
    controller = entity._spotify_return
    before = list(writes)
    put_count = sum(c[0] == "PUT" for c in session.calls)
    original_request = session.async_request
    snapshot = entity._audio_metadata.get(7)
    if failure == "positive-clock-conflict":
        session.current["progress_ms"] = 65000
    elif failure == "zero-native-sample":
        # This is a known presentation placeholder case, NOT a claim that it
        # caused the owner report. Raw coordinator and smoothed HA clocks differ.
        queue = audio_setup.queues[-1]
        queue.put_nowait(json.dumps({"audio_event": [{
            "playerid": 7, "audiopath": TRACK, "parent": {"id": CONTEXT},
            "sourceName": "native-user", "mode": "play", "time": 0,
            "duration": 180, "pbr": 32,
        }]}))
        await hass.async_block_till_done()
        assert entity._audio_metadata.get(7).position == 0
        assert entity.media_position > 0
    else:
        async def unavailable(method, url, **kwargs):
            if method == "GET" and url.endswith("/me/player"):
                msg = "Synthetic optional read outage"
                raise ClientError(msg)
            return await original_request(method, url, **kwargs)
        session.async_request = unavailable
    if failure == "read-unavailable":
        await source("Local Library")
        assert len(writes) > len(before)
    else:
        with pytest.raises(HomeAssistantError):
            # Retain raw-vs-smoothed diagnostic qualification on the dormant
            # helper directly. It must NOT veto the actual departure anymore.
            await direct_capture(entity)
        assert writes == before
        assert not hasattr(entity, "_audio_last_source_failure")
        await source('Local Library')
        assert len(writes)>len(before)
    assert entity._spotify_return is controller
    assert controller.bookmark is None
    assert not controller.uncertain
    assert not controller.commands.source_fences
    assert not controller._account["lock"].locked()
    assert entity._source_task is None
    if failure != "read-unavailable":
        # Restore matching evidence and explicitly request anew. A read-only
        # conflict does not permanently consume the controller or room.
        session.current = playback()
        session.current["progress_ms"] = round(snapshot.position * 1000)
        audio_setup.queues[-1].put_nowait(json.dumps({"audio_event": [{
            "playerid": 7, "audiopath": TRACK, "parent": {"id": CONTEXT},
            "sourceName": "native-user", "mode": "play", "time": snapshot.position,
            "duration": 180, "pbr": 32,
        }]}))
        await hass.async_block_till_done()
        await source("Local Library")
        await source("Spotify")
        assert not controller.uncertain
        assert not controller.commands.source_fences
    assert sum(c[0] == "PUT" for c in session.calls) == put_count
    await hass.config_entries.async_unload(entry.entry_id)
