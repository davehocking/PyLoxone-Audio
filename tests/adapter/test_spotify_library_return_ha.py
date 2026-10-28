"""Original source journey through real HA; entirely synthetic transports/identities."""
# Assertions/private members/fake transport signatures are intentional test contracts.
# ruff: noqa: S101, SLF001, INP001, ANN001, ANN003, ANN202, D103, PLR2004

import asyncio
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryState

from custom_components.loxone.pyloxone_api import audioserver as wire
from test_audioserver_ha import audio_setup, zone_entity_id  # noqa: F401 - imported fixture
from test_spotify_continuity import CONFIG, TRACK, CONTEXT, Session, native, playback


LIBRARY = "library:local:track:five"
FOLDER = "library:local:folder:synthetic-album"


async def library_journey(hass, audio_setup, monkeypatch, tmp_path, provider_state):
    """Wire actual HA services/catalogue/receiver; never open a device socket."""
    hass.config.config_dir = str(tmp_path)
    accounts = [{"cmd": "spotify", "id": "native-owner", "user": "native-user", "configerror": False}]
    monkeypatch.setattr(wire.AudioServerCommands, "async_service_accounts", AsyncMock(return_value=accounts))
    monkeypatch.setattr(wire.AudioServerCommands, "async_recent_sources", AsyncMock(return_value={"items": [
        {"audiopath": FOLDER, "type": 7, "title": "Synthetic album"},
        {"audiopath": "spotify@native-owner:track:" + "A" * 22, "type": 2, "title": "Prior room track"},
    ]}))

    async def folder(_self, service, _account, path, offset):
        paths = (["library:local:track:" + str(n) for n in range(4)] + [LIBRARY]) if service == "library" else [TRACK]
        return [{"start": offset, "totalitems": len(paths), "audiopath": path,
                 "items": [{"type": 2, "id": p, "audiopath": p, "name": "Synthetic"} for p in paths]}]

    monkeypatch.setattr(wire.AudioServerCommands, "async_media_folder", folder)
    entry = await audio_setup.setup(playback=True)
    await hass.config_entries.async_unload(entry.entry_id)
    hass.config_entries.async_update_entry(entry, options={**entry.options, "audioserver_spotify_return": {"synthetic-zone-7": CONFIG}})
    session = Session([native()])
    session.current = None
    provider = SimpleNamespace(domain="spotify", unique_id="synthetic-owner", entry_id="synthetic-entry",
                               state=ConfigEntryState.LOADED, runtime_data=SimpleNamespace(session=session))
    get_entry = hass.config_entries.async_get_entry
    monkeypatch.setattr(hass.config_entries, "async_get_entry", lambda key: provider if key == provider.entry_id else get_entry(key))
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    queue = audio_setup.queues[-1]
    writes = []
    spotify_row = {"playerid": 7, "mode": "play", "eventype": 0, "audiopath": TRACK,
                   "parent": {"id": CONTEXT}, "sourceName": "native-user", "time": 13.264, "duration": 180, "pbr": 32}
    library_row = {"playerid": 7, "mode": "play", "eventype": 0, "audiopath": LIBRARY,
                   "parent": {"id": FOLDER}, "time": 45.0, "duration": 240, "pbr": 32}

    async def emit(row):
        queue.put_nowait(json.dumps({"audio_event": [row]}))
        await hass.async_block_till_done()

    async def request(_self, command, _key, *, is_current=None, on_send=None, **_kwargs):
        assert is_current is not None and is_current()
        if on_send:
            on_send()
        writes.append(command)
        bits = command.split("/")
        if bits[2:4] == ["library", "play"]:
            assert unquote(bits[4]) == LIBRARY
            if provider_state == "paused":
                session.current["is_playing"] = False
            else:
                session.current = None
            row = {**library_row, "time": 0}
        elif bits[2:4] == ["serviceplay", "spotify"]:
            session.current = playback()
            row = spotify_row
        elif bits[2] == "position":
            current_row = spotify_row if entity._audio_metadata.get(7).source == "Spotify" else library_row
            row = {**current_row, "time": float(bits[3])}
            asyncio.get_running_loop().call_soon(queue.put_nowait, json.dumps({"audio_event": [row]}))
            return [{"position": float(bits[3])}]
        else:
            raise AssertionError("Unexpected synthetic command: " + command)
        asyncio.get_running_loop().call_soon(queue.put_nowait, json.dumps({"audio_event": [row]}))
        return None

    monkeypatch.setattr(wire.AudioServerCommands, "_async_request", request)


    async def source(name):
        await hass.services.async_call("media_player", "select_source", {"entity_id": entity.entity_id, "source": name}, blocking=True)
        await hass.async_block_till_done()

    await emit(library_row)
    await source("Spotify")  # No HA bookmark: concrete room-native recent track permits first return.
    assert entity._audio_metadata.get(7).audio_path == TRACK
    await source("Local Library")  # Departure never requires optional capture.
    saved = entity._radio_catalogue.source_session('Spotify')
    assert saved is not None and saved.audio_path == TRACK
    assert entity._audio_metadata.get(7).audio_path == LIBRARY
    assert entity._audio_metadata.get(7).position == 45.0
    return entity, session, provider, source, writes, saved, entry




@pytest.mark.asyncio
async def test_library_clock_change_during_return_is_not_rebased_or_overwritten(hass, audio_setup, monkeypatch, tmp_path):
    entity, session, _provider, source, writes, _saved, entry = await library_journey(hass, audio_setup, monkeypatch, tmp_path, "detached")
    before = list(writes)

    accounts = entity._audio_commands.async_service_accounts
    async def newer_action():
        seen = asyncio.Event()
        remove = entity._audio_metadata.async_add_listener(7, seen.set)
        audio_setup.queues[-1].put_nowait(json.dumps({"audio_event": [{
            "playerid": 7, "audiopath": LIBRARY, "parent": {"id": FOLDER},
            "mode": "play", "eventype": 0, "time": 45.001, "duration": 240, "pbr": 32,
        }]}))
        try:
            await asyncio.wait_for(seen.wait(), 1)
        finally:
            remove()
        return await accounts()

    monkeypatch.setattr(entity._audio_commands, 'async_service_accounts', newer_action)
    # Same-item Library progress does not veto this explicit new source request.
    await source("Spotify")
    assert writes[:len(before)] == before
    assert len(writes) == len(before) + 2
    assert TRACK.replace(":", "%3A") in writes[len(before)]
    assert writes[-1] == "audio/7/position/13.264"
    assert not [call for call in session.calls if call[0] == "PUT"]
    await hass.config_entries.async_unload(entry.entry_id)
