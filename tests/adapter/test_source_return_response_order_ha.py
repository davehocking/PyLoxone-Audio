"""
Delayed/reordered native feedback through real HA services and native crypto.

All device/account/content identities are synthetic. Only external discovery and
socket I/O are substituted by existing fixtures; entity, coordinator, parser,
authentication, request correlation and source/seek settlement remain real.
"""

# Fixture-driven tests intentionally access entity internals and use assertions.
# ruff: noqa: ANN001, ANN002, ANN003, ANN202, D103, F811, INP001, PLR0913, PLR0915, PLR2004, S101, SLF001
from __future__ import annotations

import asyncio
import json

import pytest
from homeassistant.exceptions import HomeAssistantError
from test_audioserver_ha import audio_setup  # noqa: F401
from test_audioserver_playback import rsa_key  # noqa: F401
from test_native_return_progress_wire_ha import native_return_harness
from test_native_source_return_ha import library_row

from custom_components.loxone.pyloxone_api import audioserver as wire


@pytest.mark.asyncio
@pytest.mark.parametrize("spotify", [False, True], ids=["library", "spotify"])
@pytest.mark.parametrize("source_order", ["echo-first", "feedback-first", "no-echo"])
@pytest.mark.parametrize("position_order", ["reply-first", "feedback-first"])
async def test_source_return_settles_late_responses_in_either_order(
    hass,
    audio_setup,
    monkeypatch,
    rsa_key,
    spotify,
    source_order,
    position_order,
):
    entity, sockets, _, shortcuts = await native_return_harness(
        hass,
        audio_setup,
        monkeypatch,
        rsa_key,
        spotify=spotify,
        tick=False,
    )
    original_connect = wire.connect
    tasks = []
    target = library_row(time=0)
    if spotify:
        target.update(
            audiopath="spotify:track:original", parent={"id": "spotify:playlist:original"}, sourceName="Synthetic owner"
        )

    async def emit(row):
        changed = asyncio.Event()
        unsubscribe = entity._audio_metadata.async_add_listener(7, changed.set)
        try:
            await audio_setup.queues[0].put(json.dumps({"audio_event": [row]}))
            # Wait only for the real metadata listener, not all HA service tasks
            # from within their own delayed-response producer.
            async with asyncio.timeout(0.5):
                await changed.wait()
        finally:
            unsubscribe()

    def connect(*args, **kwargs):
        socket = original_connect(*args, **kwargs)
        original_send = socket.send

        async def send(message):
            if not message.startswith("audio/7/"):
                return await original_send(message)
            socket.sent.append(message)

            async def deliver():
                if "/position/" in message:
                    value = float(message.rsplit("/", 1)[1])
                    reply = json.dumps({"position_result": [{"position": value}]})
                    if position_order == "reply-first":
                        socket.queue.put_nowait(reply)
                        await asyncio.sleep(0.12)
                        await emit({**target, "time": value})
                    else:
                        await emit({**target, "time": value})
                        await asyncio.sleep(0.12)
                        socket.queue.put_nowait(reply)
                elif source_order == "echo-first":
                    socket.queue.put_nowait(json.dumps({"command": message}))
                    await asyncio.sleep(0.12)
                    await emit(target)
                else:
                    await asyncio.sleep(0.06)
                    await emit(target)
                    if source_order == "feedback-first":
                        await asyncio.sleep(0.12)
                        socket.queue.put_nowait(json.dumps({"command": message}))

            tasks.append(asyncio.create_task(deliver()))
            return None

        socket.send = send
        return socket

    monkeypatch.setattr(wire, "connect", connect)
    try:
        error = None
        try:
            await hass.services.async_call(
                "media_player",
                "select_source",
                {
                    "entity_id": entity.entity_id,
                    "source": "Spotify" if spotify else "Local Library",
                },
                blocking=True,
            )
        except HomeAssistantError as exc:
            error = exc
        writes = [m for s in sockets for m in s.sent if m.startswith("audio/7/")]
        assert error is None, {
            "failure": getattr(entity, "_audio_last_source_failure", None),
            "writes": writes,
            "position": entity._audio_metadata.get(7).position,
        }
        assert len(writes) == 2
        assert writes[-1] == "audio/7/position/45.0"
        observed = entity._audio_metadata.get(7)
        assert observed.audio_path == target["audiopath"]
        assert observed.parent_id == target["parent"]["id"]
        # Reply-first may finish without observing the optional position yet.
        assert observed.position == (0 if position_order == "reply-first" else 45)
        assert not entity._audio_commands.source_fences
        assert shortcuts == []
        assert all(s.closed for s in sockets)
        audio_setup.apis[0].send_websocket_command.assert_not_awaited()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("spotify", [False, True], ids=["library", "spotify"])
async def test_source_feedback_does_not_hide_a_ready_exact_rejection(
    hass,
    audio_setup,
    monkeypatch,
    rsa_key,
    spotify,
):
    entity, sockets, _, _ = await native_return_harness(
        hass,
        audio_setup,
        monkeypatch,
        rsa_key,
        spotify=spotify,
        tick=False,
    )
    original_connect = wire.connect

    def connect(*args, **kwargs):
        socket = original_connect(*args, **kwargs)
        original_send = socket.send

        async def send(message):
            await original_send(message)
            if message.startswith("audio/7/"):
                while not socket.queue.empty():
                    socket.queue.get_nowait()
                socket.queue.put_nowait(json.dumps({"command": message, "error": "synthetic rejection"}))

        socket.send = send
        return socket

    monkeypatch.setattr(wire, "connect", connect)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "media_player",
            "select_source",
            {
                "entity_id": entity.entity_id,
                "source": "Spotify" if spotify else "Local Library",
            },
            blocking=True,
        )
    writes = [m for s in sockets for m in s.sent if m.startswith("audio/7/")]
    assert len(writes) == 1
    assert "/position/" not in writes[0]
    assert all(s.closed for s in sockets)
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()
