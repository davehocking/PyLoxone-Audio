"""Final independent-review regressions; synthetic state only, no household I/O."""

# ruff: noqa: S101, INP001, ANN001, D103, SLF001, PLC0415
import asyncio
from dataclasses import replace
from unittest.mock import ANY, AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from test_spotify_continuity import native, module
from test_spotify_continuity_review import entity_boundary
from custom_components.loxone.audio_radio import RADIO_MEDIA_TYPE


@pytest.mark.asyncio
async def test_unexpected_playing_provider_on_radio_never_resumes_or_falls_back(hass):
    entity, session, snapshots, commands, _, old = entity_boundary(hass)
    await entity._spotify_return.async_capture(lambda: True)
    entity._spotify_choice = ("Spotify", old)
    snapshots[0] = native("tunein:station:synthetic")
    # A valid existing native session wins; never substitute captured content.
    await entity.async_select_source("Spotify")
    commands.async_spotify_handoff.assert_awaited_once()
    assert all(call[0] == "GET" for call in session.calls)
    commands.async_play_catalogue.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["capture", "resume"])
async def test_missing_initial_native_identity_cannot_adopt_later_lock_wait_state(hass, phase):
    entity, session, snapshots, _, _, _ = entity_boundary(hass)
    controller = entity._spotify_return
    if phase == "resume":
        await controller.async_capture(lambda: True)
    snapshots[0] = None
    lock = controller._account["lock"]
    await lock.acquire()
    operation = controller.async_capture if phase == "capture" else controller.async_resume
    task = asyncio.create_task(operation(lambda: True))
    try:
        await asyncio.sleep(0)
        snapshots[0] = native()
    finally:
        lock.release()
    with pytest.raises(module().AudioCommandError):
        await task
    assert all(call[0] == "GET" for call in session.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["capture", "resume"])
async def test_newer_native_selection_during_account_lock_wait_is_rejected(hass, phase):
    entity, session, snapshots, _, _, _ = entity_boundary(hass)
    controller = entity._spotify_return
    if phase == "resume":
        await controller.async_capture(lambda: True)
        snapshots[0] = native("tunein:station:synthetic")
        session.current["is_playing"] = False
    lock = controller._account["lock"]
    await lock.acquire()
    operation = controller.async_capture if phase == "capture" else controller.async_resume
    task = asyncio.create_task(operation(lambda: True))
    try:
        await asyncio.sleep(0)
        snapshots[0] = replace(snapshots[0], audio_path="spotify:track:" + "E" * 22)
    finally:
        lock.release()
    with pytest.raises(module().AudioCommandError):
        await task
    assert all(call[0] == "GET" for call in session.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("after_dispatch", [False, True])
async def test_pause_cancels_pending_return_and_preserves_dispatched_uncertainty(hass, after_dispatch):
    entity, session, snapshots, commands, _, old = entity_boundary(hass)
    await entity._spotify_return.async_capture(lambda: True)
    entity._spotify_choice = ("Spotify", old)
    snapshots[0] = native("tunein:station:synthetic")
    session.current["is_playing"] = False
    entered, release = asyncio.Event(), asyncio.Event()
    commands.async_execute = AsyncMock()
    settled=[]
    async def handoff(_player,_account,*,is_current,on_send):
        assert is_current()
        on_send()
        entered.set()
        try:await release.wait()
        finally:settled.append(True)
    if after_dispatch:commands.async_spotify_handoff.side_effect=handoff

    async def hold(_url) -> None:
        if not after_dispatch or entity._spotify_return.uncertain:
            entered.set()
            await release.wait()

    session.on_read = hold
    session.update_native = False
    task = asyncio.create_task(entity.async_select_source("Spotify"))
    try:
        async with asyncio.timeout(1):
            await entered.wait()
        await entity.async_media_pause()
        commands.async_execute.assert_awaited_once_with(7, "pause", is_current=ANY)
        assert commands.async_execute.await_args.kwargs["is_current"]()
        assert entity._spotify_return.bookmark is None
        assert entity._spotify_return.uncertain is False
        if after_dispatch:assert settled==[True], 'Pause waits for old transport cleanup'
    finally:
        release.set()
        result = (await asyncio.gather(task, return_exceptions=True))[0]
    assert isinstance(result, (HomeAssistantError, asyncio.CancelledError))
    assert all(call[0]=='GET' for call in session.calls)
    assert commands.async_spotify_handoff.await_count==int(after_dispatch)
    commands.async_play_catalogue.assert_not_awaited()
    if after_dispatch:
        entity._spotify_return.close()
        recreated, _, _, new_commands, _, _ = entity_boundary(hass, None)
        await asyncio.sleep(0)
        new_commands.async_play_catalogue.assert_not_awaited()
        new_commands.async_spotify_handoff.assert_not_awaited()


@pytest.mark.asyncio
async def test_deliberate_searched_track_keeps_native_insertion_and_retires_bookmark(hass):
    entity, session, snapshots, commands, _, old = entity_boundary(hass)
    await entity._spotify_return.async_capture(lambda: True)
    entity._spotify_choice = ("Spotify", old)
    snapshots[0] = native("tunein:station:synthetic")
    path = "spotify@native-owner:track:" + "A" * 22
    target = replace(old, label="New track", folder=path, audio_path=path, is_context=False)
    item = entity._radio_catalogue._item(target)
    await entity.async_play_media(RADIO_MEDIA_TYPE, item.media_content_id)
    commands.async_play_catalogue.assert_awaited_once()
    assert commands.async_play_catalogue.await_args.args[3] == target.audio_path
    assert entity._spotify_return.bookmark is None
    assert snapshots[0].audio_path==native().audio_path
    assert all(call[0] == "GET" for call in session.calls)
