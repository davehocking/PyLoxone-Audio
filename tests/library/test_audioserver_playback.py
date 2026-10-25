"""Synthetic command tests; no household credentials, media or network access."""

# Assertions, fixture IDs and private lifecycle access are intentional.
# ruff: noqa: S101, INP001, PLR2004
from __future__ import annotations
import asyncio
import base64
import json
from urllib.parse import unquote
from typing import Any, Self
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import unpad
import pytest
from pyloxone_audio import native as audioserver


@pytest.mark.parametrize("action", ["play", "pause"])
def test_resume_commands_target_audio_player_not_miniserver_room(action: str) -> None:
    """The wire route differs even though the command verbs look identical."""
    assert audioserver.audio_control_command(13, action) == (f"audio/13/{action}", f"{action}_result")


@pytest.mark.parametrize("player_id", [None, False, True, 0, -1, 1.5, "13/play", ""])
def test_invalid_targets_cannot_become_wire_commands(player_id: object) -> None:
    """Invalid targets cannot become wire commands."""
    with pytest.raises(ValueError, match="exact player ID"):
        audioserver.audio_control_command(player_id, "play")


@pytest.mark.parametrize("action", ["resume", "play/1", "stop", "tts", "", None])
def test_only_reviewed_play_pause_verbs_are_accepted(action: str) -> None:
    """Only reviewed play pause verbs are accepted."""
    with pytest.raises(ValueError, match="exact player ID"):
        audioserver.audio_control_command(13, action)


@pytest.fixture(scope="module")
def rsa_key() -> RSA.RsaKey:
    """Rsa key."""
    return RSA.generate(2048)


class SyntheticAudioSocket:
    """Decrypt the client handshake independently and emulate reviewed replies."""

    def __init__(self, key: RSA.RsaKey) -> None:
        """Init."""
        self.key = key
        self.public_key = key.publickey().export_key().decode()
        self.queue = asyncio.Queue()
        self.queue.put_nowait("Session-Token: synthetic-audio-session")
        self.sent = []
        self.closed = False
        self.auth_result: object = "authentication successful"
        self.command_result: object = True
        self.reply_to_command = True
        self.command_seen = asyncio.Event()

    async def __aenter__(self) -> Self:
        """Aenter."""
        return self

    async def __aexit__(self, *_: object) -> None:
        """Aexit."""
        self.closed = True

    async def close(self) -> None:
        """Close."""
        self.closed = True
        self.queue.put_nowait(None)

    async def recv(self) -> str:
        """Recv."""
        message = await self.queue.get()
        if message is None:
            message = "synthetic connection closed"
            raise OSError(message)
        return message

    async def send(self, message: str) -> None:
        """Send."""
        self.sent.append(message)
        if message == "audio/cfg/getkey/full":
            self.queue.put_nowait(json.dumps({"getkey_result": [{"pubkey": self.public_key}]}))
        elif message.startswith("secure/authenticate/"):
            _, _, user, envelope, ciphertext = message.split("/")
            assert unquote(user) == "synthetic-user"
            decoded = PKCS1_v1_5.new(self.key).decrypt(base64.b64decode(unquote(envelope)), b"invalid")
            key, iv, session = decoded.decode().split(":")
            assert session == "synthetic-audio-session"
            plaintext = unpad(
                AES.new(bytes.fromhex(key), AES.MODE_CBC, bytes.fromhex(iv)).decrypt(
                    base64.b64decode(unquote(ciphertext))
                ),
                AES.block_size,
            )
            assert plaintext == b"synthetic-active-token"
            self.queue.put_nowait(json.dumps({"authenticate_result": self.auth_result}))
        else:
            assert message in ("audio/13/play", "audio/13/pause")
            self.command_seen.set()
            if self.reply_to_command:
                self.queue.put_nowait('{"audio_event":[{"playerid":999,"mode":"play"}]}')
                self.queue.put_nowait(json.dumps({message.rsplit("/", 1)[1] + "_result": self.command_result}))


@pytest.mark.parametrize("action", ["play", "pause"])
@pytest.mark.asyncio
async def test_authenticated_exact_player_command_waits_for_positive_ack(
    action: str, monkeypatch: pytest.MonkeyPatch, rsa_key: RSA.RsaKey
) -> None:
    """Authenticated exact player command waits for positive ack."""
    socket = SyntheticAudioSocket(rsa_key)
    opened = []

    def connect(uri: str, **kwargs: Any) -> SyntheticAudioSocket:
        """Connect."""
        opened.append((uri, kwargs))
        return socket

    monkeypatch.setattr(audioserver, "connect", connect)
    client = audioserver.AudioServerCommands(
        "audio.example.invalid", lambda: ("synthetic-user", "synthetic-active-token")
    )
    await client.async_execute(13, action)
    assert socket.sent[0] == "audio/cfg/getkey/full"
    assert socket.sent[-1] == f"audio/13/{action}"
    assert len(socket.sent) == 3
    assert socket.closed
    assert opened[0][0] == "ws://audio.example.invalid:7091/"
    assert opened[0][1]["ping_interval"] is None


@pytest.mark.parametrize("auth_result", ["authentication unsuccessful", "not authentication successful", False, None])
@pytest.mark.asyncio
async def test_negative_authentication_never_sends_play(
    auth_result: object, monkeypatch: pytest.MonkeyPatch, rsa_key: RSA.RsaKey
) -> None:
    """Negative authentication never sends play."""
    socket = SyntheticAudioSocket(rsa_key)
    socket.auth_result = auth_result
    monkeypatch.setattr(audioserver, "connect", lambda *_a, **_k: socket)
    client = audioserver.AudioServerCommands(
        "audio.example.invalid", lambda: ("synthetic-user", "synthetic-active-token")
    )
    with pytest.raises(audioserver.AudioCommandError):
        await client.async_execute(13, "play")
    assert not socket.command_seen.is_set()
    assert socket.closed


@pytest.mark.parametrize("result", [False, None, 1, "true"])
@pytest.mark.asyncio
async def test_non_boolean_positive_reply_is_not_success(
    result: object, monkeypatch: pytest.MonkeyPatch, rsa_key: RSA.RsaKey
) -> None:
    """Non boolean positive reply is not success."""
    socket = SyntheticAudioSocket(rsa_key)
    socket.command_result = result
    monkeypatch.setattr(audioserver, "connect", lambda *_a, **_k: socket)
    client = audioserver.AudioServerCommands(
        "audio.example.invalid", lambda: ("synthetic-user", "synthetic-active-token")
    )
    with pytest.raises(audioserver.AudioCommandError):
        await client.async_execute(13, "play")
    assert socket.sent.count("audio/13/play") == 1
    assert socket.closed


@pytest.mark.asyncio
async def test_unload_closes_inflight_command_and_rejects_future_commands(
    monkeypatch: pytest.MonkeyPatch, rsa_key: RSA.RsaKey
) -> None:
    """Unload closes inflight command and rejects future commands."""
    socket = SyntheticAudioSocket(rsa_key)
    socket.reply_to_command = False
    monkeypatch.setattr(audioserver, "connect", lambda *_a, **_k: socket)
    client = audioserver.AudioServerCommands(
        "audio.example.invalid", lambda: ("synthetic-user", "synthetic-active-token")
    )
    task = asyncio.create_task(client.async_execute(13, "play"))
    try:
        await asyncio.wait_for(socket.command_seen.wait(), 1)
        await client.async_close()
        with pytest.raises(audioserver.AudioCommandError):
            await asyncio.wait_for(task, 1)
        with pytest.raises(audioserver.AudioCommandError):
            await client.async_execute(13, "pause")
        assert socket.closed
        assert socket.sent.count("audio/13/play") == 1
        assert "audio/13/pause" not in socket.sent
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_missing_ack_is_timeout_not_retry(monkeypatch: pytest.MonkeyPatch, rsa_key: RSA.RsaKey) -> None:
    """Missing ack is timeout not retry."""
    socket = SyntheticAudioSocket(rsa_key)
    socket.reply_to_command = False
    monkeypatch.setattr(audioserver, "connect", lambda *_a, **_k: socket)
    client = audioserver.AudioServerCommands(
        "audio.example.invalid", lambda: ("synthetic-user", "synthetic-active-token"), timeout=0.1
    )
    with pytest.raises(audioserver.AudioCommandError):
        await client.async_execute(13, "play")
    assert socket.closed
    assert socket.sent.count("audio/13/play") == 1


@pytest.mark.asyncio
async def test_cancelled_queued_request_cannot_lose_inflight_socket(
    monkeypatch: pytest.MonkeyPatch, rsa_key: RSA.RsaKey
) -> None:
    """Cancelled queued request cannot lose inflight socket."""
    socket = SyntheticAudioSocket(rsa_key)
    socket.reply_to_command = False
    monkeypatch.setattr(audioserver, "connect", lambda *_a, **_k: socket)
    client = audioserver.AudioServerCommands(
        "audio.example.invalid", lambda: ("synthetic-user", "synthetic-active-token")
    )
    first = asyncio.create_task(client.async_execute(13, "play"))
    queued = None
    try:
        await asyncio.wait_for(socket.command_seen.wait(), 1)
        queued = asyncio.create_task(client.async_execute(13, "pause"))
        await asyncio.sleep(0)
        queued.cancel()
        await asyncio.gather(queued, return_exceptions=True)
        await client.async_close()
        with pytest.raises(audioserver.AudioCommandError):
            await asyncio.wait_for(first, 1)
        assert socket.closed
        assert "audio/13/pause" not in socket.sent
    finally:
        first.cancel()
        if queued:
            queued.cancel()
        await asyncio.gather(first, *((queued,) if queued else ()), return_exceptions=True)


@pytest.mark.asyncio
async def test_compact_public_key_uses_native_auth_without_room_fallback(
    monkeypatch: pytest.MonkeyPatch, rsa_key: RSA.RsaKey
) -> None:
    """Native replies can omit all PEM newlines; crypto must still match."""
    socket = SyntheticAudioSocket(rsa_key)
    socket.public_key = socket.public_key.replace("\n", "")
    assert "\n" not in socket.public_key
    monkeypatch.setattr(audioserver, "connect", lambda *_a, **_k: socket)
    client = audioserver.AudioServerCommands(
        "audio.example.invalid", lambda: ("synthetic-user", "synthetic-active-token")
    )
    await client.async_execute(13, "pause")
    assert socket.sent[-1] == "audio/13/pause"
    assert len(socket.sent) == 3
    assert socket.closed
