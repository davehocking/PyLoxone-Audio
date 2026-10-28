"""Actual HA source service -> existing native send -> sanitised events."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from pyloxone_audio.diagnostic_events import DiagnosticEmitter
from test_audioserver_ha import audio_setup
from test_native_source_return_ha import install_sources, library_row, RADIO
from custom_components.loxone.pyloxone_api import audioserver as wire


@pytest.mark.parametrize("spotify", [False, True])
@pytest.mark.parametrize("restriction", [32, 0])
async def test_source_service_reports_real_restore_decision_and_socket_boundary(
    hass, audio_setup, monkeypatch, spotify, restriction
):
    real_request = wire.AudioServerCommands._async_request
    entity, emit, _ = await install_sources(
        hass, audio_setup, monkeypatch, spotify=spotify
    )
    monkeypatch.setattr(wire.AudioServerCommands, "_async_request", real_request)
    rows = []
    diag = DiagnosticEmitter(b"synthetic-entry-key", rows.append)
    diag.enabled = True
    entity._audio_commands.diagnostics = diag
    entity._audio_commands._credentials = lambda: ("synthetic-user", "synthetic-token")
    original = library_row()
    if spotify:
        original.update(
            audiopath="spotify:track:original",
            parent={"id": "spotify:playlist:original"},
            sourceName="Synthetic owner",
        )
    await emit(original)
    await emit({"playerid": 7, "mode": "play", "eventype": 0, "audiopath": RADIO})
    socket = AsyncMock()
    writes = []

    async def send(command):
        writes.append(command)
        if "/position/" not in command:
            audio_setup.queues[0].put_nowait(
                json.dumps(
                    {"audio_event": [{**original, "time": 0, "pbr": restriction}]}
                )
            )

    async def recv():
        if "/position/" in writes[-1]:
            return '{"position_result":[{"position":45.0}]}'
        return json.dumps({"command": writes[-1]})

    socket.send.side_effect = send
    socket.recv.side_effect = recv
    context = AsyncMock()
    context.__aenter__.return_value = socket
    monkeypatch.setattr(wire, "connect", lambda *_a, **_kw: context)
    monkeypatch.setattr(wire.AudioServerCommands, "_authenticate", AsyncMock())
    await hass.services.async_call(
        "media_player",
        "select_source",
        {
            "entity_id": entity.entity_id,
            "source": "Spotify" if spotify else "Local Library",
        },
        blocking=True,
    )
    await hass.async_block_till_done()
    decisions = [r for r in rows if r["stage"] == "restore_decision"]
    assert decisions, "Actual optional-restore guard evaluations are missing"
    assert decisions[0]["saved_position"] == 45
    assert decisions[0]["phase"] == "initial"
    assert decisions[0]["reason"] == ("eligible" if restriction else "seek_unsupported")
    assert len(writes) == (2 if restriction else 1)
    if restriction:
        assert any(r["phase"] == "post_auth" for r in decisions)
        assert any(
            r["stage"] == "send_completed" and "/position/45.0" in r.get("route", "")
            for r in rows
        )
        assert any(r["stage"] == "restore_echo" for r in rows)
    assert entity._audio_metadata.get(7).audio_path == original["audiopath"]
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()
    assert "Synthetic owner" not in json.dumps(rows)


async def test_feedback_and_saved_session_are_observed_without_control(
    hass, audio_setup, monkeypatch
):
    entity, emit, calls = await install_sources(hass, audio_setup, monkeypatch)
    rows = []
    diag = DiagnosticEmitter(b"synthetic-entry-key", rows.append)
    diag.enabled = True
    entity._audio_commands.diagnostics = diag
    entity._audio_metadata.diagnostics = diag
    await emit(library_row())
    assert entity._radio_catalogue.source_session("Local Library").position == 45
    assert any(
        r["stage"] == "session_saved" and r["saved_position"] == 45 for r in rows
    )
    assert any(r["stage"] == "feedback" and r["position"] == 45 for r in rows)
    assert calls == []
    assert "Synthetic fifth track" not in json.dumps(rows)
