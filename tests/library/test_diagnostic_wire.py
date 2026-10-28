"""Pair the actual existing send await with enabled/disabled observation."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from pyloxone_audio import native
from pyloxone_audio.diagnostic_events import DiagnosticEmitter


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome", ["ok", "send_error", "timeout", "cancelled", "stale", "bad_echo"]
)
async def test_actual_send_evidence_preserves_commands_and_failure_semantics(
    monkeypatch, outcome
):
    results = []
    for enabled in (False, True):
        rows = []
        diag = DiagnosticEmitter(b"synthetic-key", rows.append)
        diag.enabled = enabled
        socket = AsyncMock()
        socket.recv.return_value = json.dumps(
            {"position_result": [{"position": 66.285}]}
        )
        if outcome == "send_error":
            socket.send.side_effect = OSError("SECRET")
        elif outcome == "cancelled":
            socket.send.side_effect = asyncio.CancelledError()
        elif outcome == "timeout":

            async def forever():
                await asyncio.Event().wait()

            socket.recv.side_effect = forever
        elif outcome == "bad_echo":
            socket.recv.return_value = json.dumps(
                {"position_result": [{"position": "SECRET"}]}
            )
        context = AsyncMock()
        context.__aenter__.return_value = socket
        monkeypatch.setattr(native, "connect", lambda *_a, **_kw: context)
        monkeypatch.setattr(native.AudioServerCommands, "_authenticate", AsyncMock())
        owner = native.AudioServerCommands(
            "audio.example.invalid",
            lambda: ("SECRET-user", "SECRET-token"),
            timeout=0.01,
        )
        # Assignment intentionally preserves the old constructor/owning path for RED.
        owner.diagnostics = diag
        error = None
        try:
            await owner.async_seek(27, 66.285, is_current=lambda: outcome != "stale")
        except (native.AudioCommandError, asyncio.CancelledError) as exc:
            error = type(exc).__name__
        results.append(([c.args for c in socket.send.await_args_list], error))
        stages = [r["stage"] for r in rows]
        if not enabled:
            assert rows == []
            continue
        assert "SECRET" not in json.dumps(rows)
        assert stages[0] == "request"
        assert "authenticated" in stages
        if outcome == "stale":
            assert "send_attempt" not in stages
            assert stages[-1] == "error"
        else:
            assert "send_attempt" in stages
            assert ("send_completed" in stages) == (
                outcome not in ("send_error", "cancelled")
            )
        if outcome == "ok":
            assert "reply" in stages
            assert stages[-1] == "restore_echo"
            assert rows[-1]["echo_position"] == 66.285
        elif outcome == "timeout":
            assert stages[-1] == "timeout"
        elif outcome == "cancelled":
            assert stages[-1] == "cancelled"
        elif outcome == "bad_echo":
            assert stages[-1] == "error"
        assert len({r["request_id"] for r in rows if "request_id" in r}) == 1
    assert results[0] == results[1]


@pytest.mark.asyncio
async def test_broken_observer_does_not_change_native_send(monkeypatch):
    class Broken:
        enabled = True

        def emit(self, *args, **kwargs):
            raise RuntimeError("SECRET")

    socket = AsyncMock()
    socket.recv.return_value = '{"position_result":[{"position":1}]}'
    context = AsyncMock()
    context.__aenter__.return_value = socket
    monkeypatch.setattr(native, "connect", lambda *_a, **_kw: context)
    monkeypatch.setattr(native.AudioServerCommands, "_authenticate", AsyncMock())
    owner = native.AudioServerCommands("audio.example.invalid", lambda: ("u", "t"))
    owner.diagnostics = Broken()
    assert await owner.async_seek(7, 1) == 1
    assert socket.send.await_count == 1
