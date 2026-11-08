"""Actual HA service, grouping owner and authenticated synthetic native transport.

Invented identities only. RSA/AES handshake is independently decoded by the
existing synthetic peer. No physical device or household credential is used.
"""

import asyncio
import json
from unittest.mock import AsyncMock
import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from custom_components.loxone.pyloxone_api import audioserver as wire
from test_audio_grouping_ha import STATE, row, payload, action
from test_audio_grouping_ha import grouped_setup as grouped_setup
from test_audio_grouping_ha import audio_setup as audio_setup
from test_audioserver_playback import SyntheticAudioSocket
from test_audioserver_playback import rsa_key as rsa_key


@pytest.mark.parametrize("change", ["registry-remove", "topology"])
async def test_owning_join_revalidates_registry_and_topology_after_native_auth(
    hass, grouped_setup, monkeypatch, rsa_key, change
):
    g = grouped_setup
    entry, co, ids = await g.setup()
    await g.feed(entry)
    co.audio_commands._credentials = lambda: (
        "synthetic-user",
        "synthetic-active-token",
    )
    sockets = []

    class Socket(SyntheticAudioSocket):
        async def send(self, message):
            if message.startswith("audio/cfg/dgroup/update/"):
                self.sent.append(message)
                await g.callbacks[entry.entry_id]["callback"](
                    {STATE: payload(row("created", (1, 2)))}
                )
                self.queue.put_nowait(
                    json.dumps({"dgroup_update_result": {"id": "created"}})
                )
                return
            await super().send(message)
            if message.startswith("secure/authenticate/"):
                if change == "registry-remove":
                    er.async_get(hass).async_remove(ids[2])
                else:
                    co.api.structure_file["controls"][action(2)]["details"][
                        "server"
                    ] = action(99)

    def connect(*args, **kwargs):
        socket = Socket(rsa_key)
        sockets.append(socket)
        return socket

    monkeypatch.setattr(wire, "connect", connect)
    outcome = None
    try:
        await hass.services.async_call(
            "media_player",
            "join",
            {"entity_id": ids[1], "group_members": [ids[2]]},
            blocking=True,
        )
    except HomeAssistantError as exc:
        outcome = exc
    assert outcome is not None
    assert sockets and all(s.closed for s in sockets)
    assert not [
        m for s in sockets for m in s.sent if m.startswith("audio/cfg/dgroup/update/")
    ]
    assert co.audio_commands._socket is None
    co.api.send_websocket_command.assert_not_awaited()


@pytest.mark.parametrize(
    "scenario",
    [
        "state-before-ack",
        "state-after-ack",
        "ack-only",
        "state-only",
        "wrong-id",
        "rejected",
        "disconnect",
        "external",
        "token",
        "reconnect",
        "busy",
        "unrelated-flood",
    ],
)
async def test_join_wire_requires_exact_ack_and_unchanged_authoritative_scope(
    hass, grouped_setup, monkeypatch, rsa_key, scenario
):
    g = grouped_setup
    entry, co, ids = await g.setup()
    await g.feed(entry, row("outside", (5, 6)))
    co.audio_commands._credentials = lambda: (
        "synthetic-user",
        "synthetic-active-token",
    )
    co.audio_commands._timeout = 0.12
    co.audio_grouping.native.timeout = 0.2
    sockets = []
    producers = []

    async def feedback():
        await g.callbacks[entry.entry_id]["callback"](
            {STATE: payload(row("outside", (5, 6)), row("created", (1, 2)))}
        )

    class Socket(SyntheticAudioSocket):
        async def send(self, message):
            if message.startswith("audio/cfg/dgroup/update/"):
                self.sent.append(message)
                if scenario in (
                    "state-before-ack",
                    "state-only",
                    "wrong-id",
                    "rejected",
                    "unrelated-flood",
                ):
                    await feedback()
                elif scenario == "state-after-ack":

                    async def later():
                        await asyncio.sleep(0.01)
                        await feedback()

                    producers.append(asyncio.create_task(later()))
                elif scenario == "external":
                    await g.callbacks[entry.entry_id]["callback"](
                        {STATE: payload(row("outside", (5, 6)), row("foreign", (1, 3)))}
                    )
                if scenario == "disconnect":
                    self.queue.put_nowait(None)
                elif scenario != "state-only":
                    self.queue.put_nowait(
                        json.dumps(
                            {
                                "dgroup_update_result": False
                                if scenario == "rejected"
                                else {
                                    "id": "wrong"
                                    if scenario == "wrong-id"
                                    else "created"
                                }
                            }
                        )
                    )
                return
            await super().send(message)
            if message.startswith("secure/authenticate/"):
                if scenario == "token":
                    co.audio_commands._credentials = lambda: (
                        "synthetic-user",
                        "changed-token",
                    )
                elif scenario == "reconnect":
                    g.callbacks[entry.entry_id]["on_state"]("disconnected")
                elif scenario == "busy":
                    g.entities[ids[2]]._source_task = asyncio.current_task()

        async def recv(self):
            # Always-ready unrelated native frames must still expire/allow exact reply.
            if scenario == "unrelated-flood" and self.queue.empty():
                return json.dumps({"audio_event": [{"playerid": 6, "mode": "play"}]})
            return await super().recv()

    def connect(*args, **kwargs):
        socket = Socket(rsa_key)
        sockets.append(socket)
        return socket

    monkeypatch.setattr(wire, "connect", connect)
    outcome = None
    try:
        await hass.services.async_call(
            "media_player",
            "join",
            {"entity_id": ids[1], "group_members": [ids[2]]},
            blocking=True,
        )
    except HomeAssistantError as exc:
        outcome = exc
    finally:
        for entity in g.entities.values():
            entity._source_task = None
        await asyncio.gather(*producers)
    success = scenario in ("state-before-ack", "state-after-ack", "unrelated-flood")
    assert (outcome is None) == success
    sent = [
        m for s in sockets for m in s.sent if m.startswith("audio/cfg/dgroup/update/")
    ]
    assert sent == (
        []
        if scenario in ("token", "reconnect", "busy")
        else ["audio/cfg/dgroup/update/new/1,2"]
    )
    assert sockets and all(s.closed for s in sockets)
    assert co.audio_commands._socket is None
    if success:
        groups = {
            r.group_id: r.players for r in co.audio_grouping.native.snapshot.groups
        }
        assert groups == {"outside": (5, 6), "created": (1, 2)}
    co.api.send_websocket_command.assert_not_awaited()


async def test_same_task_external_group_change_during_announcement_auth_prevents_send(
    hass, grouped_setup, audio_setup, monkeypatch, rsa_key
):
    from custom_components.loxone import audio_announcement

    g = grouped_setup
    entry, co, ids = await g.setup()
    await g.feed(entry)
    await audio_setup.queues[0].put(
        json.dumps({"audio_event": [{"playerid": 1, "mode": "stop", "eventype": 0}]})
    )
    await hass.async_block_till_done()
    co.audio_commands._credentials = lambda: (
        "synthetic-user",
        "synthetic-active-token",
    )
    monkeypatch.setattr(
        audio_announcement,
        "async_prepare_announcement",
        AsyncMock(return_value=(b"synthetic", 0.01)),
    )
    monkeypatch.setattr(co.audio_commands, "async_upload_announcement", AsyncMock())
    sockets = []

    class Socket(SyntheticAudioSocket):
        async def send(self, message):
            if message.startswith("audio/grouped/"):
                self.sent.append(message)
                self.queue.put_nowait(json.dumps({"playuploadedfile_result": False}))
                return
            await super().send(message)
            if message.startswith("secure/authenticate/"):
                await g.callbacks[entry.entry_id]["callback"](
                    {STATE: payload(row("external", (1, 2)))}
                )

    def connect(*args, **kwargs):
        socket = Socket(rsa_key)
        sockets.append(socket)
        return socket

    monkeypatch.setattr(wire, "connect", connect)
    with pytest.raises(HomeAssistantError):
        await g.entities[ids[1]].async_play_media(
            "music", "https://synthetic.invalid/test", announce=True
        )
    assert sockets and all(s.closed for s in sockets)
    assert not [m for s in sockets for m in s.sent if m.startswith("audio/grouped/")]
