"""Source-derived native modes; synthetic data, never household playback."""

import pytest
import asyncio
import json
from pyloxone_audio import native


def test_typed_modes_are_public_and_ha_independent():
    import pyloxone_audio as api

    assert getattr(api, "AudioRepeatMode", None) is native.AudioRepeatMode
    assert getattr(api, "audio_mode_supported", None) is native.audio_mode_supported
    assert {"AudioRepeatMode", "audio_mode_supported"} <= set(api.__all__)


@pytest.mark.parametrize(
    ("shuffle", "repeat", "expected_shuffle", "expected_repeat"),
    [
        (False, 0, False, 0),
        (True, 1, True, 1),
        (0, 3, False, 3),
        (1, 0, True, 0),
        ("0", 1, False, 1),
        ("1", 3, True, 3),
        (None, None, None, None),
        ("false", 2, None, None),
        ("true", True, None, None),
        (2, "3", None, None),
        ([], 3.0, None, None),
        ({}, -1, None, None),
    ],
)
def test_mode_feedback_is_explicit_not_truthiness(
    shuffle, repeat, expected_shuffle, expected_repeat
):
    row = native.parse_audio_events(
        {
            "audio_event": [
                {
                    "playerid": 7,
                    "mode": "play",
                    "eventype": 0,
                    "audiopath": "spotify:track:synthetic",
                    "plshuffle": shuffle,
                    "plrepeat": repeat,
                }
            ]
        }
    )[0]
    assert getattr(row, "shuffle", None) is expected_shuffle
    assert getattr(row, "repeat", None) == expected_repeat


def test_announcement_does_not_supply_queue_mode():
    row = native.parse_audio_events(
        {
            "audio_event": [
                {
                    "playerid": 7,
                    "mode": "play",
                    "eventype": 3,
                    "plshuffle": True,
                    "plrepeat": 3,
                }
            ]
        }
    )[0]
    assert getattr(row, "shuffle", None) is None
    assert getattr(row, "repeat", None) is None


@pytest.mark.parametrize(
    ("firmware", "api", "expected"),
    [
        ("16.1.09.23", "1.6", True),
        ("17.2.2.0", "1.6", True),
        ("16.1.09.22", "1.6", False),
        ("17.2.2.0", "1.5", False),
        ("bogus", "1.6", None),
        ("17.2.2.0", "bogus", None),
    ],
)
async def test_receiver_qualifies_greeting_and_replaces_partial_modes(
    firmware, api, expected
):
    queue = asyncio.Queue()
    seen = asyncio.Queue()
    receiver = native.AudioEventReceiver(seen.put_nowait)

    async def frames():
        while True:
            frame = await queue.get()
            if frame is None:
                return
            yield frame

    task = asyncio.create_task(receiver.async_listen(frames()))
    try:
        assert await seen.get() == ()
        queue.put_nowait(
            f"LWSS V {firmware} | ~API:{api}~ | Session-Token: synthetic-session"
        )
        row = {
            "playerid": 7,
            "eventype": 0,
            "mode": "play",
            "audiopath": "spotify:track:a",
            "plshuffle": True,
            "plrepeat": 3,
        }
        queue.put_nowait(json.dumps({"audio_event": [row]}))
        await asyncio.wait_for(seen.get(), 1)
        current = receiver.get(7)
        assert getattr(current, "shuffle_switch_supported", None) is expected
        assert current.shuffle is True and current.repeat == 3
        # The actual native schema requires full modes; missing fields in an
        # incomplete event are unknown, not permission to merge old values.
        queue.put_nowait(
            json.dumps(
                {
                    "audio_event": [
                        {
                            k: v
                            for k, v in row.items()
                            if k not in {"plshuffle", "plrepeat"}
                        }
                    ]
                }
            )
        )
        await asyncio.wait_for(seen.get(), 1)
        assert receiver.get(7).shuffle is None and receiver.get(7).repeat is None
    finally:
        queue.put_nowait(None)
        await asyncio.wait_for(task, 1)
    assert receiver.get(7) is None


@pytest.mark.parametrize(
    "operation,value",
    [
        ("shuffle", "0"),
        ("shuffle", 0),
        ("shuffle", None),
        ("repeat", 2),
        ("repeat", 3),
        ("repeat", True),
        ("repeat", "one"),
    ],
)
async def test_typed_native_mode_api_rejects_coercion_without_connection(
    monkeypatch, operation, value
):
    calls = []
    monkeypatch.setattr(native, "connect", lambda *a, **kw: calls.append((a, kw)))
    client = native.AudioServerCommands(
        "audio.example.invalid", lambda: ("synthetic", "synthetic")
    )
    with pytest.raises(ValueError):
        await getattr(client, "async_set_" + operation)(
            7, value, is_current=lambda: True
        )
    assert calls == []
    await client.async_close()


@pytest.mark.parametrize(
    "command",
    [
        "audio/7/shuffle",
        "audio/7/shuffle/0",
        "audio/7/shuffle/enable/secret",
        "audio/7/repeat/2",
        "audio/7/repeat/true",
    ],
)
def test_mode_diagnostics_route_allowlist_stays_strict(command):
    from pyloxone_audio.diagnostic_events import DiagnosticEmitter

    events = []
    diag = DiagnosticEmitter(b"synthetic", events.append)
    diag.enabled = True
    assert diag.route(command) is None
    diag.emit("feedback", shuffle="false", repeat=2, raw="synthetic-secret")
    assert not {"shuffle", "repeat", "raw"} & events[-1].keys()
    diag.emit("feedback", shuffle=False, repeat="off")
    assert events[-1]["shuffle"] is False and events[-1]["repeat"] == "off"


@pytest.mark.parametrize(
    "operation,value,tail",
    [
        ("shuffle", True, "shuffle/enable"),
        ("shuffle", False, "shuffle/disable"),
        ("repeat", native.AudioRepeatMode.OFF, "repeat/0"),
        ("repeat", native.AudioRepeatMode.ALL, "repeat/1"),
        ("repeat", native.AudioRepeatMode.ONE, "repeat/3"),
    ],
)
@pytest.mark.parametrize("accepted", [True, False])
async def test_real_unix_native_mode_framing_and_independent_authentication(
    monkeypatch, operation, value, tail, accepted
):
    import base64
    import os
    import tempfile
    from pathlib import Path
    from urllib.parse import unquote
    from Crypto.Cipher import AES, PKCS1_v1_5
    from Crypto.PublicKey import RSA
    from Crypto.Util.Padding import unpad
    import pytest_socket
    from websockets.asyncio.client import unix_connect
    from websockets.asyncio.server import unix_serve

    pytest_socket.socket_allow_hosts([], allow_unix_socket=True)
    key = RSA.generate(2048)
    commands, authenticated, failures = [], [], []
    closed = asyncio.Event()

    async def server(socket):
        try:
            await socket.send(
                "LWSS V 17.2.02.01 | ~API:1.6~ | Session-Token: synthetic-wire-session"
            )
            commands.append(await socket.recv())
            assert commands[-1] == "audio/cfg/getkey/full"
            await socket.send(
                json.dumps(
                    {
                        "getkey_result": [
                            {"pubkey": key.publickey().export_key().decode()}
                        ]
                    }
                )
            )
            auth = await socket.recv()
            _, _, username, envelope, ciphertext = auth.split("/")
            assert unquote(username) == "synthetic-user"
            clear = PKCS1_v1_5.new(key).decrypt(
                base64.b64decode(unquote(envelope)), b"invalid"
            )
            aes_key, iv, session = clear.decode().split(":")
            assert session == "synthetic-wire-session"
            cipher = AES.new(bytes.fromhex(aes_key), AES.MODE_CBC, bytes.fromhex(iv))
            assert (
                unpad(
                    cipher.decrypt(base64.b64decode(unquote(ciphertext))),
                    AES.block_size,
                )
                == b"synthetic-wire-token"
            )
            authenticated.append(True)
            await socket.send('{"authenticate_result":"authentication successful"}')
            commands.append(await socket.recv())
            assert commands[-1] == "audio/7/" + tail
            await socket.send(
                '{"audio_event":[{"playerid":999,"plshuffle":true,"plrepeat":1}]}'
            )
            await socket.send(
                json.dumps(
                    {operation + "_result": {operation: value} if accepted else False}
                )
            )
            await socket.wait_closed()
        except Exception as error:
            failures.append(type(error).__name__)
        finally:
            closed.set()

    with tempfile.TemporaryDirectory(
        prefix="mode-wire-", dir=os.environ["TMPDIR"]
    ) as folder:
        path = str(Path(folder) / "ws.sock")
        async with await unix_serve(
            server, path, subprotocols=["remotecontrol"], ping_interval=None
        ):
            monkeypatch.setattr(
                native,
                "connect",
                lambda uri, **kw: unix_connect(path=path, uri=uri, **kw),
            )
            client = native.AudioServerCommands(
                "audio.example.invalid",
                lambda: ("synthetic-user", "synthetic-wire-token"),
            )
            try:
                call = getattr(client, "async_set_" + operation)(
                    7, value, is_current=lambda: True
                )
                if accepted:
                    assert await call is None
                else:
                    with pytest.raises(native.AudioCommandError):
                        await call
                await asyncio.wait_for(closed.wait(), 2)
            finally:
                await client.async_close()
    assert failures == [] and authenticated == [True]
    assert commands == ["audio/cfg/getkey/full", "audio/7/" + tail]
