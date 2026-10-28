"""Source returns through actual HA services, synthetic indexed contexts only."""
# ruff: noqa: S101, INP001, ANN001, D103, SLF001, PLC0415
import asyncio
import json
from urllib.parse import unquote
from unittest.mock import AsyncMock

import pytest

from test_audioserver_ha import audio_setup, zone_entity_id  # noqa: F401
from custom_components.loxone.pyloxone_api import audioserver as wire

TRACK = "library:local:track:five"
PARENT = "library:local:folder:album"
RADIO = "tunein:station:synthetic"


def library_row(**changes):
    return {"playerid": 7, "mode": "play", "eventype": 0,
            "audiopath": TRACK, "parent": {"id": PARENT},
            "title": "Synthetic fifth track", "time": 45, "duration": 240,
            "pbr": 32, **changes}


async def install_sources(hass, audio_setup, monkeypatch, *, spotify=False, player=7, previous_spotify=False):
    async def folder(_self, service, account, path, offset):
        if service == "library":
            paths = (["library:local:track:" + str(n) for n in range(4)] + [TRACK]) if path == PARENT else [TRACK]
            return [{"start": offset, "totalitems": len(paths), "audiopath": path,
                     "items": [{"type": 2, "id": p, "audiopath": p, "name": "Synthetic"} for p in paths]}]
        if service == "spotify":
            return [{"start": offset, "totalitems": 1, "items": [{
                "type": 2 if path == "spotify:playlist:original" else 7,
                "id": "spotify@synthetic-account:track:original" if path == "spotify:playlist:original" else "spotify@synthetic-account:playlist:original",
                "name": "Synthetic Spotify",
            }]}]
        return [{"start": 0, "totalitems": 0, "items": []}]

    monkeypatch.setattr(wire.AudioServerCommands, "async_media_folder", folder)
    if spotify:
        monkeypatch.setattr(wire.AudioServerCommands, "async_service_accounts", AsyncMock(return_value=[{
            "cmd": "spotify", "id": "synthetic-account", "user": "Synthetic owner", "name": "Synthetic", "configerror": False,
        }]))
    monkeypatch.setattr(wire.AudioServerCommands, "async_recent_sources", AsyncMock(return_value={
        "items": [{"type": 7, "audiopath": PARENT, "title": "Synthetic album"}] + ([{
            "type": 2 if previous_spotify else 7,
            "audiopath": "spotify@synthetic-account:track:original" if previous_spotify else "spotify@synthetic-account:playlist:original",
            "title": "Synthetic previously selected track" if previous_spotify else "Synthetic playlist",
        }] if spotify else []), "ts": 1,
    }))
    await audio_setup.setup(playback=True)
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, player))

    async def emit(row):
        await audio_setup.queues[0].put(json.dumps({"audio_event": [row]}))
        await hass.async_block_till_done()

    calls = []

    async def request(_self, command, key, *, is_current=None, on_send=None, **kwargs):
        assert is_current is not None
        if not is_current():
            raise wire.AudioCommandError("Synthetic wire guard rejected stale action")
        if on_send:
            on_send()
        calls.append(command)
        bits = command.split("/")
        target_player = int(bits[1])
        if bits[2:4] == ["library", "play"]:
            path = unquote(bits[4])
            # Deterministic firmware counterfactual: selecting an album starts
            # another track; selecting the exact track preserves its identity.
            row = library_row(playerid=target_player, audiopath=path if path.startswith("library:local:track:") else "library:local:track:six", time=0)
            asyncio.get_running_loop().call_soon(audio_setup.queues[0].put_nowait, json.dumps({"audio_event": [row]}))
            return None
        if bits[2:4] == ["serviceplay", "spotify"]:
            path = unquote(bits[5]).replace("spotify@synthetic-account:", "spotify:")
            row = library_row(playerid=target_player, audiopath=path if path.startswith(("spotify:track:", "spotify:episode:")) else "spotify:track:original", parent={"id": "spotify:playlist:original"}, sourceName="Synthetic owner", time=0)
            asyncio.get_running_loop().call_soon(audio_setup.queues[0].put_nowait, json.dumps({"audio_event": [row]}))
            return None
        if bits[2] == "position":
            snapshot = entity._audio_metadata.get(target_player)
            position = float(bits[3])
            row = library_row(playerid=target_player, audiopath=snapshot.audio_path, parent={"id": snapshot.parent_id}, sourceName=snapshot.source_name, time=position)
            asyncio.get_running_loop().call_soon(audio_setup.queues[0].put_nowait, json.dumps({"audio_event": [row]}))
            return [{"position": position}]
        raise AssertionError("Unexpected synthetic command: " + command)

    monkeypatch.setattr(wire.AudioServerCommands, "_async_request", request)
    return entity, emit, calls


@pytest.mark.asyncio
async def test_source_return_keeps_prior_library_track_and_verified_parent_cursor(hass, audio_setup, monkeypatch):
    entity, emit, calls = await install_sources(hass, audio_setup, monkeypatch)
    await emit(library_row())
    await emit({"playerid": 7, "mode": "play", "eventype": 0, "audiopath": RADIO})
    await hass.services.async_call("media_player", "select_source", {
        "entity_id": entity.entity_id, "source": "Local Library",
    }, blocking=True)
    assert calls == [
        "audio/7/library/play/library%3Alocal%3Atrack%3Afive/parentpath/library%3Alocal%3Afolder%3Aalbum/4",
        "audio/7/position/45.0",
    ]
    assert entity._audio_metadata.get(7).audio_path == TRACK
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_library_return_finds_unique_track_beyond_first_native_page(hass, audio_setup, monkeypatch):
    entity, emit, calls = await install_sources(hass, audio_setup, monkeypatch)
    original_folder = wire.AudioServerCommands.async_media_folder
    paths = ["library:local:track:" + str(n) for n in range(63)] + [TRACK]
    offsets = []
    async def paged(client, service, account, path, offset):
        if path != PARENT:
            return await original_folder(client, service, account, path, offset)
        offsets.append(offset)
        return [{"start": offset, "totalitems": len(paths), "audiopath": path,
                 "items": [{"type": 2, "id": p, "audiopath": p, "name": "Synthetic"} for p in paths[offset:offset+50]]}]
    monkeypatch.setattr(wire.AudioServerCommands, "async_media_folder", paged)
    await emit(library_row())
    await emit({"playerid": 7, "mode": "play", "eventype": 0, "audiopath": RADIO})
    await hass.services.async_call("media_player", "select_source", {
        "entity_id": entity.entity_id, "source": "Local Library",
    }, blocking=True)
    assert calls[0].endswith("/parentpath/library%3Alocal%3Afolder%3Aalbum/63")
    assert offsets == [0, 50, 0, 50]  # Full stable-order revalidation, not just a count.


@pytest.mark.asyncio
async def test_native_spotify_return_keeps_prior_track_not_playlist_restart(hass, audio_setup, monkeypatch):
    entity, emit, calls = await install_sources(hass, audio_setup, monkeypatch, spotify=True)
    await emit(library_row(audiopath="spotify:track:original", parent={"id": "spotify:playlist:original"}, sourceName="Synthetic owner"))
    await emit({"playerid": 7, "mode": "play", "eventype": 0, "audiopath": RADIO})
    await hass.services.async_call("media_player", "select_source", {
        "entity_id": entity.entity_id, "source": "Spotify",
    }, blocking=True)
    assert calls[0] == "audio/7/serviceplay/spotify/synthetic-account/spotify%3Atrack%3Aoriginal/parentpath/spotify%3Aplaylist%3Aoriginal/0/noshuffle"


@pytest.mark.asyncio
@pytest.mark.parametrize("spotify", [False, True])
async def test_native_source_return_restores_sampled_position_only_after_exact_track_confirmation(hass, audio_setup, monkeypatch, spotify):
    entity, emit, calls = await install_sources(hass, audio_setup, monkeypatch, spotify=spotify)
    original = library_row()
    if spotify:
        original.update(audiopath="spotify:track:original", parent={"id": "spotify:playlist:original"}, sourceName="Synthetic owner")
    await emit(original)
    await emit({"playerid": 7, "mode": "play", "eventype": 0, "audiopath": RADIO})
    await hass.services.async_call("media_player", "select_source", {
        "entity_id": entity.entity_id, "source": "Spotify" if spotify else "Local Library",
    }, blocking=True)
    assert len(calls) == 2
    assert calls[1] == "audio/7/position/45.0"
    # Source return no longer waits for optional position feedback.
    await hass.async_block_till_done()
    assert entity._audio_metadata.get(7).position == 45


@pytest.mark.asyncio
async def test_selecting_already_playing_library_is_noop_not_another_seek(hass, audio_setup, monkeypatch):
    entity, emit, calls = await install_sources(hass, audio_setup, monkeypatch)
    await emit(library_row())
    await hass.services.async_call("media_player", "select_source", {
        "entity_id": entity.entity_id, "source": "Local Library",
    }, blocking=True)
    assert calls == []


@pytest.mark.asyncio
async def test_newer_native_same_track_seek_vetoes_delayed_position_restore(hass, audio_setup, monkeypatch):
    entity, emit, calls = await install_sources(hass, audio_setup, monkeypatch)
    restore = entity._audio_commands.async_seek
    async def newer_action(*args, **kwargs):
        await emit(library_row(time=150))
        return await restore(*args, **kwargs)
    monkeypatch.setattr(entity._audio_commands, "async_seek", newer_action)
    await emit(library_row())
    await emit({"playerid": 7, "mode": "play", "eventype": 0, "audiopath": RADIO})
    await hass.services.async_call("media_player", "select_source", {
        "entity_id": entity.entity_id, "source": "Local Library",
    }, blocking=True)
    expected_writes = 2
    assert len(calls) == expected_writes
    assert calls[-1] == "audio/7/position/45.0"
    await hass.async_block_till_done()
    expected_position = 45
    assert entity._audio_metadata.get(7).position == expected_position


@pytest.mark.asyncio
@pytest.mark.parametrize("player", range(1, 13))
async def test_shared_source_return_and_missing_cover_policy_isolated_across_twelve_rooms(hass, audio_setup, monkeypatch, player):
    import test_audioserver_ha as fixture_module
    import copy
    structure = copy.deepcopy(fixture_module.STRUCTURE)
    prototype = next(iter(structure["controls"].values()))
    structure["controls"] = {}
    for pid in range(1, 13):
        control = copy.deepcopy(prototype)
        control.update(uuidAction=f"synthetic-zone-{pid}", details={"playerid": pid}, states={"volume": f"volume-{pid}", "playState": f"play-{pid}"})
        structure["controls"][control["uuidAction"]] = control
    monkeypatch.setattr(fixture_module, "STRUCTURE", structure)
    entity, emit, calls = await install_sources(hass, audio_setup, monkeypatch, player=player)
    peers = [hass.data["media_player"].get_entity(zone_entity_id(hass, pid)) for pid in range(1, 13) if pid != player]
    for pid in range(1, 13):
        await emit(library_row(playerid=pid, audiopath=TRACK if pid == player else f"library:local:track:foreign-{pid}"))
    before = {peer.entity_id: peer._audio_metadata.get(peer._audio_player_id) for peer in peers}
    await emit({"playerid": player, "mode": "play", "eventype": 0, "audiopath": RADIO})
    await hass.services.async_call("media_player", "select_source", {
        "entity_id": entity.entity_id, "source": "Local Library",
    }, blocking=True)
    assert calls == [f"audio/{player}/library/play/library%3Alocal%3Atrack%3Afive/parentpath/library%3Alocal%3Afolder%3Aalbum/4", f"audio/{player}/position/45.0"]
    assert all(peer._audio_metadata.get(peer._audio_player_id) == before[peer.entity_id] for peer in peers)
    pictures = [await room.async_get_media_image() for room in [entity, *peers]]
    assert len(pictures) == 12 and all(picture == pictures[0] for picture in pictures)
    assert pictures[0][0].startswith(b"\x89PNG") and pictures[0][1] == "image/png"


@pytest.mark.asyncio
async def test_verified_room_session_return_does_not_depend_on_optional_recent_history(hass, audio_setup, monkeypatch):
    entity, emit, calls = await install_sources(hass, audio_setup, monkeypatch)
    await emit(library_row())
    await emit({"playerid": 7, "mode": "play", "eventype": 0, "audiopath": RADIO})
    monkeypatch.setattr(wire.AudioServerCommands, "async_recent_sources", AsyncMock(side_effect=wire.AudioCommandError("Synthetic optional history unavailable")))
    await hass.services.async_call("media_player", "select_source", {
        "entity_id": entity.entity_id, "source": "Local Library",
    }, blocking=True)
    assert len(calls) == 2 and ":track:" in unquote(calls[0])
