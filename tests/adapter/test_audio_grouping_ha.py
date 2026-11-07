"""Actual HA entry/services with invented valid native identities and I/O.

Not household captures, credentials or hardware acceptance.
"""

import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from homeassistant.components.media_player import MediaPlayerEntityFeature as F
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from custom_components.loxone.coordinator import LoxoneCoordinator
from custom_components.loxone.media_player import LoxoneAudioZoneV2
import test_audioserver_ha as base
from test_audioserver_ha import audio_setup as audio_setup

SERVER = "11111111-2222-3333-4444555555555555"
STATE = "11111111-2222-3333-4444555555556666"


def action(p):
    return f"{p:08x}-2222-3333-4444555555555555"


def row(name, players, kind="dynamic"):
    return {
        "group": name,
        "type": kind,
        "mastervolume": 0,
        "players": [{"playerid": p, "id": action(p)} for p in players],
    }


def payload(*rows):
    return json.dumps({"audio_sync_event": list(rows)})


def structure(count=6):
    result = {
        "controls": {},
        "rooms": {},
        "cats": {},
        "mediaServer": {
            SERVER: {"uuidAction": SERVER, "type": 2, "states": {"grouping": STATE}}
        },
    }
    for p in range(1, count + 1):
        result["controls"][action(p)] = {
            "uuidAction": action(p),
            "type": "AudioZoneV2",
            "name": f"Synthetic speaker {p}",
            "states": {"volume": f"volume-{p}", "playState": f"play-{p}"},
            "details": {
                "playerid": p,
                "server": SERVER,
                "playerGroup": "00000000-0000-0000-0000000000000000",
            },
        }
    return result


@pytest.fixture
async def grouped_setup(hass, audio_setup, monkeypatch):
    source = structure()
    monkeypatch.setattr(base, "STRUCTURE", source)
    refresh = LoxoneCoordinator.async_config_entry_first_refresh
    callbacks = {}
    initial = [None]
    calls = []
    entities = {}
    native_rows = {}
    added = LoxoneAudioZoneV2.async_added_to_hass

    async def capture_entity(entity):
        await added(entity)
        entities[entity.entity_id] = entity

    monkeypatch.setattr(LoxoneAudioZoneV2, "async_added_to_hass", capture_entity)

    async def first_refresh(co):
        await refresh(co)
        co.api.structure_file = copy.deepcopy(source)
        co.api.get_token_dict = lambda: {
            "token": "synthetic-token",
            "hash_alg": "SHA256",
            "valid_until": 9999999999,
        }

        async def run(**kwargs):
            callbacks[co.config_entry.entry_id] = kwargs
            kwargs["on_state"]("connected")
            if initial[0] is not None:
                await kwargs["callback"]({STATE: initial[0]})
            await asyncio.Future()

        co.api.run = run

    monkeypatch.setattr(
        LoxoneCoordinator, "async_config_entry_first_refresh", first_refresh
    )

    async def setup(*, playback=True, initial_state=None):
        initial[0] = initial_state
        entry = await audio_setup.setup(playback=playback)
        co = hass.data["loxone"][entry.entry_id]
        ids = {
            p: er.async_get(hass).async_get_entity_id(
                "media_player", "loxone", action(p)
            )
            for p in range(1, 7)
        }
        return entry, co, ids

    async def feed(entry, *rows):
        native_rows[entry.entry_id] = list(copy.deepcopy(rows))
        await callbacks[entry.entry_id]["callback"]({STATE: payload(*rows)})
        await hass.async_block_till_done()

    def wire(entry, co):
        async def request(command, reply_key, *, is_current, on_send):
            assert reply_key == "dgroup_update_result"
            assert is_current()
            on_send()
            calls.append(command)
            parts = command.split("/")
            name = parts[4]
            name = "created" if name == "new" else name
            players = (
                tuple(int(p) for p in parts[5].split(",")) if len(parts) > 5 else ()
            )
            rows = [
                r for r in native_rows.get(entry.entry_id, []) if r["group"] != name
            ]
            if players:
                rows.append(row(name, players))
            native_rows[entry.entry_id] = rows
            await callbacks[entry.entry_id]["callback"]({STATE: payload(*rows)})
            return {"id": name}

        monkeypatch.setattr(co.audio_commands, "_async_request", request)

    yield SimpleNamespace(
        setup=setup,
        feed=feed,
        wire=wire,
        callbacks=callbacks,
        calls=calls,
        source=source,
        entities=entities,
    )


async def test_real_entry_initial_grouping_feed_enables_only_confirmed_standard_controls(
    hass, grouped_setup
):
    g = grouped_setup
    entry, co, ids = await g.setup()
    before = hass.states.get(ids[1])
    assert before.state != "unavailable"
    assert not before.attributes["supported_features"] & F.GROUPING
    assert not before.attributes.get("group_members")
    await g.feed(entry)
    for p, entity_id in ids.items():
        state = hass.states.get(entity_id)
        assert state.attributes["supported_features"] & F.GROUPING
        assert state.attributes["group_members"] == [entity_id]
    await g.feed(entry, row("native", (2, 1)))
    assert hass.states.get(ids[1]).attributes["group_members"] == [ids[2], ids[1]]
    assert hass.states.get(ids[2]).attributes["group_members"] == [ids[2], ids[1]]
    assert hass.states.get(ids[3]).attributes["group_members"] == [ids[3]]


async def test_standard_ha_follower_dialog_join_then_parallel_unjoin_exact_native_scope(
    hass, grouped_setup
):
    g = grouped_setup
    entry, co, ids = await g.setup()
    g.wire(entry, co)
    await g.feed(
        entry, row("destination", (1, 2)), row("source", (3, 4)), row("outside", (5, 6))
    )
    await hass.services.async_call(
        "media_player",
        "join",
        {"entity_id": ids[2], "group_members": [ids[1], ids[3]]},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert g.calls == [
        "audio/cfg/dgroup/update/source",
        "audio/cfg/dgroup/update/destination/1,2,3",
    ]
    assert hass.states.get(ids[2]).attributes["group_members"] == [
        ids[1],
        ids[2],
        ids[3],
    ]
    assert hass.states.get(ids[4]).attributes["group_members"] == [ids[4]]
    assert hass.states.get(ids[5]).attributes["group_members"] == [ids[5], ids[6]]
    await hass.services.async_call(
        "media_player",
        "join",
        {"entity_id": ids[2], "group_members": [ids[1], ids[3]]},
        blocking=True,
    )
    assert len(g.calls) == 2
    await asyncio.gather(
        *(
            hass.services.async_call(
                "media_player", "unjoin", {"entity_id": ids[p]}, blocking=True
            )
            for p in (1, 3)
        )
    )
    await hass.async_block_till_done()
    assert g.calls == [
        "audio/cfg/dgroup/update/source",
        "audio/cfg/dgroup/update/destination/1,2,3",
        "audio/cfg/dgroup/update/destination/2,3",
        "audio/cfg/dgroup/update/destination",
    ]
    assert hass.states.get(ids[2]).attributes["group_members"] == [ids[2]]
    assert hass.states.get(ids[5]).attributes["group_members"] == [ids[5], ids[6]]


async def test_initial_reconnect_topology_change_and_unload_never_reuse_old_groups(
    hass, grouped_setup
):
    g = grouped_setup
    entry, co, ids = await g.setup(initial_state=payload(row("initial", (2, 1))))
    assert hass.states.get(ids[1]).attributes["group_members"] == [ids[2], ids[1]]
    owner = co.audio_grouping
    g.callbacks[entry.entry_id]["on_state"]("disconnected")
    await hass.async_block_till_done()
    g.callbacks[entry.entry_id]["on_state"]("connected")
    await hass.async_block_till_done()
    state = hass.states.get(ids[1])
    assert state.state != "unavailable"
    assert not state.attributes["supported_features"] & F.GROUPING
    assert not state.attributes.get("group_members")
    await g.feed(entry)
    assert hass.states.get(ids[1]).attributes["group_members"] == [ids[1]]
    co.api.structure_file["controls"][action(1)]["details"]["playerid"] = 99
    g.callbacks[entry.entry_id]["on_state"]("connected")
    await g.feed(entry)
    assert not hass.states.get(ids[1]).attributes["supported_features"] & F.GROUPING
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert owner.native.snapshot is None
    assert owner.native._closed is True
    assert co.audio_grouping is None


@pytest.mark.parametrize(
    "case",
    [
        "unknown",
        "foreign",
        "missing",
        "retired",
        "fixed",
        "static",
        "source-unavailable",
        "destination-unavailable",
        "source-owner",
    ],
)
async def test_direct_and_standard_calls_reject_all_candidates_before_any_send(
    hass, grouped_setup, monkeypatch, case
):
    g = grouped_setup
    if case == "fixed":
        g.source["controls"][action(2)]["details"]["groupObjects"] = [action(3)]
    entry, co, ids = await g.setup()
    g.wire(entry, co)
    rows = (
        [row("source", (2, 3))]
        if case in ("source-unavailable", "source-owner")
        else [row("destination", (1, 3))]
        if case == "destination-unavailable"
        else []
    )
    if case == "static":
        rows = [row("fixed", (2, 3), "static")]
    if case != "unknown":
        await g.feed(entry, *rows)
    requested = ids[2]
    if case == "foreign":
        registry = er.async_get(hass).async_get_or_create(
            "media_player", "other", "synthetic-foreign", suggested_object_id="foreign"
        )
        requested = registry.entity_id
        hass.states.async_set(
            requested, "idle", {"supported_features": int(F.GROUPING)}
        )
    elif case == "missing":
        requested = "media_player.not_registered"
    elif case in ("retired", "source-unavailable", "destination-unavailable"):
        g.entities[ids[2 if case == "retired" else 3]]._audio_removed = True
    elif case == "source-owner":
        g.entities[ids[3]]._audio_commands = None
    entity = g.entities[ids[1]]
    with pytest.raises(HomeAssistantError):
        await entity.async_join_players([requested])
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "media_player",
            "join",
            {"entity_id": ids[1], "group_members": [requested]},
            blocking=True,
        )
    assert g.calls == []
    co.api.send_websocket_command.assert_not_awaited()


@pytest.mark.parametrize("playback", [False, True])
async def test_missing_optional_binding_does_not_advertise_grouping_or_break_native_controls(
    hass, grouped_setup, playback
):
    g = grouped_setup
    g.source.pop("mediaServer")
    entry, co, ids = await g.setup(playback=playback)
    assert co.audio_grouping is None
    for entity_id in ids.values():
        state = hass.states.get(entity_id)
        assert state.state != "unavailable"
        assert not state.attributes["supported_features"] & F.GROUPING
        assert state.attributes["supported_features"] & F.VOLUME_SET


@pytest.mark.parametrize(
    "busy",
    ["source", "announcement", "transport", "source-fence", "announcement-fence"],
)
async def test_group_mutation_refuses_affected_room_busy_owners(
    hass, grouped_setup, busy
):
    g = grouped_setup
    entry, co, ids = await g.setup()
    g.wire(entry, co)
    await g.feed(entry)
    entity = g.entities[ids[2]]
    if busy == "source":
        entity._source_task = asyncio.current_task()
    elif busy == "announcement":
        entity._announcement_task = asyncio.current_task()
    elif busy == "transport":
        entity._transport_tasks.add(asyncio.current_task())
    elif busy == "source-fence":
        co.audio_commands.source_fences[2] = lambda: None
    else:
        co.audio_commands.announcement_fences[2] = lambda: None
    try:
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call(
                "media_player",
                "join",
                {"entity_id": ids[1], "group_members": [ids[2]]},
                blocking=True,
            )
        assert g.calls == []
    finally:
        entity._source_task = None
        entity._announcement_task = None
        entity._transport_tasks.clear()
        co.audio_commands.source_fences.clear()
        co.audio_commands.announcement_fences.clear()


@pytest.mark.parametrize("action", ["pause", "next", "previous"])
async def test_pending_group_send_blocks_affected_transport_but_not_outside_room(
    hass, grouped_setup, monkeypatch, action
):
    g = grouped_setup
    entry, co, ids = await g.setup()
    g.wire(entry, co)
    await g.feed(entry)
    request = co.audio_commands._async_request
    sent = asyncio.Event()
    release = asyncio.Event()

    async def held(*args, **kwargs):
        sent.set()
        await release.wait()
        return await request(*args, **kwargs)

    monkeypatch.setattr(co.audio_commands, "_async_request", held)
    execute = AsyncMock()
    monkeypatch.setattr(co.audio_commands, "async_execute", execute)
    task = asyncio.create_task(g.entities[ids[1]].async_join_players([ids[2]]))
    try:
        await asyncio.wait_for(sent.wait(), 1)
        method = {
            "pause": "async_media_pause",
            "next": "async_media_next_track",
            "previous": "async_media_previous_track",
        }[action]
        with pytest.raises(HomeAssistantError):
            await getattr(g.entities[ids[2]], method)()
        await g.entities[ids[5]].async_media_pause()
        assert execute.await_count == 1
        assert execute.call_args.args == (5, "pause")
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("known", [False, True])
async def test_unknown_or_grouped_rooms_refuse_announcement_before_preparation(
    hass, grouped_setup, monkeypatch, known
):
    from custom_components.loxone import audio_announcement

    g = grouped_setup
    entry, co, ids = await g.setup()
    if known:
        await g.feed(entry, row("native", (1, 2)))
    prepare = AsyncMock(return_value=(b"synthetic", 0.01))
    send = AsyncMock()
    monkeypatch.setattr(audio_announcement, "async_prepare_announcement", prepare)
    monkeypatch.setattr(audio_announcement, "async_send_announcement", send)
    with pytest.raises(HomeAssistantError):
        await g.entities[ids[1]].async_play_media(
            "music", "https://synthetic.invalid/test", announce=True
        )
    prepare.assert_not_awaited()
    send.assert_not_awaited()


async def test_group_feedback_never_replaces_independent_room_bookmark(
    hass, grouped_setup, audio_setup
):
    g = grouped_setup
    entry, co, ids = await g.setup()
    await g.feed(entry)
    entity = g.entities[ids[2]]
    await entity._async_refresh_native_sources()

    async def emit(path):
        await audio_setup.queues[0].put(
            json.dumps(
                {
                    "audio_event": [
                        {
                            "playerid": 2,
                            "mode": "play",
                            "eventype": 0,
                            "audiopath": path,
                        }
                    ]
                }
            )
        )
        await hass.async_block_till_done()

    await emit("tunein:station:own")
    await emit("tunein:station:own")
    saved = dict(entity._radio_catalogue.source_sessions)
    assert saved
    await g.feed(entry, row("native", (1, 2)))
    await emit("tunein:station:leader")
    await emit("tunein:station:leader")
    assert entity._radio_catalogue.source_sessions == saved


async def test_external_group_change_cancels_preparing_announcement(
    hass, grouped_setup, monkeypatch
):
    from custom_components.loxone import audio_announcement

    g = grouped_setup
    entry, co, ids = await g.setup()
    await g.feed(entry)
    ready = asyncio.Event()
    release = asyncio.Event()
    send = AsyncMock()

    async def prepare(*args):
        ready.set()
        await release.wait()
        return b"synthetic", 0.01

    monkeypatch.setattr(audio_announcement, "async_prepare_announcement", prepare)
    monkeypatch.setattr(audio_announcement, "async_send_announcement", send)
    task = asyncio.create_task(
        g.entities[ids[1]].async_play_media(
            "music", "https://synthetic.invalid/test", announce=True
        )
    )
    try:
        await asyncio.wait_for(ready.wait(), 1)
        # Feed callback directly: it must not wait for the blocked service.
        await g.callbacks[entry.entry_id]["callback"](
            {STATE: payload(row("external", (1, 2)))}
        )
        release.set()
        result = (await asyncio.gather(task, return_exceptions=True))[0]
        assert isinstance(result, (asyncio.CancelledError, HomeAssistantError))
        send.assert_not_awaited()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


async def test_grouped_track_cannot_enable_manual_seek(
    hass, grouped_setup, audio_setup
):
    g = grouped_setup
    entry, co, ids = await g.setup()
    await g.feed(entry, row("native", (1, 2)))
    await audio_setup.queues[0].put(
        json.dumps(
            {
                "audio_event": [
                    {
                        "playerid": 2,
                        "mode": "play",
                        "audiopath": "library:local:track:synthetic",
                        "time": 10,
                        "duration": 100,
                        "pbr": 32,
                    }
                ]
            }
        )
    )
    await hass.async_block_till_done()
    assert not hass.states.get(ids[2]).attributes["supported_features"] & F.SEEK
    with pytest.raises(HomeAssistantError):
        await g.entities[ids[2]].async_media_seek(20)


async def test_actual_grouping_states_for_pinned_standard_frontend(
    hass, grouped_setup, tmp_path
):
    import os
    from pathlib import Path

    g = grouped_setup
    entry, co, ids = await g.setup()
    snapshots = []

    def capture(label):
        snapshots.append(
            {
                "scenario": label,
                "target": ids[2],
                "states": {
                    entity_id: hass.states.get(entity_id).as_dict()
                    for entity_id in ids.values()
                },
                "entities": {
                    entity_id: {
                        "entity_id": entity_id,
                        "platform": er.async_get(hass).async_get(entity_id).platform,
                    }
                    for entity_id in ids.values()
                },
            }
        )

    capture("unknown")
    await g.feed(entry, row("native", (1, 2, 3)), row("static", (5, 6), "static"))
    capture("confirmed")
    assert all(
        hass.states.get(ids[p]).attributes["supported_features"] & F.GROUPING
        for p in (1, 2, 3, 4)
    )
    assert all(
        not hass.states.get(ids[p]).attributes["supported_features"] & F.GROUPING
        for p in (5, 6)
    )
    Path(
        os.environ.get("GROUP_FRONTEND_RECEIPT", tmp_path / "frontend-states.json")
    ).write_text(json.dumps(snapshots, default=str, indent=2) + "\n")
