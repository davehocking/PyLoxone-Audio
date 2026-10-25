"""Review24 account-unrelated native no-ops and radio-only clock ownership."""

# ruff: noqa: S101, INP001, ANN001, D103, SLF001
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch
from homeassistant.util import dt as dt_util

import pytest
from homeassistant.exceptions import HomeAssistantError
from test_spotify_continuity import NEXT, native
from test_spotify_continuity_conflicts import _saved
from custom_components.loxone.audio_radio import RADIO_MEDIA_TYPE, RadioTarget


@pytest.mark.asyncio
@pytest.mark.parametrize("guard", ["none", "generation", "removed", "uncertainty", "native-change"])
async def test_other_native_account_active_noop_does_not_refresh_older_history(hass, guard):
    entity, session, snapshots, commands = await _saved(hass)
    session.calls.clear()
    target = entity._radio_catalogue.source_choices["Spotify"]
    active_path = "spotify@native-b:playlist:" + "C" * 22
    target = replace(target, folder=active_path, audio_path=active_path, account="native-b")
    label = "Spotify · native-b · native-b"
    entity._radio_catalogue.source_choices[label] = target
    commands.async_service_accounts.return_value = [
        *commands.async_service_accounts.return_value,
        {"cmd": "spotify", "id": "native-b", "user": "synthetic-user-b", "configerror": False},
    ]
    snapshots[0] = replace(native(), audio_path=NEXT, source_name="synthetic-user-b")
    before = snapshots[0]
    older = "spotify@native-b:playlist:" + "D" * 22
    commands.async_recent_sources.return_value = {"items": [{"audiopath": older, "type": 7, "title": "Older"}]}

    async def changed(_player, _service, _account, path, *, is_current, on_send) -> None:
        assert path == older
        assert is_current()
        on_send()
        snapshots[0] = replace(before, parent_id="spotify:playlist:" + "D" * 22)

    commands.async_play_catalogue.side_effect = changed
    if guard != "none":

        async def guarded_accounts() -> list[dict]:
            if guard == "generation":
                entity._source_generation+=1
            elif guard == "removed":
                entity._audio_removed = True
            elif guard == "uncertainty":
                commands.announcement_fences[7]=object()
            else:
                snapshots[0] = replace(before, parent_id="spotify:playlist:" + "E" * 22)
            return commands.async_service_accounts.return_value

        commands.async_service_accounts.side_effect = guarded_accounts
        with pytest.raises(HomeAssistantError):
            await entity.async_select_source(label)
        assert not session.calls
        commands.async_play_catalogue.assert_not_awaited()
        commands.async_recent_sources.assert_not_awaited()
        if guard == "uncertainty":
            assert commands.announcement_fences
        return
    try:
        await entity.async_select_source(label)
    except HomeAssistantError:
        assert commands.async_play_catalogue.await_count == 0, "Active B received native catalogue playback"
        raise
    assert not session.calls
    commands.async_play_catalogue.assert_not_awaited()
    commands.async_recent_sources.assert_not_awaited()
    assert snapshots[0] is before
    commands.async_spotify_handoff.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("delay", [4, 30, 89])
@pytest.mark.parametrize("station", ["same", "new"])
async def test_radio_only_actions_do_not_age_spotify_as_an_advancing_clock(hass, delay, station):
    entity, session, snapshots, commands = await _saved(hass)
    controller = entity._spotify_return
    controller.bookmark = replace(controller.bookmark, captured=controller.bookmark.captured - delay)
    saved = entity._radio_catalogue.source_session('Spotify')
    path = snapshots[0].audio_path if station == "same" else "tunein:station:synthetic-other"
    target = RadioTarget("station", "Radio", "world", audio_path=path)
    item = entity._radio_catalogue._item(target)
    clock=dt_util.utcnow()+timedelta(seconds=delay)
    with patch.object(dt_util,'utcnow',lambda:clock+timedelta()):
        await entity.async_play_media(RADIO_MEDIA_TYPE, item.media_content_id)
        assert entity._radio_catalogue.source_session('Spotify') is saved
        assert saved.position==13.264
        await entity.async_select_source("Spotify")
    assert all(method=='GET' for method,_,_ in session.calls)
    if station=='new' or delay==4:
        commands.async_spotify_handoff.assert_awaited_once()
        commands.async_play_catalogue.assert_not_awaited()
    else:
        # An old, unchanged radio frame is not fresh native-session evidence.
        # The exact retained item may still be attempted without aging its clock.
        commands.async_play_catalogue.assert_awaited_once()
        assert snapshots[0].position==saved.position==13.264


@pytest.mark.asyncio
async def test_radio_only_action_does_not_extend_expired_spotify_bookmark(hass):
    entity, session, snapshots, commands = await _saved(hass)
    controller = entity._spotify_return
    controller.bookmark = replace(controller.bookmark, captured=controller.bookmark.captured - 91)
    target = RadioTarget("station", "Radio", "world", audio_path=snapshots[0].audio_path)
    item = entity._radio_catalogue._item(target)
    await entity.async_play_media(RADIO_MEDIA_TYPE, item.media_content_id)
    await entity.async_select_source("Spotify")
    assert all(method == "GET" for method, _, _ in session.calls)
    commands.async_play_catalogue.assert_not_awaited()
    commands.async_spotify_handoff.assert_awaited_once()
