"""Native typed group command contract, synthetic I/O only."""

import pytest
from unittest.mock import AsyncMock
from pyloxone_audio import native


@pytest.mark.parametrize(
    "group,members,route,reply",
    [
        (None, (2, 1), "audio/cfg/dgroup/update/new/2,1", "opaque-new"),
        (
            "opaque-existing",
            (2, 1, 3),
            "audio/cfg/dgroup/update/opaque-existing/2,1,3",
            "opaque-existing",
        ),
        (
            "opaque-existing",
            (),
            "audio/cfg/dgroup/update/opaque-existing",
            "opaque-existing",
        ),
    ],
)
async def test_group_update_serializes_typed_create_update_exact_dissolve(
    monkeypatch, group, members, route, reply
):
    client = native.AudioServerCommands(
        "audio.example.invalid", lambda: ("synthetic", "synthetic")
    )
    request = AsyncMock(return_value={"id": reply})
    monkeypatch.setattr(client, "_async_request", request)

    def current():
        return True

    def sent():
        return None

    assert (
        await client.async_update_group(
            group, members, is_current=current, on_send=sent
        )
        == reply
    )
    request.assert_awaited_once_with(
        route, "dgroup_update_result", is_current=current, on_send=sent
    )
    await client.async_close()


@pytest.mark.parametrize(
    "group,members",
    [
        ("../group", (1, 2)),
        ("new", (1, 2)),
        ("", (1, 2)),
        (False, (1, 2)),
        (None, ()),
        (None, (1,)),
        ("old", (1,)),
        ("old", (1, 1)),
        ("old", (True, 2)),
        ("old", ("1", 2)),
        ("old", (1.0, 2)),
        ("old", (-1, 2)),
        ("old", [1, 2]),
        ("old", None),
    ],
)
async def test_invalid_group_command_cannot_reach_native_request(
    monkeypatch, group, members
):
    client = native.AudioServerCommands(
        "audio.example.invalid", lambda: ("synthetic", "synthetic")
    )
    request = AsyncMock(return_value={"id": "old"})
    monkeypatch.setattr(client, "_async_request", request)
    with pytest.raises(ValueError):
        await client.async_update_group(group, members, is_current=lambda: True)
    request.assert_not_awaited()


@pytest.mark.parametrize(
    "reply", [True, {}, {"id": True}, {"id": "wrong"}, {"id": "../escape"}, {"id": ""}]
)
async def test_group_update_requires_valid_exact_id_acknowledgement(monkeypatch, reply):
    client = native.AudioServerCommands(
        "audio.example.invalid", lambda: ("synthetic", "synthetic")
    )
    monkeypatch.setattr(client, "_async_request", AsyncMock(return_value=reply))
    with pytest.raises(native.AudioCommandError):
        await client.async_update_group("old", (1, 2), is_current=lambda: True)


async def test_group_token_change_during_authentication_prevents_dispatch(monkeypatch):
    credentials = ["synthetic", "old-token"]
    sent = []

    class Socket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def send(self, command):
            sent.append(command)

        async def recv(self):
            return '{"dgroup_update_result":{"id":"old"}}'

    monkeypatch.setattr(native, "connect", lambda *a, **k: Socket())
    client = native.AudioServerCommands(
        "audio.example.invalid", lambda: tuple(credentials)
    )

    async def auth(*args):
        credentials[1] = "new-token"

    monkeypatch.setattr(client, "_authenticate", auth)
    with pytest.raises(native.AudioCommandError):
        await client.async_update_group("old", (1, 2), is_current=lambda: True)
    assert sent == []
