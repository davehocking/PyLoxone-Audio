"""Actual HA source actions with synthetic native and OAuth session boundaries."""

# ruff: noqa: S101, INP001, ANN001, ANN003, ANN202, D103, SLF001, F811, PLR0913, PLR2004, ARG001

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import ClientError

from homeassistant.config_entries import ConfigEntryState


from test_audioserver_ha import audio_setup, zone_entity_id  # noqa: F401 - imported pytest fixture
from test_spotify_continuity import CONFIG, TRACK, CONTEXT, Session, native
from custom_components.loxone.pyloxone_api import audioserver as wire


@pytest.mark.asyncio
async def test_actual_source_action_captures_before_radio_and_returns_without_native_context_start(
    hass, audio_setup, monkeypatch
):
    accounts = [{"cmd": "spotify", "id": "native-owner", "user": "native-user", "configerror": False}]
    monkeypatch.setattr(wire.AudioServerCommands, "async_service_accounts", AsyncMock(return_value=accounts))
    # Native recent history intentionally loses Spotify after radio selection.
    recent = [
        {"audiopath": "spotify@native-owner:playlist:" + "C" * 22, "type": 7, "title": "Synthetic context"},
        {"audiopath": "tunein:station:synthetic", "type": 2, "title": "Synthetic radio"},
    ]
    monkeypatch.setattr(
        wire.AudioServerCommands, "async_recent_sources", AsyncMock(side_effect=lambda _p: {"items": list(recent)})
    )
    entry = await audio_setup.setup(playback=True)
    await hass.config_entries.async_unload(entry.entry_id)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "audioserver_spotify_return": {"synthetic-zone-7": CONFIG}}
    )
    # Explicit fake authenticated HA entry; never creates OAuth or tokens.
    provider = SimpleNamespace(
        domain="spotify", unique_id="synthetic-owner", entry_id="synthetic-entry", state=ConfigEntryState.LOADED
    )
    original_get = hass.config_entries.async_get_entry
    monkeypatch.setattr(
        hass.config_entries, "async_get_entry", lambda key: provider if key == provider.entry_id else original_get(key)
    )
    snapshot = [native()]
    session = Session(snapshot)
    provider.runtime_data = SimpleNamespace(session=session)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    assert getattr(entity, "_spotify_return", None) is not None, "Configured HA room continuity is ignored"
    queue = audio_setup.queues[-1]
    row = {
        "playerid": 7,
        "audiopath": TRACK,
        "sourceName": "native-user",
        "parent": {"id": CONTEXT},
        "mode": "play",
        "time": 13.264,
        "duration": 180,
    }
    await queue.put(json.dumps({"audio_event": [row]}))
    await hass.async_block_till_done()
    native_starts = []

    async def select(player, service, path, *, is_current, on_send):
        assert is_current()
        assert entity._spotify_return.bookmark is None  # Departure never captures.
        on_send()
        native_starts.append((player, service, path))
        session.current["is_playing"] = False
        recent[:] = [recent[-1]]
        queue.put_nowait(json.dumps({"audio_event": [{"playerid": 7, "audiopath": path, "mode": "play"}]}))

    monkeypatch.setattr(entity._audio_commands, "async_play_radio_station", select)

    async def source(name):
        await hass.services.async_call(
            "media_player", "select_source", {"entity_id": entity.entity_id, "source": name}, blocking=True
        )
        await hass.async_block_till_done()

    await source("TuneIn")
    assert "Spotify" in entity.source_list

    async def publish():
        queue.put_nowait(json.dumps({"audio_event": [{**row, "time": 14.081}]}))
        await hass.async_block_till_done()

    async def native_resume(player,account,*,is_current,on_send):
        assert (player,account)==(7,'native-owner') and is_current()
        on_send()
        await publish()
    handoff=AsyncMock(side_effect=native_resume)
    monkeypatch.setattr(entity._audio_commands,'async_spotify_handoff',handoff)
    native_play = AsyncMock()
    monkeypatch.setattr(entity._audio_commands, "async_play_catalogue", native_play)
    await source("Spotify")
    await source("Spotify")  # active source must not rewind
    assert native_starts == [(7, "world", "tunein:station:synthetic")]
    native_play.assert_not_awaited()
    assert all(method=='GET' and not url.endswith('/queue') for method,url,_ in session.calls)
    handoff.assert_awaited_once()
    assert not entity._audio_commands.source_fences
    await hass.config_entries.async_unload(entry.entry_id)
    assert entity._spotify_return.closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid",
    [
        "absent",
        "invalid-mapping",
        "unloaded",
        "disabled",
        "missing-library",
        "wrong-user",
        "pre-send-outage",
        "outer-list",
        "outer-string",
        "outer-null",
    ],
)
async def test_unavailable_optional_spotify_quietly_preserves_native_sources(
    hass, audio_setup, monkeypatch, caplog, invalid
):
    monkeypatch.setattr(
        wire.AudioServerCommands,
        "async_service_accounts",
        AsyncMock(return_value=[{"cmd": "spotify", "id": "native-owner", "user": "native-user", "configerror": False}]),
    )
    monkeypatch.setattr(
        wire.AudioServerCommands,
        "async_recent_sources",
        AsyncMock(
            return_value={
                "items": [
                    {"audiopath": "spotify@native-owner:playlist:" + "C" * 22, "type": 7},
                    {"audiopath": "tunein:station:synthetic", "type": 2},
                ]
            }
        ),
    )
    entry = await audio_setup.setup(playback=True)
    await hass.config_entries.async_unload(entry.entry_id)
    binding = {**CONFIG, "extra": "rejected"} if invalid == "invalid-mapping" else CONFIG
    session = Session([native()])
    provider = SimpleNamespace(
        domain="spotify",
        unique_id="wrong-user" if invalid == "wrong-user" else "synthetic-owner",
        entry_id="synthetic-entry",
        state=ConfigEntryState.NOT_LOADED if invalid == "unloaded" else ConfigEntryState.LOADED,
        disabled_by="user" if invalid == "disabled" else None,
        runtime_data=None if invalid == "missing-library" else SimpleNamespace(session=session),
    )
    if invalid not in ("absent", "invalid-mapping"):
        original_get = hass.config_entries.async_get_entry
        monkeypatch.setattr(
            hass.config_entries,
            "async_get_entry",
            lambda key: provider if key == provider.entry_id else original_get(key),
        )
    if invalid == "pre-send-outage":

        async def unavailable(_url):
            msg = "synthetic pre-dispatch outage"
            raise ClientError(msg)

        session.on_read = unavailable
    option = {"outer-list": [], "outer-string": "invalid", "outer-null": None}.get(
        invalid, {"synthetic-zone-7": binding}
    )
    hass.config_entries.async_update_entry(entry, options={**entry.options, "audioserver_spotify_return": option})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    queue = audio_setup.queues[-1]
    await queue.put(
        json.dumps(
            {
                "audio_event": [
                    {
                        "playerid": 7,
                        "audiopath": TRACK,
                        "sourceName": "native-user",
                        "parent": {"id": CONTEXT},
                        "mode": "play",
                        "time": 13.264,
                        "duration": 180,
                    }
                ]
            }
        )
    )
    await hass.async_block_till_done()
    writes = []

    async def radio(player, service, path, *, is_current, on_send):
        assert is_current()
        on_send()
        writes.append((player, service, path))
        queue.put_nowait(json.dumps({"audio_event": [{"playerid": player, "audiopath": path, "mode": "play"}]}))

    monkeypatch.setattr(entity._audio_commands, "async_play_radio_station", radio)

    async def select_native(player, service, account, path, *, is_current, on_send, **_kwargs):
        assert is_current()
        on_send()
        queue.put_nowait(
            json.dumps(
                {
                    "audio_event": [
                        {
                            "playerid": player,
                            "audiopath": TRACK,
                            "sourceName": "native-user",
                            "parent": {"id": CONTEXT},
                            "mode": "play",
                        }
                    ]
                }
            )
        )

    native_start = AsyncMock(side_effect=select_native)
    monkeypatch.setattr(entity._audio_commands, "async_play_catalogue", native_start)
    await hass.services.async_call(
        "media_player", "select_source", {"entity_id": entity.entity_id, "source": "TuneIn"}, blocking=True
    )
    assert writes == [(7, "world", "tunein:station:synthetic")]
    await entity.async_select_source("Spotify")
    native_start.assert_awaited_once()
    assert all(method == "GET" for method, _, _ in session.calls)
    if invalid != "pre-send-outage":
        assert not session.calls
    assert not [r for r in caplog.records if r.levelno >= 30 and "Spotify" in r.message]
    await hass.config_entries.async_unload(entry.entry_id)
