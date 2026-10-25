"""
Native source-return transport regression with independently decrypted auth.

Synthetic library/Spotify identities only; actual HA setup/services/event receiver
and actual AudioServerCommands request/guard/echo path, with no network sockets.
"""

# Test fixtures need HA/socket arguments and literal expected wire counts.
# ruff: noqa: S101, INP001, ANN001, ANN002, ANN202, ANN003, D103, F811, F401, SLF001, PLR0913, PLR2004
from __future__ import annotations

import asyncio
import json

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from test_audioserver_ha import audio_setup
from test_audioserver_playback import SyntheticAudioSocket, rsa_key
from test_native_source_return_ha import RADIO, install_sources, library_row

from custom_components.loxone.pyloxone_api import audioserver as wire


async def native_return_harness(
    hass,
    audio_setup,
    monkeypatch,
    rsa_key,
    *,
    spotify,
    tick,
    auth_change=None,
    source_echo=True,
    position_reply=True,
    source_feedback=True,
):
    """Replace only external socket and discovery; keep the actual request path."""
    real_request = wire.AudioServerCommands._async_request
    entity, emit, shortcut_calls = await install_sources(hass, audio_setup, monkeypatch, spotify=spotify)
    monkeypatch.setattr(wire.AudioServerCommands, "_async_request", real_request)
    entity._audio_commands._credentials = lambda: ("synthetic-user", "synthetic-active-token")
    entity._audio_commands._timeout = 1
    target = library_row(time=0)
    saved = library_row()
    if spotify:
        values = {
            "audiopath": "spotify:track:original",
            "parent": {"id": "spotify:playlist:original"},
            "sourceName": "Synthetic owner",
        }
        target.update(values)
        saved.update(values)
    sockets = []
    samples = []

    class Socket(SyntheticAudioSocket):
        async def send(self, message):
            if message.startswith("secure/authenticate/"):
                # The inherited socket independently decrypts RSA/AES credentials.
                await super().send(message)
                if len(sockets) == 2 and tick:
                    original = entity._audio_metadata.get(7)
                    await asyncio.sleep(0.25)
                    elapsed = (dt_util.utcnow() - original.position_updated_at).total_seconds()
                    await emit({**target, "time": original.position + elapsed})
                    samples.extend([original, entity._audio_metadata.get(7)])
                if len(sockets) == 2 and auth_change is not None:
                    await auth_change(entity, emit, target)
                return
            if message.startswith("audio/7/"):
                self.sent.append(message)
                if "/position/" in message:
                    value = float(message.rsplit("/", 1)[1])
                    await emit({**target, "time": value})
                    if position_reply:
                        self.queue.put_nowait(json.dumps({"position_result": [{"position": value}]}))
                else:
                    if source_feedback:
                        await emit({**target, **source_feedback} if isinstance(source_feedback, dict) else target)
                    if source_echo:
                        self.queue.put_nowait(json.dumps({"command": message}))
                return
            await super().send(message)

    def connect(*_args, **_kwargs):
        socket = Socket(rsa_key)
        sockets.append(socket)
        return socket

    monkeypatch.setattr(wire, "connect", connect)
    await emit(saved)
    await emit({"playerid": 7, "mode": "play", "eventype": 0, "audiopath": RADIO})
    return entity, sockets, samples, shortcut_calls


@pytest.mark.asyncio
@pytest.mark.parametrize("spotify", [False, True], ids=["library", "spotify"])
@pytest.mark.parametrize("tick", [False, True], ids=["static", "ordinary-progress"])
async def test_native_return_accepts_anchored_progress_during_corrective_seek_authentication(
    hass,
    audio_setup,
    monkeypatch,
    rsa_key,
    spotify,
    tick,
):
    entity, sockets, samples, shortcut_calls = await native_return_harness(
        hass,
        audio_setup,
        monkeypatch,
        rsa_key,
        spotify=spotify,
        tick=tick,
    )
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
    sent = [m for socket in sockets for m in socket.sent if m.startswith("audio/7/")]
    assert shortcut_calls == [], "Real transport must not use the earlier shortcut"
    assert all(socket.closed for socket in sockets)
    if tick:
        assert len(samples) == 2
        assert samples[1].position > samples[0].position
        assert samples[1].position_updated_at > samples[0].position_updated_at
    assert error is None, {
        "error": str(error),
        "failure": getattr(entity, "_audio_last_source_failure", None),
        "sent": sent,
        "sample_positions": [s.position for s in samples],
        "sample_times": [s.position_updated_at.isoformat() for s in samples],
    }
    assert len(sent) == 2
    assert sent[-1] == "audio/7/position/45.0"
    assert entity._audio_metadata.get(7).position == 45
    assert not entity._audio_commands.source_fences
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("spotify", [False, True], ids=["library", "spotify"])
@pytest.mark.parametrize(
    "change",
    [
        "seek",
        "rewind",
        "stop",
        "track",
        "source",
        "account",
        "context",
        "duration",
        "capability",
        "missing_progress",
        "event",
        "disconnect",
    ],
)
async def test_real_transport_never_restores_after_conflict_during_seek_auth(
    hass,
    audio_setup,
    monkeypatch,
    rsa_key,
    spotify,
    change,
):
    async def conflict(entity, emit, target):
        if change == "disconnect":
            entity._audio_metadata._client._receiver._reset()
            await hass.async_block_till_done()
            return
        changed = {
            "seek": {"time": 10.5},
            "rewind": {"time": -1},
            "stop": {"mode": "stop"},
            "track": {"audiopath": "library:local:track:newer"},
            "source": {"audiopath": "tunein:station:newer"},
            "account": {"sourceName": "Foreign synthetic user"},
            "context": {"parent": {"id": "library:local:folder:newer"}},
            "duration": {"duration": 100},
            "capability": {"pbr": 0},
            "missing_progress": {"time": None},
            "event": {"eventype": 3},
        }[change]
        await emit({**target, **changed})

    entity, sockets, _samples, shortcuts = await native_return_harness(
        hass,
        audio_setup,
        monkeypatch,
        rsa_key,
        spotify=spotify,
        tick=False,
        auth_change=conflict,
    )
    await hass.services.async_call(
        "media_player",
        "select_source",
        {
            "entity_id": entity.entity_id,
            "source": "Spotify" if spotify else "Local Library",
        },
        blocking=True,
    )
    sent = [m for socket in sockets for m in socket.sent if m.startswith("audio/7/")]
    # Legacy node IDs retained; only current target/capability gates the optional seek.
    may_seek = change in {"seek", "rewind", "context", "duration", "missing_progress"}
    assert len(sent) == (2 if may_seek else 1)
    assert "/position/" not in sent[0]
    assert shortcuts == []
    assert all(socket.closed for socket in sockets)


@pytest.mark.asyncio
async def test_library_uncertain_source_dispatch_is_not_a_position_suboperation(
    hass,
    audio_setup,
    monkeypatch,
    rsa_key,
):
    entity, sockets, _samples, _shortcuts = await native_return_harness(
        hass,
        audio_setup,
        monkeypatch,
        rsa_key,
        spotify=False,
        tick=False,
        source_echo=False,
        source_feedback={"audiopath": "spotify:track:wrong-provider"},
    )
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "media_player",
            "select_source",
            {
                "entity_id": entity.entity_id,
                "source": "Local Library",
            },
            blocking=True,
        )
    sent = [m for socket in sockets for m in socket.sent if m.startswith("audio/7/")]
    assert len(sent) == 1
    assert "/position/" not in sent[0]
    assert entity._audio_metadata.get(7).native_mode == "play"
    assert entity._audio_metadata.get(7).source == "Spotify"
    assert not hasattr(entity, "_audio_last_source_failure")
    assert 7 in entity._audio_commands.source_fences
    # No automatic replay. A second explicit request is now a NEW intent.
    await hass.async_block_till_done()
    assert sent == [m for socket in sockets for m in socket.sent if m.startswith("audio/7/")]


@pytest.mark.asyncio
@pytest.mark.parametrize("spotify", [False, True], ids=["library", "spotify"])
async def test_native_return_does_not_require_optional_source_echo_if_exact_postsend_proof_exists(
    hass,
    audio_setup,
    monkeypatch,
    rsa_key,
    spotify,
):
    entity, sockets, _samples, _shortcuts = await native_return_harness(
        hass,
        audio_setup,
        monkeypatch,
        rsa_key,
        spotify=spotify,
        tick=False,
        source_echo=False,
    )
    await hass.services.async_call(
        "media_player",
        "select_source",
        {
            "entity_id": entity.entity_id,
            "source": "Spotify" if spotify else "Local Library",
        },
        blocking=True,
    )
    assert len([m for s in sockets for m in s.sent if m.startswith("audio/7/")]) == 2
    assert not entity._audio_commands.source_fences


@pytest.mark.asyncio
async def test_library_missing_seek_reply_is_uncertain_not_false_success_or_replay(
    hass,
    audio_setup,
    monkeypatch,
    rsa_key,
):
    entity, sockets, _samples, _shortcuts = await native_return_harness(
        hass,
        audio_setup,
        monkeypatch,
        rsa_key,
        spotify=False,
        tick=False,
        position_reply=False,
    )
    await hass.services.async_call(
        "media_player",
        "select_source",
        {
            "entity_id": entity.entity_id,
            "source": "Local Library",
        },
        blocking=True,
    )
    sent = [m for socket in sockets for m in socket.sent if m.startswith("audio/7/")]
    assert len(sent) == 2
    assert sent[-1] == "audio/7/position/45.0"
    # Source succeeded; a missing optional seek reply creates no source failure/fence.
    assert not entity._audio_commands.source_fences
    assert all(socket.closed for socket in sockets)
    await hass.async_block_till_done()
    assert sent == [m for socket in sockets for m in socket.sent if m.startswith("audio/7/")]


@pytest.mark.asyncio
@pytest.mark.parametrize("spotify", [False, True], ids=["library", "spotify"])
@pytest.mark.parametrize("action", ["stop", "newer_selection", "remove", "cancel"])
async def test_actual_ha_newer_actions_cancel_return_pending_in_seek_authentication(
    hass,
    audio_setup,
    monkeypatch,
    rsa_key,
    spotify,
    action,
):
    ready, release = asyncio.Event(), asyncio.Event()
    feedback = {}

    async def held_auth(_entity, emit, target):
        feedback.update(emit=emit, target=target)
        ready.set()
        await release.wait()

    entity, sockets, _samples, _shortcuts = await native_return_harness(
        hass,
        audio_setup,
        monkeypatch,
        rsa_key,
        spotify=spotify,
        tick=False,
        auth_change=held_auth,
    )
    service = {"entity_id": entity.entity_id, "source": "Spotify" if spotify else "Local Library"}
    pending = asyncio.create_task(hass.services.async_call("media_player", "select_source", service, blocking=True))
    try:
        await asyncio.wait_for(ready.wait(), timeout=2)
        if action == "stop":
            await hass.services.async_call("media_player", "media_stop", {"entity_id": entity.entity_id}, blocking=True)
        elif action == "newer_selection":
            # New valid choice owns the action; old pending seek is cancelled.
            await hass.services.async_call("media_player", "select_source", service, blocking=True)
            await feedback["emit"]({**feedback["target"], "audiopath": "tunein:station:newer"})
        elif action == "remove":
            (entry,) = hass.config_entries.async_entries("loxone")
            assert await hass.config_entries.async_unload(entry.entry_id)
        else:
            pending.cancel()
        release.set()
        (result,) = await asyncio.gather(pending, return_exceptions=True)
        assert isinstance(result, (HomeAssistantError, asyncio.CancelledError))
        sent = [m for socket in sockets for m in socket.sent if m.startswith("audio/7/")]
        assert len(sent) == 1
        assert "/position/" not in sent[0]
        assert all(socket.closed for socket in sockets)
    finally:
        release.set()
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("spotify", [False, True], ids=["library", "spotify"])
async def test_transient_seek_cannot_be_rebased_to_a_later_matching_return_sample(
    hass,
    audio_setup,
    monkeypatch,
    rsa_key,
    spotify,
):
    async def conflict_then_revert(_entity, emit, target):
        await emit({**target, "time": 75})
        await emit(target)

    entity, sockets, _samples, _shortcuts = await native_return_harness(
        hass,
        audio_setup,
        monkeypatch,
        rsa_key,
        spotify=spotify,
        tick=False,
        auth_change=conflict_then_revert,
    )
    await hass.services.async_call(
        "media_player",
        "select_source",
        {
            "entity_id": entity.entity_id,
            "source": "Spotify" if spotify else "Local Library",
        },
        blocking=True,
    )
    sent = [m for socket in sockets for m in socket.sent if m.startswith("audio/7/")]
    # Same-track progress arbitration is explicitly retired.
    assert len(sent) == 2
    assert "/position/" not in sent[0]
