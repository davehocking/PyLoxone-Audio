"""
Qualified source proof must not starve behind unrelated native broadcasts.

Synthetic identities and independently decrypted native authentication; the HA
service/entity, passive receiver, source coordinator and transport are real.
"""
# HA fixtures, literal wire counts and lifecycle access are intentional.
# ruff: noqa: S101, INP001, F401, F811, SLF001, PLR2004
from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import pytest
from homeassistant.exceptions import HomeAssistantError
from test_audioserver_ha import audio_setup
from test_audioserver_playback import rsa_key
from test_native_return_progress_wire_ha import native_return_harness

from custom_components.loxone.pyloxone_api import audioserver as wire

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


@pytest.mark.asyncio
async def test_exact_library_return_proof_settles_despite_ready_unrelated_broadcasts(
    hass: HomeAssistant,
    audio_setup: Any,
    monkeypatch: pytest.MonkeyPatch,
    rsa_key: Any,
) -> None:
    """Fresh exact source proof is sufficient even while recv stays readable."""
    entity, sockets, _samples, shortcuts = await native_return_harness(
        hass, audio_setup, monkeypatch, rsa_key,
        spotify=False, tick=False, source_echo=False,
    )
    original_connect = wire.connect
    reads = []

    def connect(*args: Any, **kwargs: Any) -> Any:
        socket = original_connect(*args, **kwargs)
        original_recv = socket.recv

        async def recv() -> str:
            if (
                len(sockets) == 1 and socket.queue.empty()
                and any(message.startswith("audio/7/") for message in socket.sent)
            ):
                reads.append(None)
                return json.dumps({"audio_event": [{"playerid": 999, "mode": "play"}]})
            return await original_recv()

        socket.recv = recv
        return socket

    monkeypatch.setattr(wire, "connect", connect)
    error = None
    try:
        await hass.services.async_call(
            "media_player", "select_source",
            {"entity_id": entity.entity_id, "source": "Local Library"}, blocking=True,
        )
    except HomeAssistantError as exc:
        error = exc
    sent = [message for socket in sockets for message in socket.sent if message.startswith("audio/7/")]
    assert shortcuts == []
    assert all(socket.closed for socket in sockets)
    assert reads, "The command socket must actually be readable with unrelated events"
    assert error is None, {
        "error": str(error),
        "native_writes": sent, "unrelated_reads": len(reads),
    }
    assert len(sent) == 2
    assert sent[-1] == "audio/7/position/45.0"
    assert entity._audio_metadata.get(7).position == 45
    assert not entity._audio_commands.source_fences
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


def install_ready_frames(monkeypatch: pytest.MonkeyPatch, sockets: list[Any], kind: str) -> list[None]:
    """Keep only the dispatched source socket readable, never fake a proof."""
    original_connect = wire.connect
    reads = []

    def connect(*args: Any, **kwargs: Any) -> Any:
        socket = original_connect(*args, **kwargs)
        original_recv = socket.recv

        async def recv() -> Any:
            commands = [message for message in socket.sent if message.startswith("audio/7/")]
            if len(sockets) == 1 and commands and socket.queue.empty():
                reads.append(None)
                if kind == "rejected":
                    return json.dumps({"command": commands[0], "error": "synthetic rejection"})
                if kind == "disconnect":
                    message = "synthetic closed socket"
                    raise OSError(message)
                return {
                    "event": '{"audio_event":[{"playerid":999,"mode":"play"}]}',
                    "foreign-error": '{"command":"audio/999/library/play/foreign","error":"foreign rejection"}',
                    "sync": '{"audio_sync_event":[{"playerid":999,"mode":"stop"}]}',
                    "malformed": "not JSON",
                    "array": "[]",
                    "binary": b"unrelated binary frame",
                }[kind]
            return await original_recv()

        socket.recv = recv
        return socket

    monkeypatch.setattr(wire, "connect", connect)
    return reads


@pytest.mark.asyncio
@pytest.mark.parametrize("spotify", [False, True], ids=["library", "spotify"])
@pytest.mark.parametrize("tick", [False, True], ids=["static", "ordinary-progress"])
@pytest.mark.parametrize("kind", ["event", "sync", "foreign-error", "malformed", "array", "binary"])
async def test_shared_return_proof_is_not_starved_by_other_ready_frames(  # noqa: PLR0913
    hass: HomeAssistant,
    audio_setup: Any,
    monkeypatch: pytest.MonkeyPatch,
    rsa_key: Any,
    *, spotify: bool, tick: bool, kind: str,
) -> None:
    """All existing proof requirements survive either source and normal progress."""
    entity, sockets, samples, shortcuts = await native_return_harness(
        hass, audio_setup, monkeypatch, rsa_key,
        spotify=spotify, tick=tick, source_echo=False,
    )
    reads = install_ready_frames(monkeypatch, sockets, kind)
    await hass.services.async_call(
        "media_player", "select_source",
        {"entity_id": entity.entity_id, "source": "Spotify" if spotify else "Local Library"}, blocking=True,
    )
    sent = [message for socket in sockets for message in socket.sent if message.startswith("audio/7/")]
    assert reads
    assert shortcuts == []
    assert len(sent) == 2
    assert sent[-1] == "audio/7/position/45.0"
    assert all(socket.closed for socket in sockets)
    assert not entity._audio_commands.source_fences
    if tick:
        assert samples[1].position > samples[0].position
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("conflict", ["missing", "parent", "track", "account", "event"])
async def test_ready_frames_never_substitute_for_missing_exact_source_proof(
    hass: HomeAssistant,
    audio_setup: Any,
    monkeypatch: pytest.MonkeyPatch,
    rsa_key: Any,
    conflict: str,
) -> None:
    """Playing another identity or interruptions remain ambiguous and fenced."""
    feedback = {
        "missing": False,
        "parent": {"parent": {"id": "library:local:folder:foreign"}},
        "track": {"audiopath": "library:local:track:foreign"},
        "account": {"sourceName": "Foreign synthetic user"},
        "event": {"eventype": 3},
    }[conflict]
    spotify = conflict == "account"
    entity, sockets, _samples, _shortcuts = await native_return_harness(
        hass, audio_setup, monkeypatch, rsa_key,
        spotify=spotify, tick=False, source_echo=False, source_feedback=feedback,
    )
    reads = install_ready_frames(monkeypatch, sockets, "event")
    service = {"entity_id": entity.entity_id, "source": "Spotify" if spotify else "Local Library"}
    if conflict in {"parent", "track"}:
        # Same-provider playback confirms a source return, independent of saved content.
        await hass.services.async_call("media_player", "select_source", service, blocking=True)
        sent = [message for socket in sockets for message in socket.sent if message.startswith("audio/7/")]
        assert len(sent) == (2 if conflict == "parent" else 1)
        assert not entity._audio_commands.source_fences
        assert all(socket.closed for socket in sockets)
        return
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("media_player", "select_source", service, blocking=True)
    sent = [message for socket in sockets for message in socket.sent if message.startswith("audio/7/")]
    assert reads
    assert len(sent) == 1
    assert "/position/" not in sent[0]
    assert not hasattr(entity, "_audio_last_source_failure")
    assert 7 in entity._audio_commands.source_fences
    # First request failed honestly; without a NEW explicit request there is
    # no automatic replay. Newest-intent regression covers a subsequent choice.
    await hass.async_block_till_done()
    assert sent == [message for socket in sockets for message in socket.sent if message.startswith("audio/7/")]
    assert all(socket.closed for socket in sockets)
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["rejected", "disconnect"])
async def test_ready_exact_rejection_or_disconnect_wins_over_simultaneous_source_proof(
    hass: HomeAssistant,
    audio_setup: Any,
    monkeypatch: pytest.MonkeyPatch,
    rsa_key: Any,
    kind: str,
) -> None:
    """A known error is never upgraded by otherwise matching source feedback."""
    entity, sockets, _samples, _shortcuts = await native_return_harness(
        hass, audio_setup, monkeypatch, rsa_key,
        spotify=False, tick=False, source_echo=False,
    )
    reads = install_ready_frames(monkeypatch, sockets, kind)
    service = {"entity_id": entity.entity_id, "source": "Local Library"}
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("media_player", "select_source", service, blocking=True)
    sent = [message for socket in sockets for message in socket.sent if message.startswith("audio/7/")]
    assert reads
    assert len(sent) == 1
    assert "/position/" not in sent[0]
    assert 7 in entity._audio_commands.source_fences
    assert all(socket.closed for socket in sockets)
    # First request failed honestly; without a NEW explicit request there is
    # no automatic replay. Newest-intent regression covers a subsequent choice.
    await hass.async_block_till_done()
    assert sent == [message for socket in sockets for message in socket.sent if message.startswith("audio/7/")]


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["cancelled", "failed"])
async def test_failed_or_cancelled_proof_cannot_settle_a_readable_socket(outcome: str) -> None:
    """Honouring ready proof must consume its actual result, not just done()."""
    observation = asyncio.get_running_loop().create_future()
    if outcome == "cancelled":
        observation.cancel()
    else:
        observation.set_exception(wire.AudioCommandError("synthetic lost ownership"))

    class Socket:
        async def recv(self) -> str:
            return '{"audio_event":[]}'

    expected_error = asyncio.CancelledError if outcome == "cancelled" else wire.AudioCommandError
    with pytest.raises(expected_error):
        await asyncio.wait_for(
            wire.AudioServerCommands._command_echo(Socket(), "audio/7/library/play/synthetic", observation),
            timeout=1,
        )
