"""Offline transport tests; all payloads are synthetic, not device captures."""

from __future__ import annotations

# Assert/magic fixture IDs, private lifecycle checks and stub exceptions are intentional.
# ruff: noqa: S101, INP001, PLR2004, TRY003, EM101

import asyncio
import inspect
import json
from typing import TYPE_CHECKING, Any, Self
from unittest.mock import AsyncMock

import pytest
from websockets.asyncio.client import connect as real_connect

from pyloxone_audio import native as audioserver

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.mark.asyncio
async def test_connection_receives_metadata_without_sending_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    """A cancellable, receive-only connection clears metadata before closing."""
    assert hasattr(audioserver, "AudioServerListener")
    received = asyncio.Event()
    socket_closed = []
    connect_calls = []
    snapshots = []
    send = AsyncMock()

    class Socket:
        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_: object) -> None:
            socket_closed.append(True)

        def __aiter__(self) -> AsyncIterator[str]:
            return self.messages()

        async def messages(self) -> AsyncIterator[str]:
            yield "hello"
            yield json.dumps({"audio_event": [{"playerid": 7, "title": "Synthetic title"}]})
            await asyncio.Future()

    socket = Socket()
    socket.send = send

    def connect(uri: str, **kwargs: Any) -> Socket:
        connect_calls.append((uri, kwargs))
        return socket

    def on_update(updates: tuple[audioserver.AudioZoneMetadata, ...]) -> None:
        if updates:
            snapshots.append(listener.get(7))
            received.set()

    monkeypatch.setattr(audioserver, "connect", connect)
    listener = audioserver.AudioServerListener("audio.example.invalid", on_update)
    task = asyncio.create_task(listener.async_run())
    try:
        await asyncio.wait_for(received.wait(), timeout=1)
        assert snapshots[0].title == "Synthetic title"
        assert connect_calls[0][0] == "ws://audio.example.invalid:7091/"
        assert connect_calls[0][1]["subprotocols"] == ["remotecontrol"]
        assert connect_calls[0][1]["ping_interval"] is None
        assert connect_calls[0][1]["open_timeout"] == 10
        assert connect_calls[0][1]["close_timeout"] == 5
        assert connect_calls[0][1]["max_size"] == 1048576
        if "proxy" in inspect.signature(real_connect).parameters:
            assert connect_calls[0][1].get("proxy", True) is None
        else:
            assert "proxy" not in connect_calls[0][1]
        send.assert_not_called()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert socket_closed == [True]
    assert listener.get(7) is None


@pytest.mark.asyncio
async def test_reconnect_uses_capped_backoff_for_failures_and_eof(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both handshake failure and graceful EOF must retry, never busy-loop."""
    delays = []
    attempts = []

    class EmptySocket:
        async def __aenter__(self) -> Self:
            attempts.append(True)
            if len(attempts) % 2:
                raise OSError("synthetic unavailable server")
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def __aiter__(self) -> AsyncIterator[str]:
            if False:
                yield ""

    async def sleep(delay: float) -> None:
        delays.append(delay)
        if len(delays) == 7:
            raise asyncio.CancelledError

    monkeypatch.setattr(audioserver, "connect", lambda *_, **__: EmptySocket())
    monkeypatch.setattr(audioserver.asyncio, "sleep", sleep)
    listener = audioserver.AudioServerListener("audio.example.invalid", lambda _: None)
    with pytest.raises(asyncio.CancelledError):
        await listener.async_run()
    assert delays == [1, 2, 4, 8, 16, 30, 30]
    assert len(attempts) == 7


@pytest.mark.asyncio
async def test_receiving_valid_metadata_resets_reconnect_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real update, not merely an open handshake, resets the retry delay."""
    delays = []
    attempts = []

    class Socket:
        async def __aenter__(self) -> Self:
            attempts.append(True)
            if len(attempts) != 3:
                raise OSError("synthetic unavailable server")
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def __aiter__(self) -> AsyncIterator[str]:
            yield '{"audio_event":[{"playerid":7,"title":"Recovered"}]}'

    async def sleep(delay: float) -> None:
        assert listener.get(7) is None
        delays.append(delay)
        if len(delays) == 4:
            raise asyncio.CancelledError

    updates = []
    monkeypatch.setattr(audioserver, "connect", lambda *_, **__: Socket())
    monkeypatch.setattr(audioserver.asyncio, "sleep", sleep)
    listener = audioserver.AudioServerListener("audio.example.invalid", updates.append)
    with pytest.raises(asyncio.CancelledError):
        await listener.async_run()
    assert any(rows and rows[0].title == "Recovered" for rows in updates)
    assert delays == [1, 2, 1, 2]


@pytest.mark.parametrize(
    ("host", "uri"),
    [
        ("audio.example.invalid", "ws://audio.example.invalid:7091/"),
        ("192.0.2.10", "ws://192.0.2.10:7091/"),
        ("2001:db8::7", "ws://[2001:db8::7]:7091/"),
        ("[2001:db8::7]", "ws://[2001:db8::7]:7091/"),
    ],
)
def test_host_builds_an_explicit_audioserver_origin(host: str, uri: str) -> None:
    """Keep hostname, IPv4 and IPv6 origins explicit and deterministic."""
    assert hasattr(audioserver, "audioserver_uri")
    assert audioserver.audioserver_uri(host) == uri


@pytest.mark.parametrize(
    "host",
    ["", " ", "a/b", "a?b", "a#b", "user@audio", "ws://audio", "audio:7091", "a b", "[bad]", None],
)
def test_invalid_hosts_are_rejected_before_opening_a_connection(host: str) -> None:
    """Reject endpoints with paths, credentials, ports or invalid syntax."""
    with pytest.raises(ValueError, match="Audioserver host"):
        audioserver.AudioServerListener(host, lambda _: None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "malformed",
    ["[" * 10000 + "]" * 10000, '{"number":' + "9" * 5000 + "}"],
    ids=["too-deep", "integer-too-large"],
)
async def test_pathological_json_does_not_terminate_the_receiver(malformed: str) -> None:
    """Non-events and decoder integer limits cannot prevent later valid events."""
    updates = []

    async def messages() -> AsyncIterator[str]:
        yield malformed
        yield '{"audio_event":[{"playerid":7,"title":"Still receiving"}]}'

    receiver = audioserver.AudioEventReceiver(updates.append)
    await receiver.async_listen(messages())
    assert any(rows and rows[0].title == "Still receiving" for rows in updates)
