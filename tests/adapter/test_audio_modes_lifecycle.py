"""Independent real-HA extra controls. Synthetic I/O only; no live APIs."""

# ruff: noqa: F811
import asyncio
import pytest
from homeassistant.exceptions import HomeAssistantError
from test_audio_modes_ha import mode_harness, request
from test_audioserver_ha import audio_setup  # noqa: F401
from test_audioserver_playback import rsa_key  # noqa: F401


@pytest.mark.parametrize("operation,value", [("shuffle", True), ("repeat", "one")])
@pytest.mark.parametrize("change", ["track", "permission", "missing"])
async def test_transient_loss_during_auth_cannot_revive_request(
    hass, audio_setup, monkeypatch, rsa_key, operation, value, change
):
    h = await mode_harness(hass, audio_setup, monkeypatch, rsa_key)

    async def hook():
        delta = {
            "track": {"audiopath": "library:local:track:other"},
            "permission": {"pbr": 0},
            "missing": {"plshuffle": None, "plrepeat": None},
        }[change]
        await h.emit(h.rows[7] | delta)
        await h.emit(h.rows[7])

    h.state.auth_hook = hook
    with pytest.raises(HomeAssistantError):
        await request(hass, h, 7, operation, value)
    assert h.writes == []
    assert all(s.closed for s in h.sockets)


@pytest.mark.parametrize("operation,value", [("shuffle", True), ("repeat", "one")])
async def test_stop_supersedes_authenticating_mode_without_mode_write(
    hass, audio_setup, monkeypatch, rsa_key, operation, value
):
    h = await mode_harness(hass, audio_setup, monkeypatch, rsa_key)
    entered, hold = asyncio.Event(), asyncio.Event()

    async def hook():
        h.state.auth_hook = None
        entered.set()
        await hold.wait()

    h.state.auth_hook = hook
    old = asyncio.create_task(request(hass, h, 7, operation, value))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        # Existing stop path uses Miniserver transport; do not make a fake mode
        # socket accept an unmodelled native playback command.
        await hass.services.async_call(
            "media_player",
            "media_stop",
            {"entity_id": h.entities[7].entity_id},
            blocking=True,
        )
        result = await asyncio.wait_for(asyncio.gather(old, return_exceptions=True), 2)
        assert isinstance(result[0], asyncio.CancelledError)
        assert h.writes == []
        assert all(s.closed for s in h.sockets)
    finally:
        hold.set()
        if not old.done():
            old.cancel()
        await asyncio.gather(old, return_exceptions=True)


@pytest.mark.parametrize("operation,value", [("shuffle", True), ("repeat", "one")])
async def test_preownership_cleanup_transient_loss_does_not_revive_mode(
    hass, audio_setup, monkeypatch, rsa_key, operation, value
):
    h = await mode_harness(hass, audio_setup, monkeypatch, rsa_key)
    started, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def predecessor():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
            await release.wait()

    # Model the existing shielded source/transport cleanup boundary with a
    # genuine pending task. No product method is replaced or bypassed.
    previous = asyncio.create_task(predecessor())
    await asyncio.wait_for(started.wait(), 1)
    h.entities[7]._source_task = previous
    task = asyncio.create_task(request(hass, h, 7, operation, value))
    try:
        await asyncio.wait_for(cancelled.wait(), 1)
        await h.emit(h.rows[7] | {"pbr": 0})
        await h.emit(h.rows[7])
        release.set()
        result = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 2)
        assert h.writes == [], (
            "Original mode request survived native capability loss during predecessor cleanup"
        )
        assert isinstance(result[0], (HomeAssistantError, asyncio.CancelledError))
    finally:
        release.set()
        for pending in [task, previous]:
            if not pending.done():
                pending.cancel()
        await asyncio.gather(task, previous, return_exceptions=True)


@pytest.mark.parametrize("operation,value", [("shuffle", True), ("repeat", "one")])
@pytest.mark.parametrize("transient", [False, True])
async def test_real_older_mode_cleanup_and_current_native_identity(
    hass, audio_setup, monkeypatch, rsa_key, operation, value, transient
):
    from test_audioserver_playback import SyntheticAudioSocket

    h = await mode_harness(hass, audio_setup, monkeypatch, rsa_key)
    entered, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def block_auth():
        h.state.auth_hook = None
        entered.set()
        await asyncio.Event().wait()

    original_exit = SyntheticAudioSocket.__aexit__

    async def slow_first_exit(socket, *args):
        if h.sockets and socket is h.sockets[0]:
            closing.set()
            await release.wait()
        await original_exit(socket, *args)

    monkeypatch.setattr(SyntheticAudioSocket, "__aexit__", slow_first_exit)
    h.state.auth_hook = block_auth
    older = asyncio.create_task(request(hass, h, 7, operation, value))
    newer = None
    try:
        await asyncio.wait_for(entered.wait(), 1)
        newer = asyncio.create_task(request(hass, h, 7, operation, value))
        await asyncio.wait_for(closing.wait(), 1)
        if transient:
            await h.emit(h.rows[7] | {"pbr": 0})
            await h.emit(h.rows[7])
        release.set()
        result = await asyncio.wait_for(
            asyncio.gather(newer, return_exceptions=True), 2
        )
        old_result = await asyncio.wait_for(
            asyncio.gather(older, return_exceptions=True), 2
        )
        assert isinstance(old_result[0], asyncio.CancelledError)
        if transient:
            assert h.writes == [], (
                "Newest mode intent survived capability loss while awaiting actual older mode socket cleanup"
            )
            assert isinstance(result[0], (HomeAssistantError, asyncio.CancelledError))
        else:
            assert result == [None]
            assert h.writes == [
                f"audio/7/{'shuffle/enable' if operation == 'shuffle' else 'repeat/3'}"
            ]
        assert all(s.closed for s in h.sockets)
    finally:
        release.set()
        for t in [older, newer]:
            if t is not None and not t.done():
                t.cancel()
        await asyncio.gather(
            *[t for t in [older, newer] if t is not None], return_exceptions=True
        )
