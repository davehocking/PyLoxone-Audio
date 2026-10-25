"""
Terminal source settlement must not depend on a departed caller's generation.

Actual HA services, receiver and authenticated synthetic wire. No household data.
"""
# Synthetic literal IDs/counts and one complete source-action lifecycle.
# ruff: noqa: S101, INP001, F811, F401, SLF001, PLR2004
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from homeassistant.exceptions import HomeAssistantError
from test_audioserver_ha import audio_setup
from test_audioserver_playback import rsa_key
from test_native_return_progress_wire_ha import native_return_harness
from test_native_source_return_ha import RADIO, library_row

from custom_components.loxone.pyloxone_api import audioserver as wire

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


@pytest.mark.asyncio
async def test_late_exact_library_feedback_settles_after_a_blocked_spotify_request(  # noqa: PLR0915 - one complete no-replay lifecycle
    hass: HomeAssistant,
    audio_setup: Any,
    monkeypatch: pytest.MonkeyPatch,
    rsa_key: Any,
) -> None:
    """Settle a failed action, then allow a new explicit Spotify request.

    The historical case ID/assertion wording is retained for reconciliation;
    this body makes no intervening blocked Spotify request before terminal proof.
    """
    entity, sockets, _samples, shortcuts = await native_return_harness(
        hass, audio_setup, monkeypatch, rsa_key,
        spotify=True, tick=False, source_echo=False,
        source_feedback=library_row(audiopath="tunein:station:unsettled", time=0),
    )

    async def emit(row: dict[str, Any]) -> None:
        await audio_setup.queues[0].put(json.dumps({"audio_event": [row]}))
        await hass.async_block_till_done()

    await emit(library_row())
    await emit({"playerid": 7, "mode": "play", "eventype": 0, "audiopath": RADIO})
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "media_player", "select_source",
            {"entity_id": entity.entity_id, "source": "Local Library"}, blocking=True,
        )
    assert not hasattr(entity, "_audio_last_source_failure")
    assert 7 in entity._audio_commands.source_fences
    assert len(sockets) == 1
    assert sockets[0].closed
    writes = [message for socket in sockets for message in socket.sent if message.startswith("audio/7/")]
    assert len(writes) == 1
    assert "/library/play/" in writes[0]

    # No NEW request yet: ambiguous first dispatch cannot replay itself.
    await hass.async_block_till_done()
    assert len(sockets) == 1

    # Neither timer callbacks nor contrary native identity qualify settlement.
    for callback in tuple(entity._audio_metadata._listeners.get(7, ())):
        callback()
    assert 7 in entity._audio_commands.source_fences
    for row in (
        library_row(audiopath="tunein:station:foreign"),
        library_row(audiopath="spotify:track:foreign"),
        library_row(mode="pause"),
        library_row(eventype=3),
    ):
        await emit(row)
        assert 7 in entity._audio_commands.source_fences
    # Explicit event end, then an independently fresh exact wire sample.
    await emit(library_row(mode="stop", eventype=0))
    await emit(library_row(time=12))
    assert 7 not in entity._audio_commands.source_fences, (
        "Fresh exact terminal proof must release ownership despite the rejected newer generation"
    )
    assert writes == [message for socket in sockets for message in socket.sent if message.startswith("audio/7/")]
    assert entity._audio_metadata.get(7).position == 12

    # Only a NEW explicit Spotify service request may now dispatch. Terminal
    # settlement did not resurrect the old request or its corrective seek.
    original_connect = wire.connect

    def connect(*args: Any, **kwargs: Any) -> Any:
        socket = original_connect(*args, **kwargs)
        original_send = socket.send

        async def send(message: str) -> None:
            if message.startswith("audio/7/serviceplay/spotify/"):
                socket.sent.append(message)
                await audio_setup.queues[0].put(json.dumps({"audio_event": [library_row(
                    audiopath="spotify:track:original",
                    parent={"id": "spotify:playlist:original"},
                    sourceName="Synthetic owner", time=0,
                )]}))
                socket.queue.put_nowait(json.dumps({"command": message}))
                return
            await original_send(message)

        socket.send = send
        return socket

    monkeypatch.setattr(wire, "connect", connect)
    await hass.services.async_call(
        "media_player", "select_source",
        {"entity_id": entity.entity_id, "source": "Spotify"}, blocking=True,
    )
    final_writes = [message for socket in sockets for message in socket.sent if message.startswith("audio/7/")]
    assert len(final_writes) == 3
    assert "/serviceplay/spotify/" in final_writes[1]
    assert final_writes[2] == "audio/7/position/45.0"
    assert all(socket.closed for socket in sockets)
    assert not entity._audio_commands.source_fences
    assert entity._audio_metadata.get(7).source == "Spotify"
    assert entity._audio_metadata.get(7).position == 45
    assert shortcuts == []
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()
