"""Repeated real HA entity actions; only synthetic provider/native I/O."""
# ruff: noqa: S101, SLF001, INP001, ANN001, D103, PLR2004, F811, ANN202, ANN003
from copy import deepcopy
import asyncio
import json

import pytest
from custom_components.loxone.pyloxone_api import audioserver as wire

from test_audioserver_ha import audio_setup  # noqa: F401 - fixture
from test_spotify_library_return_ha import library_journey


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_state", ["paused", "detached"])
async def test_same_controller_supports_repeated_library_spotify_returns(
    hass, audio_setup, monkeypatch, tmp_path, provider_state,
):
    entity, session, _provider, source, writes, _saved, entry = await library_journey(
        hass, audio_setup, monkeypatch, tmp_path, provider_state,
    )
    controller = entity._spotify_return
    preview = deepcopy(session.queue)
    for cycle in range(3):
        saved = entity._radio_catalogue.source_session('Spotify')
        assert saved is not None
        before = list(writes)
        await source("Spotify")
        assert writes[:len(before)] == before
        added=writes[len(before):]
        assert len(added)==(2 if provider_state=='detached' else 1)
        assert (saved.audio_path.replace(':','%3A') in added[0]) if provider_state=='detached' else added[0].endswith('/native-owner/')
        assert entity._spotify_return is controller
        assert controller.bookmark is None
        assert not controller.uncertain
        assert not entity._audio_commands.source_fences
        assert not controller._account["lock"].locked()
        assert controller._account["owner"] is None
        assert entity._source_task is None
        assert session.queue == preview
        if cycle < 2:
            await source("Local Library")
            assert entity._source_task is None
            assert entity._audio_metadata.get(7).source == "Local Library"
    assert all(method=='GET' for method,_,_ in session.calls)
    assert session.transfer_count == 0
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_state", ["paused", "detached"])
async def test_same_controller_supports_repeated_tunein_spotify_returns(
    hass, audio_setup, monkeypatch, tmp_path, provider_state,
):
    entity, session, _provider, source, writes, _saved, entry = await library_journey(
        hass, audio_setup, monkeypatch, tmp_path, provider_state,
    )
    await source("Spotify")
    controller = entity._spotify_return
    preview = deepcopy(session.queue)
    tunein = "tunein:station:synthetic"
    recent = entity._audio_commands.async_recent_sources.return_value
    recent["items"].append({"audiopath": tunein, "type": 2, "title": "Synthetic radio"})
    previous_request = wire.AudioServerCommands._async_request

    async def request(self, command, key, *, is_current=None, on_send=None, **kwargs):
        bits = command.split("/")
        if bits[2:5] == ["serviceplay", "radio", "world"]:
            assert is_current()
            on_send()
            writes.append(command)
            if provider_state == "paused":
                session.current["is_playing"] = False
            else:
                session.current = None
            asyncio.get_running_loop().call_soon(
                audio_setup.queues[-1].put_nowait,
                json.dumps({"audio_event": [{"playerid": 7, "audiopath": tunein, "mode": "play"}]}),
            )
            return True
        return await previous_request(
            self, command, key, is_current=is_current, on_send=on_send, **kwargs,
        )

    monkeypatch.setattr(wire.AudioServerCommands, "_async_request", request)
    for _ in range(3):
        await source("TuneIn")
        assert entity._audio_metadata.get(7).source == "TuneIn"
        before = list(writes)
        await source("Spotify")
        assert entity._spotify_return is controller
        added=writes[len(before):]
        assert len(added)==(2 if provider_state=='detached' else 1)
        assert '/serviceplay/spotify/native-owner/' in added[0]
        if provider_state=='detached': assert entity._audio_metadata.get(7).audio_path.replace(':','%3A') in added[0]
        assert not controller.uncertain
        assert not controller.commands.source_fences
        assert controller._account["owner"] is None
        assert entity._source_task is None
        assert not controller._account["lock"].locked()
        assert session.queue == preview
    assert session.transfer_count == 0
    assert all(c[0]=='GET' for c in session.calls)
    await hass.config_entries.async_unload(entry.entry_id)
