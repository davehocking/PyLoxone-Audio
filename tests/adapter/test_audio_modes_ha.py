"""Standard HA mode services through native RSA/AES, synthetic all-room feedback."""

# ruff: noqa: F401, F811
import asyncio
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from homeassistant.components.media_player import MediaPlayerEntityFeature
from homeassistant.exceptions import HomeAssistantError
from pyloxone_audio.diagnostic_events import DiagnosticEmitter
from test_audioserver_ha import audio_setup, zone_entity_id
from test_audioserver_playback import SyntheticAudioSocket, rsa_key
from custom_components.loxone.pyloxone_api import audioserver as wire
from custom_components.loxone.const import EVENT

GREETING = "LWSS V 17.2.02.01 | ~API:1.6~ | Session-Token: synthetic-audio-session"
FULL = 2048 | 4096 | 8192 | 32


async def mode_harness(
    hass,
    audio_setup,
    monkeypatch,
    rsa_key,
    *,
    playback=True,
    greeting=GREETING,
    source="spotify",
):
    import test_audioserver_ha as fixtures

    structure = copy.deepcopy(fixtures.STRUCTURE)
    prototype = next(iter(structure["controls"].values()))
    structure["controls"] = {}
    for pid in range(1, 13):
        control = copy.deepcopy(prototype)
        control.update(
            uuidAction=f"synthetic-zone-{pid}",
            details={"playerid": pid},
            states={"volume": f"volume-{pid}", "playState": f"play-{pid}"},
        )
        structure["controls"][control["uuidAction"]] = control
    monkeypatch.setattr(fixtures, "STRUCTURE", structure)
    entry = await audio_setup.setup(playback=playback)
    entities = {
        p: hass.data["media_player"].get_entity(zone_entity_id(hass, p))
        for p in range(1, 13)
    }
    metadata = entities[7]._audio_metadata
    commands = entities[7]._audio_commands
    if commands is not None:
        commands._credentials = lambda: ("synthetic-user", "synthetic-active-token")
        commands._timeout = 0.25
    state = SimpleNamespace(
        auth_hook=None,
        feedback=True,
        reply="normal",
        auth="authentication successful",
        command_greeting=GREETING,
    )
    rows, sockets, writes, events = {}, [], [], []
    emitter = DiagnosticEmitter(b"synthetic-mode-key", events.append)
    if commands is not None:
        commands.diagnostics = emitter
    metadata.diagnostics = emitter

    async def emit(row):
        delivered = asyncio.get_running_loop().create_future()

        def received():
            if not delivered.done():
                delivered.set_result(None)

        remove = metadata.async_add_listener(row["playerid"], received)
        try:
            audio_setup.queues[0].put_nowait(json.dumps({"audio_event": [row]}))
            await asyncio.wait_for(delivered, 1)
        finally:
            remove()

    class Socket(SyntheticAudioSocket):
        def __init__(self):
            super().__init__(rsa_key)
            self.queue.get_nowait()
            self.queue.put_nowait(state.command_greeting)
            self.auth_result = state.auth

        async def send(self, message):
            if message.startswith("audio/") and not message.startswith("audio/cfg/"):
                self.sent.append(message)
                writes.append(message)
                player, operation, value = message.split("/")[1:]
                player = int(player)
                assert operation in ("shuffle", "repeat"), (
                    "Unexpected playback operation"
                )
                target = value == "enable" if operation == "shuffle" else int(value)
                if state.feedback:
                    rows[player] = {
                        **rows[player],
                        "plshuffle" if operation == "shuffle" else "plrepeat": target,
                    }
                    await emit(rows[player])
                if state.reply == "normal":
                    self.queue.put_nowait(
                        json.dumps({operation + "_result": {operation: target}})
                    )
                elif state.reply == "negative":
                    self.queue.put_nowait(json.dumps({operation + "_result": False}))
                elif state.reply == "disconnect":
                    self.queue.put_nowait(None)
                elif state.reply != "silent":
                    self.queue.put_nowait(
                        json.dumps({operation + "_result": state.reply})
                    )
                return
            await super().send(message)
            if (
                message.startswith("secure/authenticate/")
                and state.auth_hook is not None
            ):
                await state.auth_hook()

    def connect(*_a, **_kw):
        socket = Socket()
        sockets.append(socket)
        return socket

    monkeypatch.setattr(wire, "connect", connect)
    if greeting is not None:
        audio_setup.queues[0].put_nowait(greeting)
    prefix = "library:local" if source == "library" else source
    for pid in range(1, 13):
        rows[pid] = {
            "playerid": pid,
            "eventype": 0,
            "mode": "play",
            "pbr": FULL,
            "audiopath": f"{prefix}:track:synthetic-{pid}",
            "sourceName": "Synthetic account",
            "parent": {"id": f"{prefix}:album:synthetic"},
            "title": "Synthetic title",
            "time": 30 + pid,
            "duration": 200,
            "plshuffle": False,
            "plrepeat": 0,
        }
        await emit(rows[pid])
    hass.bus.async_fire(EVENT, {f"play-{pid}": 2 for pid in range(1, 13)})
    await hass.async_block_till_done()
    return SimpleNamespace(
        entities=entities,
        metadata=metadata,
        commands=commands,
        rows=rows,
        sockets=sockets,
        writes=writes,
        events=events,
        emitter=emitter,
        emit=emit,
        state=state,
        entry=entry,
        apis=audio_setup.apis,
    )


def request(hass, h, player, operation, value):
    return hass.services.async_call(
        "media_player",
        operation + "_set",
        {
            "entity_id": h.entities[player].entity_id,
            operation: value,
        },
        blocking=True,
    )


def frontend_receipt(hass, entity, **case):
    if receipt := os.environ.get("AUDIO_MODES_FRONTEND_RECEIPT"):
        state = hass.states.get(entity.entity_id)
        with Path(receipt).open("a") as output:
            output.write(
                json.dumps(
                    {
                        **case,
                        "entity_id": entity.entity_id,
                        "state": state.state,
                        "attributes": dict(state.attributes),
                    },
                    default=lambda value: value.isoformat(),
                )
                + "\n"
            )


@pytest.mark.parametrize("player", range(1, 13), ids=lambda p: f"room-{p}")
@pytest.mark.parametrize("source", ["spotify", "library"])
@pytest.mark.parametrize(
    ("operation", "value", "native"),
    [
        ("shuffle", True, "shuffle/enable"),
        ("shuffle", False, "shuffle/disable"),
        ("repeat", "off", "repeat/0"),
        ("repeat", "all", "repeat/1"),
        ("repeat", "one", "repeat/3"),
    ],
)
async def test_native_ha_modes_send_once_and_publish_confirmed_state_all_rooms(
    hass,
    audio_setup,
    monkeypatch,
    rsa_key,
    player,
    operation,
    value,
    native,
    source,
):
    h = await mode_harness(hass, audio_setup, monkeypatch, rsa_key, source=source)
    assert "spotify" not in hass.config.components, (
        "Native modes cannot require an HA Spotify entity"
    )
    room = h.entities[player]
    before_hash = room.media_image_hash
    before_sessions = {
        p: copy.copy(e._radio_catalogue.source_sessions) for p, e in h.entities.items()
    }
    failure = None
    try:
        await request(hass, h, player, operation, value)
    except HomeAssistantError as err:
        failure = type(err).__name__
    assert failure is None, "Standard HA mode service is not implemented/advertised"
    await hass.async_block_till_done()
    assert h.writes == [f"audio/{player}/{native}"]
    attrs = hass.states.get(room.entity_id).attributes
    assert attrs.get(operation) == value, (
        hass.states.get(room.entity_id),
        room.shuffle,
        room.repeat,
    )
    assert attrs["supported_features"] & MediaPlayerEntityFeature.SHUFFLE_SET
    assert attrs["supported_features"] & MediaPlayerEntityFeature.REPEAT_SET
    frontend_receipt(
        hass, room, room=player, source=source, operation=operation, value=value
    )
    assert all(s.closed for s in h.sockets)
    assert room.media_image_hash == before_hash, "Mode-only feedback churned artwork"
    assert h.apis[0].send_websocket_command.await_count == 0
    assert h.events == [], "Diagnostics must remain OFF"
    for pid, other in h.entities.items():
        assert other._radio_catalogue.source_sessions == before_sessions[pid]
        if pid != player:
            assert other.shuffle is False and other.repeat == "off"


@pytest.mark.parametrize(
    ("update", "shuffle", "repeat"),
    [
        ({"pbr": 0}, False, False),
        ({"pbr": 4096}, False, False),
        ({"pbr": 8192}, False, False),
        ({"pbr": 4096 | 8192}, False, True),
        ({"pbr": 2048}, True, False),
        ({"pbr": None}, False, False),
        ({"mode": "pause"}, False, True),
        ({"mode": "stop"}, False, False),
        ({"mode": "unknown"}, False, False),
        ({"eventype": 3}, False, False),
        ({"eventype": -1}, False, False),
        ({"audiopath": None}, False, False),
        ({"plshuffle": None}, False, True),
        ({"plshuffle": "false"}, False, True),
        ({"plrepeat": 2}, True, False),
        ({"plrepeat": True}, True, False),
    ],
)
async def test_capability_gates_both_advertisement_and_owning_setter(
    hass, audio_setup, monkeypatch, rsa_key, update, shuffle, repeat
):
    h = await mode_harness(hass, audio_setup, monkeypatch, rsa_key)
    room = h.entities[7]
    await h.emit({**h.rows[7], **update})
    await hass.async_block_till_done()
    frontend_receipt(
        hass,
        room,
        scenario="capability",
        update=update,
        expected_shuffle=shuffle,
        expected_repeat=repeat,
    )
    for op, enabled, bit, value in [
        ("shuffle", shuffle, MediaPlayerEntityFeature.SHUFFLE_SET, True),
        ("repeat", repeat, MediaPlayerEntityFeature.REPEAT_SET, "one"),
    ]:
        assert bool(room.supported_features & bit) is enabled
        if not enabled:
            with pytest.raises(HomeAssistantError):
                await request(hass, h, 7, op, value)
            with pytest.raises(HomeAssistantError):
                await getattr(room, "async_set_" + op)(value)
    assert not h.writes and not h.sockets


@pytest.mark.parametrize(
    "greeting",
    [
        None,
        GREETING.replace("17.2.02.01", "16.1.09.22"),
        GREETING.replace("1.6", "1.5"),
        "not-a-greeting",
    ],
)
async def test_unqualified_firmware_has_no_shuffle_switch(
    hass, audio_setup, monkeypatch, rsa_key, greeting
):
    h = await mode_harness(hass, audio_setup, monkeypatch, rsa_key, greeting=greeting)
    assert not h.entities[7].supported_features & MediaPlayerEntityFeature.SHUFFLE_SET
    with pytest.raises(HomeAssistantError):
        await request(hass, h, 7, "shuffle", True)
    assert h.writes == []
    await request(hass, h, 7, "repeat", "one")
    assert h.writes == ["audio/7/repeat/3"]


@pytest.mark.parametrize("operation,value", [("shuffle", True), ("repeat", "one")])
async def test_disabled_playback_keeps_receive_only_modes_without_setters(
    hass, audio_setup, monkeypatch, rsa_key, operation, value
):
    h = await mode_harness(hass, audio_setup, monkeypatch, rsa_key, playback=False)
    assert h.entities[7].shuffle is False and h.entities[7].repeat == "off"
    with pytest.raises(HomeAssistantError):
        await request(hass, h, 7, operation, value)
    assert not h.sockets and not h.writes


async def test_external_partial_disconnect_feedback_and_artwork_identity(
    hass, audio_setup, monkeypatch, rsa_key
):
    h = await mode_harness(hass, audio_setup, monkeypatch, rsa_key)
    room = h.entities[7]
    original_hash = room.media_image_hash
    for shuffle, repeat in [(True, 3), (False, 1), (True, 0)]:
        await h.emit({**h.rows[7], "plshuffle": shuffle, "plrepeat": repeat})
        await hass.async_block_till_done()
        attrs = hass.states.get(room.entity_id).attributes
        assert attrs["shuffle"] is shuffle
        assert attrs["repeat"] == {0: "off", 1: "all", 3: "one"}[repeat]
        assert room.media_image_hash == original_hash
        frontend_receipt(
            hass, room, scenario="external", expected_shuffle=True, expected_repeat=True
        )
    await h.emit(
        {k: v for k, v in h.rows[7].items() if k not in ("plshuffle", "plrepeat")}
    )
    await hass.async_block_till_done()
    assert room.shuffle is None and room.repeat is None
    assert not room.supported_features & (
        MediaPlayerEntityFeature.SHUFFLE_SET | MediaPlayerEntityFeature.REPEAT_SET
    )
    assert room.media_image_hash == original_hash
    frontend_receipt(
        hass, room, scenario="partial", expected_shuffle=False, expected_repeat=False
    )
    audio_setup.queues[0].put_nowait(None)
    for _ in range(50):
        if h.metadata.get(7) is None:
            break
        await asyncio.sleep(0)
    await hass.async_block_till_done()
    assert h.metadata.get(7) is None and room.shuffle is None and room.repeat is None
    frontend_receipt(
        hass, room, scenario="disconnect", expected_shuffle=False, expected_repeat=False
    )
    assert h.writes == []


@pytest.mark.parametrize("operation,value", [("shuffle", True), ("repeat", "one")])
@pytest.mark.parametrize(
    "failure",
    ["negative", "silent", "disconnect", "wrong-mode", "auth", "old-command-firmware"],
)
async def test_native_mode_failures_no_retry_or_optimistic_state(
    hass, audio_setup, monkeypatch, rsa_key, operation, value, failure
):
    h = await mode_harness(hass, audio_setup, monkeypatch, rsa_key)
    h.state.feedback = False
    h.state.reply = (
        failure if failure in ("negative", "silent", "disconnect") else "normal"
    )
    if failure == "wrong-mode":
        h.state.reply = {operation: False if operation == "shuffle" else 2}
    if failure == "auth":
        h.state.auth = "authentication failed"
    if failure == "old-command-firmware":
        h.state.command_greeting = GREETING.replace("17.2.02.01", "16.1.09.22")
        if operation == "repeat":
            await request(hass, h, 7, operation, value)
            assert h.writes == ["audio/7/repeat/3"]
            return
    with pytest.raises(HomeAssistantError):
        await request(hass, h, 7, operation, value)
    expected = 0 if failure in ("auth", "old-command-firmware") else 1
    assert len(h.writes) == expected
    assert all(socket.closed for socket in h.sockets)
    assert h.entities[7].shuffle is False and h.entities[7].repeat == "off"
    assert h.apis[0].send_websocket_command.await_count == 0


@pytest.mark.parametrize("operation,value", [("shuffle", True), ("repeat", "one")])
async def test_reply_without_feedback_does_not_invent_enabled_state(
    hass, audio_setup, monkeypatch, rsa_key, operation, value
):
    h = await mode_harness(hass, audio_setup, monkeypatch, rsa_key)
    h.state.feedback = False
    await request(hass, h, 7, operation, value)
    assert len(h.writes) == 1
    assert h.entities[7].shuffle is False and h.entities[7].repeat == "off"
    await h.emit({**h.rows[7], "plshuffle": True, "plrepeat": 3})
    await hass.async_block_till_done()
    assert h.entities[7].shuffle is True and h.entities[7].repeat == "one"


@pytest.mark.parametrize(
    "change",
    ["track", "account", "parent", "permission", "event", "missing", "transient"],
)
async def test_authentication_delay_invalidates_old_native_mode_intent(
    hass, audio_setup, monkeypatch, rsa_key, change
):
    h = await mode_harness(hass, audio_setup, monkeypatch, rsa_key)

    async def during_auth():
        changes = {
            "track": {"audiopath": "spotify:track:new"},
            "account": {"sourceName": "Other account"},
            "parent": {"parent": {"id": "spotify:album:other"}},
            "permission": {"pbr": 0},
            "event": {"eventype": 3},
            "missing": {"plshuffle": None},
            "transient": {"pbr": 0},
        }
        await h.emit({**h.rows[7], **changes[change]})
        if change == "transient":
            await h.emit(h.rows[7])

    h.state.auth_hook = during_auth
    with pytest.raises(HomeAssistantError):
        await request(hass, h, 7, "shuffle", True)
    assert h.writes == [] and all(s.closed for s in h.sockets)


async def test_newer_mode_supersedes_waiting_request_without_cancelling_other_room(
    hass, audio_setup, monkeypatch, rsa_key
):
    h = await mode_harness(hass, audio_setup, monkeypatch, rsa_key)
    entered, hold = asyncio.Event(), asyncio.Event()

    async def block_first_auth():
        h.state.auth_hook = None
        entered.set()
        await hold.wait()

    h.state.auth_hook = block_first_auth
    old = asyncio.create_task(request(hass, h, 7, "shuffle", True))
    others = []
    try:
        await asyncio.wait_for(entered.wait(), 1)
        others.append(asyncio.create_task(request(hass, h, 8, "repeat", "one")))
        await asyncio.sleep(0)
        others.append(asyncio.create_task(request(hass, h, 7, "shuffle", False)))
        await asyncio.wait_for(asyncio.gather(*others), 2)
        result = await asyncio.gather(old, return_exceptions=True)
        assert isinstance(result[0], asyncio.CancelledError)
        assert h.writes == ["audio/8/repeat/3", "audio/7/shuffle/disable"]
        assert h.entities[8].repeat == "one" and h.entities[7].shuffle is False
        assert h.entities[7]._source_task is None and h.entities[8]._source_task is None
    finally:
        hold.set()
        for task in [old, *others]:
            if not task.done():
                task.cancel()
        await asyncio.gather(old, *others, return_exceptions=True)
    assert all(s.closed for s in h.sockets)


async def test_unload_drains_pending_mode_socket(
    hass, audio_setup, monkeypatch, rsa_key
):
    h = await mode_harness(hass, audio_setup, monkeypatch, rsa_key)
    entered, hold = asyncio.Event(), asyncio.Event()

    async def block_auth():
        entered.set()
        await hold.wait()

    h.state.auth_hook = block_auth
    task = asyncio.create_task(request(hass, h, 7, "repeat", "one"))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert await hass.config_entries.async_unload(h.entry.entry_id)
        result = await asyncio.gather(task, return_exceptions=True)
        assert isinstance(result[0], asyncio.CancelledError)
        assert not h.writes and all(s.closed for s in h.sockets)
        assert h.metadata._listeners == {}
    finally:
        hold.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize(
    "source",
    [
        "library:local:track:a",
        "tunein:station:a",
        "linein:input:a",
        "unknown:native:source",
    ],
)
@pytest.mark.parametrize("permissions", [0, FULL])
async def test_provider_independent_native_permissions_not_source_labels(
    hass, audio_setup, monkeypatch, rsa_key, source, permissions
):
    h = await mode_harness(hass, audio_setup, monkeypatch, rsa_key)
    h.rows[7] = {**h.rows[7], "audiopath": source, "pbr": permissions}
    await h.emit(h.rows[7])
    await hass.async_block_till_done()
    assert bool(
        h.entities[7].supported_features & MediaPlayerEntityFeature.SHUFFLE_SET
    ) is bool(permissions)
    assert bool(
        h.entities[7].supported_features & MediaPlayerEntityFeature.REPEAT_SET
    ) is bool(permissions)
    if permissions:
        await request(hass, h, 7, "shuffle", True)
        await request(hass, h, 7, "repeat", "one")
        assert h.writes == ["audio/7/shuffle/enable", "audio/7/repeat/3"]
    else:
        with pytest.raises(HomeAssistantError):
            await request(hass, h, 7, "shuffle", True)
        with pytest.raises(HomeAssistantError):
            await request(hass, h, 7, "repeat", "one")
        assert h.writes == []
    # FULL is a synthetic advertised-native-capability control, not a claim
    # that real Line-In/radio firmware supplies these permissions or modes.


async def test_opt_in_modes_diagnostics_retains_strict_aliased_routes_and_state(
    hass, audio_setup, monkeypatch, rsa_key
):
    from custom_components.loxone.audio_diagnostics import _safe_event

    h = await mode_harness(hass, audio_setup, monkeypatch, rsa_key)
    h.emitter.enabled = True
    await request(hass, h, 7, "shuffle", True)
    await request(hass, h, 7, "repeat", "one")
    assert h.events
    for operation, suffix in [("shuffle", "/shuffle/enable"), ("repeat", "/repeat/3")]:
        routed = [
            e
            for e in h.events
            if e.get("operation") == operation and e.get("route", "").endswith(suffix)
        ]
        assert {e["stage"] for e in routed} >= {
            "request",
            "authenticated",
            "send_attempt",
            "send_completed",
            "reply",
        }
        assert all("audio/7/" not in e["route"] for e in routed)
    feedback = [e for e in h.events if e["stage"] == "feedback"]
    assert feedback[-1]["shuffle"] is True and feedback[-1]["repeat"] == "one"
    assert all(_safe_event(e) for e in h.events)
    text = json.dumps(h.events)
    assert "synthetic-active-token" not in text and "spotify:track:" not in text
    assert not _safe_event({**feedback[-1], "repeat": 2})
    assert not _safe_event({**feedback[-1], "shuffle": "false"})
