"""Actual existing Miniserver send await, no new socket or live connection."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from custom_components.loxone import media_player
from custom_components.loxone.audio_diagnostics import EntryAudioDiagnostics
from custom_components.loxone.pyloxone_api.connection import LoxoneConnection


@pytest.mark.parametrize("outcome", ["ok", "send_error", "cancelled"])
@pytest.mark.parametrize("encrypted", [False, True])
async def test_audio_miniserver_boundary_preserves_wire_and_errors(
    hass, outcome, encrypted
):
    wires = []
    for enabled in [False, True]:
        collector = EntryAudioDiagnostics(
            hass,
            SimpleNamespace(entry_id="synthetic-entry"),
            {
                "controls": {
                    "zone": {
                        "uuidAction": "synthetic-zone",
                        "type": "AudioZoneV2",
                        "details": {"playerid": 7},
                    }
                }
            },
        )
        collector.emitter.enabled = enabled
        c = LoxoneConnection.__new__(LoxoneConnection)
        c.audio_diagnostics = collector
        c._salt_lock = asyncio.Lock()
        c._new_salt_needed = Mock(return_value=False)
        c._salt = "synthetic-salt"
        c._aes_key = b"0" * 32
        c._iv = b"1" * 16
        sent = []

        async def send(command):
            sent.append(command)
            if enabled:
                assert any(r["stage"] == "send_attempt" for r in collector.queue._queue)
                assert not any(
                    r["stage"] == "send_completed" for r in collector.queue._queue
                )
            if outcome == "send_error":
                raise OSError("SECRET error text")
            if outcome == "cancelled":
                raise asyncio.CancelledError()

        c.connection = SimpleNamespace(
            protocol=SimpleNamespace(state=SimpleNamespace(name="OPEN")), send=send
        )
        if outcome == "ok":
            await c._send_text_command(
                "jdev/sps/io/synthetic-zone/volume/37", encrypted=encrypted
            )
        else:
            with pytest.raises(
                OSError if outcome == "send_error" else asyncio.CancelledError
            ):
                await c._send_text_command(
                    "jdev/sps/io/synthetic-zone/volume/37", encrypted=encrypted
                )
        wires.append(sent)
        rows = list(collector.queue._queue)
        if not enabled:
            assert rows == []
        else:
            assert [r["stage"] for r in rows] == [
                "send_attempt",
                {
                    "ok": "send_completed",
                    "send_error": "error",
                    "cancelled": "cancelled",
                }[outcome],
            ]
            assert all(
                r["transport"] == "miniserver" and r["volume"] == 37 for r in rows
            )
            assert rows[0]["room"] == collector.emitter.alias("room", "synthetic-zone")
            assert rows[0]["route"].endswith("/volume/37")
    assert wires[0] == wires[1]


async def test_auth_unrelated_controls_and_announcement_text_never_emit(hass):
    collector = EntryAudioDiagnostics(
        hass,
        SimpleNamespace(entry_id="synthetic-entry"),
        {
            "controls": {
                "zone": {
                    "uuidAction": "synthetic-zone",
                    "type": "AudioZoneV2",
                    "details": {"playerid": 7},
                }
            }
        },
    )
    collector.emitter.enabled = True
    c = LoxoneConnection.__new__(LoxoneConnection)
    c.audio_diagnostics = collector
    c.connection = SimpleNamespace(
        protocol=SimpleNamespace(state=SimpleNamespace(name="OPEN")), send=AsyncMock()
    )
    for command in [
        "jdev/sys/auth/SECRET",
        "jdev/sys/getkey2/SECRET",
        "jdev/sps/io/unrelated-door/close",
        "jdev/sps/io/synthetic-zone/tts/SECRET",
        "jdev/sps/io/synthetic-zone/volume/SECRET",
        "jdev/sps/ios/synthetic-zone/SECRET",
    ]:
        await c._send_text_command(command, encrypted=False)
    assert collector.queue.empty()
    assert c.connection.send.await_count == 6
