"""Synthetic uploaded-WAV announcement protocol; no household data."""

# Synthetic HTTP fixtures have compact fake transport signatures.
# ruff: noqa: S101, INP001, ANN001, ANN202
from unittest.mock import AsyncMock
import io
import os
from pathlib import Path
import tempfile
import wave
from contextlib import asynccontextmanager
from types import SimpleNamespace

from aiohttp import ClientSession, UnixConnector, web
import pytest
import pytest_socket
from pyloxone_audio import native as wire


def synthetic_wav():
    """Generate short PCM silence without any household recording."""
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(bytes(4800))
    return output.getvalue()


@pytest.mark.asyncio
async def test_upload_response_cannot_expand_before_bounded_read():
    """Reject compressed native responses without automatic decompression."""
    read = AsyncMock()

    @asynccontextmanager
    async def put(_url, **kwargs: object):
        assert kwargs.get("auto_decompress") is False
        yield SimpleNamespace(status=200, headers={"Content-Encoding": "gzip"}, content=SimpleNamespace(read=read))

    owner = wire.AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "synthetic"))
    with pytest.raises(wire.AudioCommandError):
        await owner.async_upload_announcement(
            SimpleNamespace(put=put), "pyloxone-0123456789abcdef.wav", synthetic_wav()
        )
    read.assert_not_awaited()


@pytest.mark.asyncio
async def test_uploaded_announcement_targets_one_player_with_explicit_volume(monkeypatch):
    """Native grouped upload route is constrained to one exact target."""
    request = AsyncMock(return_value=True)
    owner = wire.AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "synthetic"))
    monkeypatch.setattr(owner, "_async_request", request)
    await owner.async_announce(7, "pyloxone-0123456789abcdef.wav", 10)
    request.assert_awaited_once_with(
        "audio/grouped/playuploadedfile/pyloxone-0123456789abcdef.wav/7#10",
        "playuploadedfile_result",
        is_current=None,
        on_send=None,
    )


@pytest.mark.asyncio
async def test_upload_uses_exact_native_put_route_and_wav_bytes():
    """Exercise the real HTTP client/server over AF_UNIX, with no network."""
    pytest_socket.socket_allow_hosts([], allow_unix_socket=True)
    received = []
    data = synthetic_wav()

    async def handler(request):
        received.append((request.method, request.path, request.content_type, await request.read()))
        return web.Response(status=200, text="OK")

    app = web.Application()
    app.router.add_put("/audio/cfg/upload/audioupload/add/{filename}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        with tempfile.TemporaryDirectory(prefix="upload-", dir=os.environ.get("TMPDIR")) as directory:
            path = str(Path(directory) / "http.sock")
            await web.UnixSite(runner, path).start()
            async with ClientSession(connector=UnixConnector(path=path)) as session:
                owner = wire.AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "synthetic"))
                await owner.async_upload_announcement(session, "pyloxone-0123456789abcdef.wav", data)
    finally:
        await runner.cleanup()
    assert received == [("PUT", "/audio/cfg/upload/audioupload/add/pyloxone-0123456789abcdef.wav", "audio/wav", data)]
