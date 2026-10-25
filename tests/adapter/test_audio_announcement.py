"""Offline HA announcement preparation; synthetic audio only."""

# Synthetic fixtures use compact fake transport signatures and literal audio dimensions.
# ruff: noqa: S101, INP001, ANN001, ANN002, ANN003, ANN202, PLR2004, ARG001, ARG002, D103, PLC0415, PT018
from custom_components.loxone import audio_announcement as module
import io
import wave

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components import media_player, media_source
from homeassistant.helpers import aiohttp_client


def source_wav(*, rate=16000, seconds=0.2):
    """Generate synthetic silence; no recorded household content."""
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(bytes(int(rate * seconds) * 2))
    return output.getvalue()


@pytest.mark.asyncio
async def test_convert_preserves_audio_duration_and_emits_seekable_native_wav(hass):
    """Exercise the actual local FFmpeg converter and WAV framing."""
    data, duration = await module.async_announcement_wav(hass, source_wav())
    with wave.open(io.BytesIO(data)) as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 24000)
        assert wav.getnframes() == 4800
        assert len(wav.readframes(4800)) == 9600
    assert duration == pytest.approx(0.2)
    assert int.from_bytes(data[4:8], "little") == len(data) - 8


@pytest.mark.asyncio
async def test_prepare_resolves_exact_tts_media_id_without_changing_provider_options(hass, monkeypatch):
    """Preserve the provider/voice media ID through HA's resolver."""
    media_id = "media-source://tts/tts.synthetic?message=testing&voice=synthetic-voice&language=en"
    resolved = AsyncMock(return_value=SimpleNamespace(url="/api/tts_proxy/synthetic.wav", mime_type="audio/wav"))
    signed = MagicMock(return_value="https://ha.example.invalid/stream.wav?authSig=synthetic")
    received = []

    async def chunks(size):
        received.append(size)
        yield source_wav()

    @asynccontextmanager
    async def response(*args, **kwargs):
        received.append((args, kwargs))
        yield SimpleNamespace(status=200, headers={}, content=SimpleNamespace(iter_chunked=chunks))

    session = SimpleNamespace(get=response)
    monkeypatch.setattr(media_source, "async_resolve_media", resolved)
    monkeypatch.setattr(media_player, "async_process_play_media_url", signed)
    monkeypatch.setattr(aiohttp_client, "async_get_clientsession", lambda _: session)
    data, duration = await module.async_prepare_announcement(hass, media_id, "media_player.synthetic_audio")
    resolved.assert_awaited_once_with(hass, media_id, "media_player.synthetic_audio")
    signed.assert_called_once_with(hass, "/api/tts_proxy/synthetic.wav")
    assert received[0] == (
        ("https://ha.example.invalid/stream.wav?authSig=synthetic",),
        {
            "allow_redirects": True,
            "max_redirects": 3,
            "auto_decompress": False,
            "headers": {"Accept-Encoding": "identity"},
        },
    )
    assert duration == pytest.approx(0.2)
    assert data.startswith(b"RIFF")


@pytest.mark.asyncio
async def test_compressed_download_is_rejected_before_body_read(hass, monkeypatch):
    chunks = AsyncMock()

    @asynccontextmanager
    async def response(*args, **kwargs):
        assert kwargs.get("auto_decompress") is False, "HTTP expansion is unbounded before chunk limit"
        yield SimpleNamespace(
            status=200, headers={"Content-Encoding": "gzip"}, content=SimpleNamespace(iter_chunked=chunks)
        )

    monkeypatch.setattr(media_player, "async_process_play_media_url", lambda _, url: url)
    monkeypatch.setattr(aiohttp_client, "async_get_clientsession", lambda _: SimpleNamespace(get=response))
    with pytest.raises(ValueError, match="unavailable"):
        await module.async_prepare_announcement(hass, "https://ha.example.invalid/audio", "media_player.synthetic")
    chunks.assert_not_called()


@pytest.mark.asyncio
async def test_decoder_is_resource_limited_and_killed_on_cancellation(hass, monkeypatch):
    import asyncio

    entered = asyncio.Event()

    class Process:
        returncode = None

        async def communicate(self, data):
            entered.set()
            await asyncio.Future()

        def kill(self):
            self.returncode = -9

        async def wait(self):
            return self.returncode

    process = Process()
    calls = []

    async def spawn(*args, **kwargs):
        calls.append(args)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(module.async_announcement_wav(hass, source_wav()))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.returncode == -9
    args = calls[0]
    assert args[1] == "-c" and "RLIMIT_AS" in args[2] and "RLIMIT_CPU" in args[2]
    assert args[args.index("-threads") + 1] == "1"
    assert "-max_alloc" in args
