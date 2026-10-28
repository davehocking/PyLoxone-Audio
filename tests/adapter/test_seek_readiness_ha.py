"""Shared restore readiness via real HA services/native auth; synthetic I/O only."""

# ruff: noqa: F401, F811
import asyncio
import copy
import json
from types import SimpleNamespace

import pytest
from homeassistant.exceptions import HomeAssistantError
from pyloxone_audio.diagnostic_events import DiagnosticEmitter
from test_audioserver_ha import audio_setup, zone_entity_id
from test_audioserver_playback import SyntheticAudioSocket, rsa_key
from test_native_source_return_ha import RADIO, install_sources, library_row
from custom_components.loxone.pyloxone_api import audioserver as wire


async def readiness_harness(
    hass, audio_setup, monkeypatch, rsa_key, *, spotify, startup=0, player=7
):
    import test_audioserver_ha as fixture_module

    structure = copy.deepcopy(fixture_module.STRUCTURE)
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
    monkeypatch.setattr(fixture_module, "STRUCTURE", structure)
    real_request = wire.AudioServerCommands._async_request
    entity, _emit, shortcuts = await install_sources(
        hass, audio_setup, monkeypatch, spotify=spotify, player=player
    )
    monkeypatch.setattr(wire.AudioServerCommands, "_async_request", real_request)
    commands, metadata = entity._audio_commands, entity._audio_metadata
    commands._credentials = lambda: ("synthetic-user", "synthetic-active-token")
    commands._timeout = 1
    events, sockets, writes = [], [], []
    emitter = DiagnosticEmitter(b"synthetic-readiness-test", events.append)
    emitter.enabled = True
    commands.diagnostics = emitter
    saved_rows, target_rows, started_events = {}, {}, {}
    state = SimpleNamespace(auth_hook=None)
    for pid in range(1, 13):
        saved = library_row(
            playerid=pid,
            time=38 + pid,
            audiopath=f"library:local:track:synthetic-{pid}",
        )
        if spotify:
            saved.update(
                audiopath=f"spotify:track:synthetic-{pid}",
                parent={"id": "spotify:playlist:original"},
                sourceName="Synthetic owner",
            )
        target = {**saved, "time": 0}
        if startup is None:
            target.pop("pbr")
        else:
            target["pbr"] = startup
        saved_rows[pid], target_rows[pid], started_events[pid] = (
            saved,
            target,
            asyncio.Event(),
        )

    async def folder(_self, service, account, path, offset):
        paths = [row["audiopath"] for row in saved_rows.values()]
        return [
            {
                "start": offset,
                "totalitems": len(paths),
                "audiopath": path,
                "items": [
                    {
                        "type": 2,
                        "id": p.replace("spotify:", "spotify@synthetic-account:", 1)
                        if spotify
                        else p,
                        "audiopath": p,
                        "name": "Synthetic",
                    }
                    for p in paths
                ],
            }
        ]

    monkeypatch.setattr(wire.AudioServerCommands, "async_media_folder", folder)

    async def emit(row):
        # Await only this receiver notification, never all HA tasks while a
        # service is legitimately waiting for the metadata we are producing.
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
        async def send(self, message):
            if message.startswith("audio/") and not message.startswith("audio/cfg/"):
                self.sent.append(message)
                writes.append(message)
                if "/position/" in message:
                    self.queue.put_nowait(
                        json.dumps(
                            {
                                "position_result": [
                                    {"position": float(message.rsplit("/", 1)[1])}
                                ]
                            }
                        )
                    )
                else:
                    pid = int(message.split("/")[1])
                    await emit(target_rows[pid])
                    self.queue.put_nowait(json.dumps({"command": message}))
                    started_events[pid].set()
                return
            await super().send(message)
            if (
                message.startswith("secure/authenticate/")
                and state.auth_hook is not None
            ):
                await state.auth_hook()

    def connect(*_a, **_kw):
        socket = Socket(rsa_key)
        sockets.append(socket)
        return socket

    monkeypatch.setattr(wire, "connect", connect)
    for pid in range(1, 13):
        await emit(saved_rows[pid])
        await emit({"playerid": pid, "mode": "play", "eventype": 0, "audiopath": RADIO})
    await hass.async_block_till_done()
    entities = {
        pid: hass.data["media_player"].get_entity(zone_entity_id(hass, pid))
        for pid in range(1, 13)
    }
    return SimpleNamespace(
        entity=entity,
        entities=entities,
        commands=commands,
        metadata=metadata,
        saved=saved_rows[player],
        target=target_rows[player],
        saved_rows=saved_rows,
        target_rows=target_rows,
        state=state,
        emit=emit,
        sockets=sockets,
        writes=writes,
        events=events,
        started=started_events[player],
        started_events=started_events,
        shortcuts=shortcuts,
        source="Spotify" if spotify else "Local Library",
    )


def select(hass, h, player=None):
    return hass.services.async_call(
        "media_player",
        "select_source",
        {
            "entity_id": (
                h.entities[player] if player is not None else h.entity
            ).entity_id,
            "source": h.source,
        },
        blocking=True,
    )


@pytest.mark.parametrize("spotify", [False, True], ids=["library", "spotify"])
@pytest.mark.parametrize("startup", [None, 0, 1], ids=["absent", "zero", "no-seek-bit"])
@pytest.mark.parametrize("player", range(1, 13), ids=lambda p: f"synthetic-room-{p}")
async def test_late_same_target_readiness_restores_once_at_native_send(
    hass, audio_setup, monkeypatch, rsa_key, spotify, startup, player
):
    h = await readiness_harness(
        hass,
        audio_setup,
        monkeypatch,
        rsa_key,
        spotify=spotify,
        startup=startup,
        player=player,
    )
    peers = {
        pid: room._radio_catalogue.source_session(h.source)
        for pid, room in h.entities.items()
        if pid != player
    }
    pending = asyncio.create_task(select(hass, h))
    try:
        await asyncio.wait_for(h.started.wait(), 1)
        # A distinct event-loop turn after source confirmation/settlement.
        await asyncio.sleep(0.02)
        assert not any(e.get("reason") == "eligible" for e in h.events), (
            "No positive capability has arrived yet"
        )
        await h.emit({**h.target, "pbr": 32})
        await asyncio.wait_for(pending, 1)
        assert len(h.writes) == 2, (
            "Source return discarded the bookmark before native seek readiness"
        )
        assert "/position/" not in h.writes[0]
        assert h.writes[1] == f"audio/{player}/position/{38 + player}.0"
        assert h.saved["audiopath"].replace(":", "%3A") in h.writes[0]
        assert all(s.closed for s in h.sockets)
        assert h.shortcuts == []
        assert not h.commands.source_fences
        assert h.entity._source_task is None
        assert all(
            h.entities[pid]._radio_catalogue.source_session(h.source) == saved
            for pid, saved in peers.items()
        )
        audio_setup.apis[0].send_websocket_command.assert_not_awaited()
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.parametrize("spotify", [False, True], ids=["library", "spotify"])
async def test_readiness_cannot_survive_transient_other_track_during_seek_auth(
    hass, audio_setup, monkeypatch, rsa_key, spotify
):
    h = await readiness_harness(
        hass, audio_setup, monkeypatch, rsa_key, spotify=spotify
    )
    pending = asyncio.create_task(select(hass, h))
    try:
        await asyncio.wait_for(h.started.wait(), 1)
        await asyncio.sleep(0.02)

        async def changed_and_reverted():
            await h.emit(
                {**h.target, "audiopath": "library:local:track:intervening", "pbr": 32}
            )
            await h.emit({**h.target, "pbr": 32})

        h.state.auth_hook = changed_and_reverted
        await h.emit({**h.target, "pbr": 32})
        await asyncio.wait_for(pending, 1)
        assert len(h.writes) == 1, (
            "A revoked readiness visit was revived after another track"
        )
        assert all(s.closed for s in h.sockets)
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.parametrize("spotify", [False, True], ids=["library", "spotify"])
async def test_already_ready_visit_cannot_revive_after_other_track_during_auth(
    hass, audio_setup, monkeypatch, rsa_key, spotify
):
    h = await readiness_harness(
        hass, audio_setup, monkeypatch, rsa_key, spotify=spotify, startup=32
    )

    async def changed_and_reverted():
        if not h.writes:
            return  # Source authentication is before this restore visit.
        await h.emit(
            {**h.target, "audiopath": "library:local:track:intervening", "pbr": 32}
        )
        await h.emit({**h.target, "pbr": 32})

    h.state.auth_hook = changed_and_reverted
    await asyncio.wait_for(select(hass, h), 1)
    assert len(h.writes) == 1, "An already-ready restore revived after another track"
    assert all(s.closed for s in h.sockets)


@pytest.mark.parametrize("spotify", [False, True], ids=["library", "spotify"])
@pytest.mark.parametrize("phase", ["waiting", "post_auth"])
@pytest.mark.parametrize(
    "change",
    [
        "track",
        "account",
        "source",
        "pause",
        "stop",
        "event",
        "duration_missing",
        "duration_invalid",
        "disconnect",
        "announcement",
        "source_fence",
    ],
)
async def test_changed_target_retires_readiness_without_reviving(
    hass, audio_setup, monkeypatch, rsa_key, spotify, phase, change
):
    h = await readiness_harness(
        hass, audio_setup, monkeypatch, rsa_key, spotify=spotify
    )
    pending = asyncio.create_task(select(hass, h))

    async def invalidate():
        fields = {
            "track": {"audiopath": h.target["audiopath"] + "-other"},
            "account": {"sourceName": "Different synthetic account"},
            "source": {"audiopath": RADIO},
            "pause": {"mode": "pause"},
            "stop": {"mode": "stop"},
            "event": {"eventype": 3},
            "duration_missing": {"duration": None},
            "duration_invalid": {"duration": 20},
        }
        if change == "disconnect":
            h.metadata._client._receiver._reset()
        else:
            if change == "announcement":
                h.commands.announcement_fences[7] = lambda: (
                    h.commands.announcement_fences.pop(7, None)
                )
            if change == "source_fence":
                h.commands.source_fences[7] = lambda: h.commands.source_fences.pop(
                    7, None
                )
            await h.emit({**h.target, **fields.get(change, {}), "pbr": 32})
        h.commands.announcement_fences.pop(7, None)
        h.commands.source_fences.pop(7, None)
        await h.emit({**h.target, "pbr": 32})

    try:
        await asyncio.wait_for(h.started.wait(), 1)
        await asyncio.sleep(0.02)
        assert not pending.done(), (
            "The optional readiness phase should still own the service"
        )
        if phase == "waiting":
            await invalidate()
        else:
            h.state.auth_hook = invalidate
            await h.emit({**h.target, "pbr": 32})
        await asyncio.wait_for(pending, 1)
        assert len(h.writes) == 1
        assert not any("/position/" in w for w in h.writes)
        assert all(s.closed for s in h.sockets)
        assert len(h.metadata._listeners[7]) == 1
    finally:
        h.commands.source_fences.pop(7, None)
        h.commands.announcement_fences.pop(7, None)
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.parametrize("spotify", [False, True], ids=["library", "spotify"])
@pytest.mark.parametrize(
    "action", ["cancel", "remove", "unload", "stop", "newer_source"]
)
@pytest.mark.parametrize("phase", ["waiting", "authenticating"])
async def test_newer_ha_action_cancels_readiness_and_detaches_listener(
    hass, audio_setup, monkeypatch, rsa_key, spotify, action, phase
):
    h = await readiness_harness(
        hass, audio_setup, monkeypatch, rsa_key, spotify=spotify
    )
    pending = asyncio.create_task(select(hass, h))
    auth_started, auth_release = asyncio.Event(), asyncio.Event()
    try:
        await asyncio.wait_for(h.started.wait(), 1)
        await asyncio.sleep(0.02)
        assert len(h.metadata._listeners[7]) == 2
        if phase == "authenticating":

            async def held_auth():
                auth_started.set()
                await auth_release.wait()

            h.state.auth_hook = held_auth
            await h.emit({**h.target, "pbr": 32})
            await asyncio.wait_for(auth_started.wait(), 1)
        if action == "cancel":
            pending.cancel()
        elif action == "remove":
            await h.entity.async_remove()
        elif action == "unload":
            (entry,) = hass.config_entries.async_entries("loxone")
            assert await hass.config_entries.async_unload(entry.entry_id)
        elif action == "stop":
            await hass.services.async_call(
                "media_player",
                "media_stop",
                {"entity_id": h.entity.entity_id},
                blocking=True,
            )
        else:
            await select(hass, h)
        await asyncio.wait_for(asyncio.gather(pending, return_exceptions=True), 1)
        if action not in ("unload", "remove"):
            await h.emit({**h.target, "pbr": 32})
            assert len(h.metadata._listeners[7]) == 1
        else:
            assert not h.metadata._listeners.get(7)
        assert not any("/position/" in w for w in h.writes)
        assert len(h.writes) == 1
        assert all(s.closed for s in h.sockets)
    finally:
        auth_release.set()
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.parametrize("spotify", [False, True], ids=["library", "spotify"])
@pytest.mark.parametrize(
    "cancel_first", [False, True], ids=["both-complete", "cancel-one"]
)
async def test_two_rooms_interleave_readiness_without_cross_wake_or_shared_bookmark(
    hass, audio_setup, monkeypatch, rsa_key, spotify, cancel_first
):
    h = await readiness_harness(
        hass, audio_setup, monkeypatch, rsa_key, spotify=spotify
    )
    first = asyncio.create_task(select(hass, h, 7))
    second = None
    try:
        await asyncio.wait_for(h.started_events[7].wait(), 1)
        await asyncio.sleep(0.02)
        second = asyncio.create_task(select(hass, h, 8))
        await asyncio.wait_for(h.started_events[8].wait(), 1)
        await asyncio.sleep(0.02)
        if cancel_first:
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
            await h.emit({**h.target_rows[7], "pbr": 32})
        await h.emit({**h.target_rows[8], "pbr": 32})
        await asyncio.wait_for(second, 1)
        assert [w for w in h.writes if "/position/" in w] == ["audio/8/position/46.0"]
        if not cancel_first:
            assert not first.done()
            await h.emit({**h.target_rows[7], "pbr": 32})
            await asyncio.wait_for(first, 1)
            assert [w for w in h.writes if "/position/" in w] == [
                "audio/8/position/46.0",
                "audio/7/position/45.0",
            ]
        assert len(h.writes) == (3 if cancel_first else 4)
        assert all(s.closed for s in h.sockets)
        assert all(len(h.metadata._listeners[p]) == 1 for p in range(1, 13))
    finally:
        for task in (first, second):
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(t for t in (first, second) if t is not None), return_exceptions=True
        )


@pytest.mark.parametrize("spotify", [False, True], ids=["library", "spotify"])
async def test_already_ready_has_no_readiness_delay(
    hass, audio_setup, monkeypatch, rsa_key, spotify
):
    h = await readiness_harness(
        hass, audio_setup, monkeypatch, rsa_key, spotify=spotify, startup=32
    )
    await asyncio.wait_for(select(hass, h), 0.5)
    assert len(h.writes) == 2 and h.writes[-1] == "audio/7/position/45.0"
    assert len(h.metadata._listeners[7]) == 1


@pytest.mark.parametrize("spotify", [False, True], ids=["library", "spotify"])
@pytest.mark.parametrize("startup", [None, 0, 1])
async def test_permanent_unsupported_has_one_common_two_second_ceiling(
    hass, audio_setup, monkeypatch, rsa_key, spotify, startup
):
    h = await readiness_harness(
        hass, audio_setup, monkeypatch, rsa_key, spotify=spotify, startup=startup
    )
    before = asyncio.get_running_loop().time()
    await asyncio.wait_for(select(hass, h), 3)
    elapsed = asyncio.get_running_loop().time() - before
    assert 1.9 <= elapsed < 3
    assert len(h.writes) == 1
    assert any(
        e["stage"] == "timeout" and e.get("reason") == "seek_unsupported"
        for e in h.events
    )
    assert h.metadata.get(7).audio_path == h.saved["audiopath"]
    assert h.metadata.get(7).native_mode == "play"
    assert not h.commands.source_fences
    assert len(h.metadata._listeners[7]) == 1
    await h.emit({**h.target, "pbr": 32})
    assert len(h.writes) == 1, "Late readiness cannot replay an expired restore"


@pytest.mark.parametrize("spotify", [False, True], ids=["library", "spotify"])
async def test_unrelated_frames_do_not_extend_deadline_or_leak_old_capability(
    hass, audio_setup, monkeypatch, rsa_key, spotify
):
    h = await readiness_harness(
        hass, audio_setup, monkeypatch, rsa_key, spotify=spotify
    )
    pending = asyncio.create_task(select(hass, h))
    producer = None
    try:
        await asyncio.wait_for(h.started.wait(), 1)

        async def noise():
            while True:
                await h.emit({**h.target_rows[8], "pbr": 32})
                await h.emit({**h.target, "pbr": 0})
                await asyncio.sleep(0.01)

        producer = asyncio.create_task(noise())
        before = asyncio.get_running_loop().time()
        await asyncio.wait_for(pending, 2.7)
        assert 1.8 <= asyncio.get_running_loop().time() - before < 2.7
        producer.cancel()
        await asyncio.gather(producer, return_exceptions=True)
        assert len(h.writes) == 1
        assert len(h.metadata._listeners[7]) == 1
    finally:
        for task in (pending, producer):
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(t for t in (pending, producer) if t is not None), return_exceptions=True
        )


@pytest.mark.parametrize("spotify", [False, True], ids=["library", "spotify"])
async def test_radio_return_remains_unsupported_for_position_restore(
    hass, audio_setup, monkeypatch, rsa_key, spotify
):
    h = await readiness_harness(
        hass, audio_setup, monkeypatch, rsa_key, spotify=spotify
    )
    await h.emit({**h.saved, "audiopath": RADIO, "pbr": 32})
    await h.emit({**h.saved, "audiopath": RADIO, "pbr": 32})
    await h.emit(h.saved)
    h.target_rows[7] = {**h.target, "audiopath": RADIO, "pbr": 32}
    await asyncio.wait_for(
        hass.services.async_call(
            "media_player",
            "select_source",
            {
                "entity_id": h.entity.entity_id,
                "source": "TuneIn",
            },
            blocking=True,
        ),
        0.5,
    )
    assert len(h.writes) == 1
    assert "/position/" not in h.writes[0]
