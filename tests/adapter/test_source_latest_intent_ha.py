"""Owner's newest-valid-intent contract through real HA services, synthetic I/O."""
# ruff: noqa: S101, SLF001, INP001, F811, F401, PLR2004
from __future__ import annotations

import asyncio
from typing import Any
import json

import pytest
from homeassistant.exceptions import HomeAssistantError
from test_audioserver_ha import audio_setup
from test_native_source_return_ha import install_sources, library_row, RADIO
from test_audioserver_playback import rsa_key, SyntheticAudioSocket

from custom_components.loxone.audio_catalogue import CatalogueTarget
from custom_components.loxone.audio_radio import RADIO_MEDIA_TYPE
from custom_components.loxone.pyloxone_api import audioserver as wire


@pytest.mark.asyncio
async def test_waiting_source_a_then_b_then_explicit_content_c_only_c_dispatches(
    hass: Any, audio_setup: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    entity, emit, writes = await install_sources(hass, audio_setup, monkeypatch, spotify=True)
    await emit(library_row())
    await emit({"playerid": 7, "mode": "play", "eventype": 0, "audiopath": RADIO})
    entered = {service: asyncio.Event() for service in ("library", "spotify")}
    original_folder = wire.AudioServerCommands.async_media_folder

    original_accounts = wire.AudioServerCommands.async_service_accounts

    async def folder(client: Any, service: str, *args: Any) -> Any:
        if service == "library":
            entered["library"].set()
            await asyncio.Event().wait()  # Outstanding read, cancelled by newer intent.
        return await original_folder(client, service, *args)

    async def accounts(client: Any) -> Any:
        if entered["library"].is_set():
            entered["spotify"].set()
            await asyncio.Event().wait()
        return await original_accounts(client)

    monkeypatch.setattr(wire.AudioServerCommands, "async_media_folder", folder)
    monkeypatch.setattr(wire.AudioServerCommands, "async_service_accounts", accounts)
    async def select(source: str) -> None:
        await hass.services.async_call("media_player", "select_source", {
            "entity_id": entity.entity_id, "source": source,
        }, blocking=True)
    tasks = [asyncio.create_task(select("Local Library"))]
    try:
        await asyncio.wait_for(entered["library"].wait(), 1)
        tasks.append(asyncio.create_task(select("Spotify")))
        await asyncio.wait_for(entered["spotify"].wait(), 1)
        newest = CatalogueTarget("item", "Explicit synthetic track", "library",
                                 "library:local:track:newest", audio_path="library:local:track:newest")
        media_id = entity._radio_catalogue._item(newest).media_content_id
        await hass.services.async_call("media_player", "play_media", {
            "entity_id": entity.entity_id, "media_content_type": RADIO_MEDIA_TYPE,
            "media_content_id": media_id,
        }, blocking=True)
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(isinstance(result, asyncio.CancelledError) for result in results)
        assert len(writes) == 1
        assert "library%3Alocal%3Atrack%3Anewest" in writes[0]
        assert entity._audio_metadata.get(7).audio_path == newest.audio_path
        assert entity._source_task is None
        assert not entity._audio_commands.source_fences
        assert getattr(entity, "_audio_last_source_failure", None) is None
        audio_setup.apis[0].send_websocket_command.assert_not_awaited()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_unqualified_spotify_bookmark_does_not_veto_explicit_library_departure(
    hass: Any, audio_setup: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Real HA setup, without the retired journey helper's mandatory-capture assertion.
    from test_source_simple_session_ha import session_room

    entity, emit, writes, session, spotify = await session_room(hass, audio_setup, monkeypatch)
    await emit(library_row())
    await emit(spotify)
    session.current["progress_ms"] = 65000  # Positive disagreement: no qualified bookmark.
    before = list(writes)
    provider_calls = list(session.calls)
    await hass.services.async_call(
        "media_player", "select_source", {"entity_id": entity.entity_id, "source": "Local Library"}, blocking=True,
    )
    assert len(writes) == len(before) + 2
    assert "/library/play/" in writes[-2]
    assert writes[-1] == "audio/7/position/45.0"
    assert entity._audio_metadata.get(7).source == "Local Library"
    assert not hasattr(entity, '_spotify_return')
    assert entity._source_task is None
    assert not entity._audio_commands.source_fences
    assert session.calls == provider_calls
    await hass.config_entries.async_unload(hass.config_entries.async_entries("loxone")[0].entry_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("late", ["none", "feedback", "error"])
@pytest.mark.parametrize("supersede", [False, True])
async def test_sent_old_source_closes_before_new_explicit_write_without_old_seek(
    hass: Any, audio_setup: Any, monkeypatch: pytest.MonkeyPatch, rsa_key: Any, late: str, supersede: bool,
) -> None:
    real_request = wire.AudioServerCommands._async_request
    entity, emit, shortcuts = await install_sources(hass, audio_setup, monkeypatch, spotify=True)
    monkeypatch.setattr(wire.AudioServerCommands, "_async_request", real_request)
    entity._audio_commands._credentials = lambda: ("synthetic-user", "synthetic-active-token")
    entity._audio_commands._timeout = 1
    await emit(library_row(audiopath="spotify:track:original", parent={"id": "spotify:playlist:original"}, sourceName="Synthetic owner"))
    await emit({"playerid": 7, "mode": "play", "eventype": 0, "audiopath": RADIO})
    entered, closing, allow_close = asyncio.Event(), asyncio.Event(), asyncio.Event()
    sockets: list[Any] = []
    writes: list[str] = []
    target = CatalogueTarget("item", "Newest", "library", "library:local:track:newest", audio_path="library:local:track:newest")
    media_id = entity._radio_catalogue._item(target).media_content_id

    class Socket(SyntheticAudioSocket):
        async def __aexit__(self, *args: Any) -> None:
            if self is sockets[0]:
                closing.set()
                await allow_close.wait()
            await super().__aexit__(*args)

        async def send(self, message: str) -> None:
            if message.startswith("audio/7/"):
                self.sent.append(message)
                writes.append(message)
                if "/serviceplay/spotify/" in message:
                    entered.set()
                    await asyncio.Event().wait()
                assert sockets[0].closed, "No concurrent player writes during old socket cleanup"
                audio_setup.queues[0].put_nowait(json.dumps({"audio_event": [library_row(audiopath=target.audio_path, time=0)]}))
                self.queue.put_nowait(json.dumps({"command": message}))
                return
            await super().send(message)

    def connect(*_args: Any, **_kwargs: Any) -> Any:
        socket = Socket(rsa_key)
        sockets.append(socket)
        return socket
    monkeypatch.setattr(wire, "connect", connect)
    async def select_old() -> None:
        await hass.services.async_call("media_player", "select_source", {"entity_id": entity.entity_id, "source": "Spotify"}, blocking=True)
    async def select_new() -> None:
        await hass.services.async_call("media_player", "play_media", {"entity_id": entity.entity_id, "media_content_type": RADIO_MEDIA_TYPE, "media_content_id": media_id}, blocking=True)
    old = asyncio.create_task(select_old())
    new = None
    newest = None
    try:
        await asyncio.wait_for(entered.wait(), 1)
        new = asyncio.create_task(select_new())
        await asyncio.wait_for(closing.wait(), 1)
        assert len(writes) == 1
        assert not new.done()
        if supersede:
            third_entered = asyncio.Event()
            begin = entity._async_begin_source_action
            async def third_begin() -> Any:
                third_entered.set()
                return await begin()
            monkeypatch.setattr(entity, "_async_begin_source_action", third_begin)
            newest = asyncio.create_task(select_new())
            await asyncio.wait_for(third_entered.wait(), 1)
            # B was waiting on A's close. Cancelling B must not cancel that
            # cleanup a second time or let C bypass it.
            for _ in range(6):
                await asyncio.sleep(0)
            assert len(writes) == 1
            assert not newest.done()
        # Old response arrives during cleanup; it must not resurrect follow-ups.
        if late == "feedback":
            audio_setup.queues[0].put_nowait(json.dumps({"audio_event": [library_row(audiopath="spotify:track:original", parent={"id": "spotify:playlist:original"}, sourceName="Synthetic owner", time=0)]}))
        elif late == "error":
            sockets[0].queue.put_nowait(json.dumps({"command": writes[0], "error": "synthetic rejection"}))
        allow_close.set()
        await asyncio.wait_for(newest if supersede else new, 2)
        if supersede:
            result = await asyncio.gather(new, return_exceptions=True)
            assert isinstance(result[0], asyncio.CancelledError)
        result = await asyncio.gather(old, return_exceptions=True)
        assert isinstance(result[0], asyncio.CancelledError)
        assert len(writes) == 2
        assert "library%3Alocal%3Atrack%3Anewest" in writes[-1]
        assert not any("/position/" in command for command in writes)
        assert entity._source_task is None
        assert not entity._audio_commands.source_fences
        assert not entity._audio_commands.source_observations
        assert all(socket.closed for socket in sockets)
        assert shortcuts == []
    finally:
        allow_close.set()
        for task in (old, new, newest):
            if task is not None:
                task.cancel()
        await asyncio.gather(*(task for task in (old, new, newest) if task is not None), return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("late", [False, True])
async def test_pending_library_a2_does_not_erase_a1_and_explicit_return_uses_a1(
    hass: Any, audio_setup: Any, monkeypatch: pytest.MonkeyPatch, late: bool,
) -> None:
    entity, emit, writes = await install_sources(hass, audio_setup, monkeypatch, spotify=True, previous_spotify=True)
    await emit(library_row())
    a1 = entity._radio_catalogue.source_session("Local Library")
    assert a1 is not None and a1.position == 45
    target = CatalogueTarget("item", "Pending A2", "library", "library:local:track:a2", audio_path="library:local:track:a2")
    media_id = entity._radio_catalogue._item(target).media_content_id
    entered = asyncio.Event()
    original = wire.AudioServerCommands._async_request

    async def request(client: Any, command: str, key: Any, **kwargs: Any) -> Any:
        if "library%3Alocal%3Atrack%3Aa2" in command:
            assert kwargs["is_current"]()
            kwargs["on_send"]()
            writes.append(command)
            entered.set()
            await asyncio.Event().wait()
        return await original(client, command, key, **kwargs)
    monkeypatch.setattr(wire.AudioServerCommands, "_async_request", request)
    old = asyncio.create_task(hass.services.async_call("media_player", "play_media", {
        "entity_id": entity.entity_id, "media_content_type": RADIO_MEDIA_TYPE, "media_content_id": media_id,
    }, blocking=True))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        await hass.services.async_call("media_player", "select_source", {"entity_id": entity.entity_id, "source": "Spotify"}, blocking=True)
        result = await asyncio.gather(old, return_exceptions=True)
        assert isinstance(result[0], asyncio.CancelledError)
        assert entity._radio_catalogue.source_session("Local Library") is a1
        if late:
            await emit(library_row(audiopath=target.audio_path, time=7))
        assert entity._radio_catalogue.source_session("Local Library") is a1, "Obsolete visit cannot overwrite A1"
        await hass.services.async_call("media_player", "select_source", {"entity_id": entity.entity_id, "source": "Local Library"}, blocking=True)
        # A single obsolete A2 frame is not a newly qualified session. The next
        # explicit return requests the retained A1, not a provider-only no-op.
        assert "library%3Alocal%3Atrack%3Afive" in writes[-2]
        assert writes[-1] == "audio/7/position/45.0"
        assert entity._audio_metadata.get(7).audio_path == a1.audio_path
        assert entity._source_task is None
    finally:
        old.cancel()
        await asyncio.gather(old, return_exceptions=True)
