"""Synthetic command tests; no household credentials, media or network access."""


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


from custom_components.loxone.pyloxone_api import audioserver


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

