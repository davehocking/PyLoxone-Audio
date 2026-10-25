"""Reviewer regressions: actual HA boundary, synthetic rooms/accounts only."""
# ruff: noqa: S101, INP001, ANN001, D103, SLF001, PLC0415
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from test_audioserver_ha import audio_setup  # noqa: F401
from test_native_source_return_ha import install_sources, library_row, RADIO
from custom_components.loxone.pyloxone_api import audioserver as wire
from custom_components.loxone import audio_sources


@pytest.mark.asyncio
@pytest.mark.parametrize("spotify", [False, True])
@pytest.mark.parametrize("history_fails", [False, True])
async def test_retained_session_without_source_choices_returns_independent_of_history(hass, audio_setup, monkeypatch, spotify, history_fails):
    entity, emit, calls = await install_sources(hass, audio_setup, monkeypatch, spotify=spotify)
    row = library_row()
    if spotify:
        row.update(audiopath="spotify:track:original", parent={"id": "spotify:playlist:original"}, sourceName="Synthetic owner")
    await emit(row)
    await emit({"playerid": 7, "mode": "play", "eventype": 0, "audiopath": RADIO})
    entity._radio_catalogue.source_choices.clear()
    history = AsyncMock(side_effect=wire.AudioCommandError("Synthetic unavailable")) if history_fails else AsyncMock(return_value={"items": [], "ts": 2})
    monkeypatch.setattr(wire.AudioServerCommands, "async_recent_sources", history)
    await hass.services.async_call("media_player", "select_source", {
        "entity_id": entity.entity_id, "source": "Spotify" if spotify else "Local Library",
    }, blocking=True)
    assert len(calls) == 2
    assert calls[-1] == "audio/7/position/45.0"


@pytest.mark.asyncio
@pytest.mark.parametrize("loss", ["capability", "progress"])
async def test_return_seek_rechecks_native_capability_and_progress_at_transport_dispatch(hass, audio_setup, monkeypatch, loss):
    entity, emit, calls = await install_sources(hass, audio_setup, monkeypatch)
    request = wire.AudioServerCommands._async_request

    async def delayed_auth(client, command, key, **kwargs):
        if "/position/" in command:
            await emit(library_row(time=None if loss == "progress" else 0, pbr=0 if loss == "capability" else 32))
        return await request(client, command, key, **kwargs)

    monkeypatch.setattr(wire.AudioServerCommands, "_async_request", delayed_auth)
    await emit(library_row())
    await emit({"playerid": 7, "mode": "play", "eventype": 0, "audiopath": RADIO})
    # Capability still gates the optional seek; progress samples do not gate source success.
    await hass.services.async_call("media_player", "select_source", {
        "entity_id": entity.entity_id, "source": "Local Library",
    }, blocking=True)
    assert len(calls) == (1 if loss == "capability" else 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["source_settlement", "seek_authentication"])
@pytest.mark.parametrize("new_position", [9.5, 10.5, 11.0])
async def test_newer_small_or_rewind_seek_never_becomes_return_baseline(hass, audio_setup, monkeypatch, phase, new_position):
    entity, emit, calls = await install_sources(hass, audio_setup, monkeypatch)
    request = wire.AudioServerCommands._async_request

    async def delayed(client, command, key, **kwargs):
        if "/library/play/" in command:
            assert kwargs["is_current"]()
            kwargs["on_send"]()
            calls.append(command)
            await emit(library_row(time=10))
            if phase == "source_settlement":
                await emit(library_row(time=new_position))
            return None
        if "/position/" in command and phase == "seek_authentication":
            await emit(library_row(time=new_position))
        return await request(client, command, key, **kwargs)

    monkeypatch.setattr(wire.AudioServerCommands, "_async_request", delayed)
    await emit(library_row())
    await emit({"playerid": 7, "mode": "play", "eventype": 0, "audiopath": RADIO})
    await hass.services.async_call("media_player", "select_source", {
        "entity_id": entity.entity_id, "source": "Local Library",
    }, blocking=True)
    expected_writes = 2
    assert len(calls) == expected_writes
    assert calls[-1] == "audio/7/position/45.0"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [None, {"type": 2, "id": "library:local:track:other", "audiopath": "library:local:track:five", "name": "Synthetic"}, {"type": 7, "id": "library:local:track:five", "name": "Synthetic"}, {"type": 2, "id": "library:local:track:five", "unplayable": True, "name": "Synthetic"}, {"type": 2, "id": "tunein:track:other", "name": "Synthetic"}])
async def test_cursor_rejects_malformed_nontrack_unplayable_and_conflicting_rows(hass, audio_setup, monkeypatch, bad):
    entity, emit, calls = await install_sources(hass, audio_setup, monkeypatch)
    folder = wire.AudioServerCommands.async_media_folder

    async def corrupt(client, service, account, path, offset):
        result = await folder(client, service, account, path, offset)
        if path == "library:local:folder:album":
            result[0]["items"][0] = bad
        return result

    monkeypatch.setattr(wire.AudioServerCommands, "async_media_folder", corrupt)
    await emit(library_row())
    await emit({"playerid": 7, "mode": "play", "eventype": 0, "audiopath": RADIO})
    await hass.services.async_call("media_player", "select_source", {
        "entity_id": entity.entity_id, "source": "Local Library",
    }, blocking=True)
    # Invalid context rows cannot be used for parent/cursor reconstruction;
    # Dave explicitly permits trying the SAME known-good track without it.
    assert calls[0] == 'audio/7/library/play/library%3Alocal%3Atrack%3Afive'
    assert all('/parentpath/' not in command for command in calls)


@pytest.mark.asyncio
async def test_same_total_parent_reordering_between_complete_reads_sends_no_playback(hass, audio_setup, monkeypatch):
    entity, emit, calls = await install_sources(hass, audio_setup, monkeypatch)
    folder = wire.AudioServerCommands.async_media_folder
    reads = 0

    async def reorder(client, service, account, path, offset):
        nonlocal reads
        result = await folder(client, service, account, path, offset)
        if path == "library:local:folder:album":
            reads += 1
            if reads > 1:
                result[0]["items"].reverse()
        return result

    monkeypatch.setattr(wire.AudioServerCommands, "async_media_folder", reorder)
    await emit(library_row())
    await emit({"playerid": 7, "mode": "play", "eventype": 0, "audiopath": RADIO})
    await hass.services.async_call("media_player", "select_source", {
        "entity_id": entity.entity_id, "source": "Local Library",
    }, blocking=True)
    assert calls[0] == 'audio/7/library/play/library%3Alocal%3Atrack%3Afive'
    assert all('/parentpath/' not in command for command in calls)
    assert reads == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("loss", ["progress", "capability", "account_user"])
async def test_newer_unqualified_spotify_state_cannot_replay_old_sampled_track(hass, audio_setup, monkeypatch, loss):
    entity, emit, calls = await install_sources(hass, audio_setup, monkeypatch, spotify=True)
    spotify = dict(audiopath="spotify:track:original", parent={"id": "spotify:playlist:original"}, sourceName="Synthetic owner")
    await emit(library_row(**spotify))
    spotify["audiopath"] = "spotify:track:newer"
    if loss == "progress":
        spotify["time"] = None
    elif loss == "capability":
        spotify["pbr"] = 0
    else:
        spotify["sourceName"] = "Unknown replacement user"
    await emit(library_row(**spotify))
    await emit({"playerid": 7, "mode": "play", "eventype": 0, "audiopath": RADIO})
    if loss == 'account_user':
        # Unknown account cannot replace the exact known account's success.
        await hass.services.async_call("media_player", "select_source", {
            "entity_id": entity.entity_id, "source": "Spotify",
        }, blocking=True)
        assert 'spotify%3Atrack%3Aoriginal' in calls[0]
    else:
        # Real playing newer item is last-good even without optional timing.
        # The provider may report ORIGINAL after we request NEWER; source is confirmed,
        # with no automatic fallback command or seek of a different item.
        await hass.services.async_call("media_player", "select_source", {
            "entity_id": entity.entity_id, "source": "Spotify",
        }, blocking=True)
        assert len(calls) == 1 and calls[0].endswith('spotify%3Atrack%3Anewer')
    assert all('/parentpath/' not in command for command in calls) if loss != 'account_user' else True


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_inventory", [False, True])
async def test_replaced_account_with_same_presentation_user_cannot_adopt_old_native_session(hass, audio_setup, monkeypatch, missing_inventory):
    entity, emit, calls = await install_sources(hass, audio_setup, monkeypatch, spotify=True)
    await emit(library_row(audiopath="spotify:track:original", parent={"id": "spotify:playlist:original"}, sourceName="Synthetic owner"))
    await emit({"playerid": 7, "mode": "play", "eventype": 0, "audiopath": RADIO})
    if missing_inventory:
        monkeypatch.setattr(wire.AudioServerCommands, "async_service_accounts", AsyncMock(return_value=[]))
        await entity._radio_catalogue.async_refresh_sources()
    monkeypatch.setattr(wire.AudioServerCommands, "async_service_accounts", AsyncMock(return_value=[{
        "cmd": "spotify", "id": "replacement-account", "user": "Synthetic owner", "name": "Synthetic", "configerror": False,
    }]))
    folder = wire.AudioServerCommands.async_media_folder
    async def new_account_rows(client, service, account, path, offset):
        rows = await folder(client, service, account, path, offset)
        if service == "spotify":
            for page in rows:
                for item in page["items"]:
                    item["id"] = item["id"].replace("synthetic-account", "replacement-account")
        return rows
    monkeypatch.setattr(wire.AudioServerCommands, "async_media_folder", new_account_rows)
    monkeypatch.setattr(wire.AudioServerCommands, "async_recent_sources", AsyncMock(return_value={
        "items": [{"type": 7, "audiopath": "spotify@replacement-account:playlist:original", "title": "Replacement playlist"}], "ts": 2,
    }))
    await entity._radio_catalogue.async_refresh_sources()
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("media_player", "select_source", {
            "entity_id": entity.entity_id, "source": "Spotify",
        }, blocking=True)
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("spotify", [False, True])
async def test_stream_loss_does_not_turn_captured_session_into_history_restart(hass, audio_setup, monkeypatch, spotify):
    entity, emit, calls = await install_sources(hass, audio_setup, monkeypatch, spotify=spotify)
    row = library_row()
    if spotify:
        row.update(audiopath="spotify:track:original", parent={"id": "spotify:playlist:original"}, sourceName="Synthetic owner")
    await emit(row)
    entity._audio_metadata._client._receiver._reset()
    await hass.async_block_till_done()
    await emit({"playerid": 7, "mode": "play", "eventype": 0, "audiopath": RADIO})
    await hass.services.async_call("media_player", "select_source", {
        "entity_id": entity.entity_id, "source": "Spotify" if spotify else "Local Library",
    }, blocking=True)
    expected='spotify%3Atrack%3Aoriginal' if spotify else 'library%3Alocal%3Atrack%3Afive'
    assert expected in calls[0] and len(calls)==2
