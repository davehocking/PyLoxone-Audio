"""Synthetic mutations of measured phase order; never live recordings or tokens."""

# ruff: noqa: S101, INP001, ANN001, ANN002, ANN003, ANN202, D103, PT018
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_spotify_continuity import NEXT, module
from test_spotify_continuity_activation import detached_boundary


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        "track",
        "context",
        "queue",
        "position",
        "shuffle",
        "repeat",
        "foreign-device",
        "unexpected-playing",
        "native-track",
        "native-account",
        "native-position",
        "native-stale",
    ],
)
async def test_changed_activation_never_sends_play_or_retries(hass, tmp_path, mutation):
    controller, session, snapshots, _, _ = await detached_boundary(hass, tmp_path)

    async def changed():
        if mutation == "track":
            session.current["item"]["uri"] = NEXT
        elif mutation == "context":
            session.current["context"] = None
        elif mutation == "queue":
            session.queue["queue"].append({"uri": NEXT})
        elif mutation == "position":
            session.current["progress_ms"] = 32556
        elif mutation == "shuffle":
            session.current["shuffle_state"] = True
        elif mutation == "repeat":
            session.current["repeat_state"] = "off"
        elif mutation == "foreign-device":
            session.current["device"]["id"] = "foreign-receiver"
        elif mutation == "unexpected-playing":
            session.current["is_playing"] = True
        elif mutation == "native-track":
            snapshots[0] = replace(snapshots[0], audio_path=NEXT)
        elif mutation == "native-account":
            snapshots[0] = replace(snapshots[0], source_name="different-user")
        elif mutation == "native-position":
            snapshots[0] = replace(snapshots[0], position=32.556)
        else:
            snapshots[0] = replace(snapshots[0], received_at=snapshots[0].received_at.replace(year=2001))

    session.after_transfer = changed
    with pytest.raises((module().AudioCommandError, ValueError)):
        await controller.async_resume(lambda: True)
    writes = [c for c in session.calls if c[0] == "PUT"]
    assert len(writes) == 1 and writes[0][1].endswith("/me/player")
    assert controller.uncertain
    with pytest.raises(module().AudioCommandError):
        await controller.async_resume(lambda: True)
    assert len([c for c in session.calls if c[0] == "PUT"]) == 1


@pytest.mark.asyncio
async def test_long_playing_origin_is_not_eligible_for_large_rewind(hass, tmp_path):
    controller, session, _, _, _ = await detached_boundary(hass, tmp_path)
    controller.bookmark = replace(controller.bookmark, progress_ms=120000)
    with pytest.raises(module().AudioCommandError):
        await controller.async_resume(lambda: True)
    assert session.transfer_count == 1
    assert not any(c[1].endswith("/play") for c in session.calls if c[0] == "PUT")


@pytest.mark.asyncio
async def test_transfer_transport_replay_is_blocked_before_second_send(hass, tmp_path):
    controller, session, _, _, _ = await detached_boundary(hass, tmp_path)
    original = session.async_request

    async def replay(method, url, **kwargs):
        if method == "PUT" and url.endswith("/me/player"):
            middleware = kwargs["middlewares"][0]

            async def twice(request, handler):
                await middleware(request, handler)
                return await middleware(request, handler)

            kwargs["middlewares"] = (twice,)
        return await original(method, url, **kwargs)

    session.async_request = replay
    with pytest.raises(module().AudioCommandError):
        await controller.async_resume(lambda: True)
    assert session.transfer_count == 1 and controller.uncertain


@pytest.mark.asyncio
async def test_ambiguous_transfer_consumes_marker_without_play_or_native_replay(hass, tmp_path):
    controller, session, _, _, _ = await detached_boundary(hass, tmp_path)

    async def disconnect():
        message = "synthetic disconnect after dispatch"
        raise ConnectionResetError(message)

    session.after_transfer = disconnect
    with pytest.raises(ConnectionResetError):
        await controller.async_resume(lambda: True)
    assert session.transfer_count == 1 and len(list(session.journal.glob("*.json"))) == 1
    with pytest.raises(module().AudioCommandError):
        await controller.async_resume(lambda: True)
    assert session.transfer_count == 1 and controller.uncertain


@pytest.mark.asyncio
async def test_cancel_after_marker_before_request_never_dispatches(hass, tmp_path, monkeypatch):
    controller, session, _, _, _ = await detached_boundary(hass, tmp_path)
    original = hass.async_add_executor_job

    async def invalidating(*args):
        value = await original(*args)
        controller.invalidate()
        return value

    monkeypatch.setattr(hass, "async_add_executor_job", invalidating)
    with pytest.raises(module().AudioCommandError):
        await controller.async_resume(lambda: True)
    assert session.transfer_count == 0 and controller.uncertain
    assert len(list(session.journal.glob("*.json"))) == 1


@pytest.mark.asyncio
async def test_profile_rechecked_after_activation_before_play(hass, tmp_path):
    controller, session, _, _, _ = await detached_boundary(hass, tmp_path)
    original = session.async_request

    async def profile(method, url, **kwargs):
        if method == "GET" and url.endswith("/me") and session.transfer_count:
            return SimpleNamespace(
                status=200, json=AsyncMock(return_value={"id": "different-owner"}), release=lambda: None
            )
        return await original(method, url, **kwargs)

    session.async_request = profile
    with pytest.raises(module().AudioCommandError):
        await controller.async_resume(lambda: True)
    assert session.transfer_count == 1
    assert not any(c[1].endswith("/play") for c in session.calls if c[0] == "PUT")
