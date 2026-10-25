"""Synthetic seek contract tests: no household data or network."""

# ruff: noqa: S101, INP001, SLF001
import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from pyloxone_audio import native as wire


@pytest.mark.parametrize("value", [None, True, False, "12", -1, float("nan"), float("inf"), 10**999])
@pytest.mark.asyncio
async def test_invalid_seek_never_connects(monkeypatch: pytest.MonkeyPatch, value: object) -> None:
    """Bad offsets are rejected before authentication or connection."""
    connect = AsyncMock()
    monkeypatch.setattr(wire, "connect", connect)
    owner = wire.AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "synthetic"))
    with pytest.raises(ValueError, match="exact player and nonnegative seconds"):
        await owner.async_seek(7, value)
    connect.assert_not_called()


@pytest.mark.parametrize("position", [0, 0.125, 180])
@pytest.mark.asyncio
async def test_seek_accepts_only_numeric_reply_and_sends_once(monkeypatch: pytest.MonkeyPatch, position: float) -> None:
    """Numeric ACKs preserve zero and fractions without extra commands."""
    socket = AsyncMock()
    socket.recv.side_effect = [
        json.dumps({"audio_event": []}),
        json.dumps({"position_result": [{"position": position}]}),
    ]
    context = AsyncMock()
    context.__aenter__.return_value = socket
    monkeypatch.setattr(wire, "connect", lambda *_a, **_kw: context)
    monkeypatch.setattr(wire.AudioServerCommands, "_authenticate", AsyncMock())
    owner = wire.AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "synthetic"))
    assert await owner.async_seek(7, position) == position
    assert socket.send.await_count == 1
    assert socket.send.await_args.args[0] == f"audio/7/position/{float(position)}"
    assert owner._socket is None


@pytest.mark.parametrize(
    "reply",
    [
        None,
        True,
        False,
        [],
        {},
        [{}],
        [{"position": True}],
        [{"position": "1"}],
        [{"position": -1}],
        [{"position": float("nan")}],
        [{"position": float("inf")}],
        [{"position": 10**999}],
    ],
)
@pytest.mark.asyncio
async def test_seek_rejects_malformed_numeric_ack_without_retry(monkeypatch: pytest.MonkeyPatch, reply: object) -> None:
    """Malformed replies never become accepted offsets or a second command."""
    socket = AsyncMock()
    socket.recv.return_value = json.dumps({"position_result": reply})
    context = AsyncMock()
    context.__aenter__.return_value = socket
    monkeypatch.setattr(wire, "connect", lambda *_a, **_kw: context)
    monkeypatch.setattr(wire.AudioServerCommands, "_authenticate", AsyncMock())
    owner = wire.AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "synthetic"))
    with pytest.raises(wire.AudioCommandError):
        await owner.async_seek(7, 1)
    assert socket.send.await_count == 1


@pytest.mark.parametrize(
    ("pbr", "expected"),
    [(32, 32), (16127, 16127), (0, 0), (None, None), (True, None), (-1, None), ("32", None), (32.0, None)],
)
def test_pbr_is_exact_nonnegative_integer(pbr: object, expected: int | None) -> None:
    """Only exact nonnegative integer restriction bits reach the entity."""
    row = wire.parse_audio_events(
        {
            "audio_event": [
                {
                    "playerid": 7,
                    "mode": "play",
                    "audiopath": "spotify:track:synthetic",
                    "time": 12,
                    "duration": 180,
                    "pbr": pbr,
                }
            ]
        }
    )[0]
    assert row.playback_restrictions == expected


@pytest.mark.asyncio
async def test_seek_unrelated_flood_obeys_whole_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unrelated events cannot extend the shared operation deadline."""
    socket = AsyncMock()
    socket.recv.return_value = '{"audio_event": []}'
    context = AsyncMock()
    context.__aenter__.return_value = socket
    monkeypatch.setattr(wire, "connect", lambda *_a, **_kw: context)
    monkeypatch.setattr(wire.AudioServerCommands, "_authenticate", AsyncMock())
    owner = wire.AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "synthetic"), timeout=0.02)
    with pytest.raises(wire.AudioCommandError):
        await asyncio.wait_for(owner.async_seek(7, 1), timeout=1)
    assert socket.send.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["queued", "authentication"])
async def test_stale_seek_is_rejected_immediately_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    """No player command reaches a changed track after awaited setup."""
    socket = AsyncMock()
    context = AsyncMock()
    context.__aenter__.return_value = socket
    monkeypatch.setattr(wire, "connect", lambda *_a, **_kw: context)
    valid = True

    async def authenticate(*_: object) -> None:
        nonlocal valid
        if phase == "authentication":
            valid = False

    monkeypatch.setattr(wire.AudioServerCommands, "_authenticate", authenticate)
    owner = wire.AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "synthetic"))
    if phase == "queued":
        await owner._lock.acquire()
    task = asyncio.create_task(owner.async_seek(7, 10, is_current=lambda: valid))
    if phase == "queued":
        await asyncio.sleep(0)
        valid = False
        owner._lock.release()
    with pytest.raises(wire.AudioCommandError):
        await task
    socket.send.assert_not_awaited()
    assert owner._socket is None
