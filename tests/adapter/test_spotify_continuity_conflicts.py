"""Synthetic review13 positive-state conflicts precede capability fallback."""

# ruff: noqa: S101, INP001, ANN001, ANN202, D103, SLF001
from dataclasses import replace
import logging

import pytest
from homeassistant.exceptions import HomeAssistantError
from test_spotify_continuity import NEXT, TRACK, native
from test_spotify_continuity_review import entity_boundary
from custom_components.loxone.audio_radio import RadioTarget
from custom_components.loxone.pyloxone_api.audioserver import AudioCommandError


async def _saved(hass):
    entity, session, snapshots, commands, _, old = entity_boundary(hass)
    await entity._spotify_return.async_capture(lambda: True)
    # Legacy helper capture remains independently tested. The entity return
    # uses the sole qualified last-success record, not the removed cache.
    entity._radio_catalogue._source_accounts = commands.async_service_accounts.return_value
    entity._radio_catalogue.remember_source(snapshots[0])
    snapshots[0] = native("tunein:station:synthetic")
    session.current["is_playing"] = False
    return entity, session, snapshots, commands


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["paused", "204"])
@pytest.mark.parametrize("change", ["track", "context", "progress", "account"])
async def test_saved_bookmark_never_masks_changed_native_spotify(hass, provider, change):
    entity, session, snapshots, commands = await _saved(hass)
    changes = {
        "track": {"audio_path": NEXT},
        "context": {"parent_id": "spotify:playlist:" + "D" * 22},
        "progress": {"position": 40.0},
        "account": {"source_name": "another-native-owner"},
    }
    snapshots[0] = replace(native(mode="pause"), **changes[change])
    if provider == "204":
        session.current = None
    if change in ("context", "progress", "track"):
        # Optional historical context/clock cannot veto the existing session.
        await entity.async_select_source("Spotify")
        commands.async_spotify_handoff.assert_awaited_once()
        assert snapshots[0].parent_id==changes[change].get('parent_id',native().parent_id)
        assert snapshots[0].position==changes[change].get('position',native().position)
        assert snapshots[0].audio_path==changes[change].get('audio_path',TRACK)
    else:
        with pytest.raises(HomeAssistantError):
            await entity.async_select_source("Spotify")
    assert all(method == "GET" for method, _, _ in session.calls)
    commands.async_play_catalogue.assert_not_awaited()
    commands.async_play_radio_station.assert_not_awaited()


@pytest.mark.asyncio
async def test_already_active_new_native_content_is_noop_and_retires_old_bookmark(hass):
    entity, session, snapshots, commands = await _saved(hass)
    snapshots[0] = replace(native(), audio_path=NEXT)
    session.current["item"]["uri"] = NEXT
    session.current["is_playing"] = True
    await entity.async_select_source("Spotify")
    # Dormant helper state is not another entity authority or a prerequisite.
    assert entity._radio_catalogue.source_session('Spotify').audio_path==NEXT
    assert snapshots[0].audio_path == NEXT
    assert all(method == "GET" for method, _, _ in session.calls)
    commands.async_play_catalogue.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["initial", "final", "capture-final"])
@pytest.mark.parametrize(("field", "value"), [("progress_ms", 40000), ("shuffle_state", True), ("repeat_state", "off")])
async def test_restriction_cannot_hide_positive_position_or_flags_change(hass, phase, field, value):
    if phase == "capture-final":
        entity, session, _, commands, _, _ = entity_boundary(hass)

        async def after_first_read(url):
            if url.endswith("/me/player"):
                session.current[field] = value
                session.current["device"]["is_restricted"] = True

        session.on_read = after_first_read
        item = entity._radio_catalogue._item(
            RadioTarget("station", "Radio", "world", audio_path="tunein:station:synthetic")
        )
        operation = entity._spotify_return.async_capture(lambda:True)
    else:
        entity, session, _, commands = await _saved(hass)

        async def change() -> None:
            session.current[field] = value
            session.current["device"]["is_restricted"] = True

        if phase == "final":
            session.ensure.side_effect = change
        else:
            await change()
        operation = entity._spotify_return.async_resume(lambda:True)
    with pytest.raises(AudioCommandError):
        await operation
    assert any(url.endswith("/me/player") for _, url, _ in session.calls)
    assert all(method == "GET" for method, _, _ in session.calls)
    commands.async_play_catalogue.assert_not_awaited()
    commands.async_play_radio_station.assert_not_awaited()


@pytest.mark.asyncio
async def test_initial_capture_restriction_cannot_hide_native_position_conflict(hass):
    entity, session, _, commands, _, _ = entity_boundary(hass)
    session.current["progress_ms"] = 40000
    session.current["device"]["is_restricted"] = True
    item = entity._radio_catalogue._item(
        RadioTarget("station", "Radio", "world", audio_path="tunein:station:synthetic")
    )
    with pytest.raises(AudioCommandError):
        await entity._spotify_return.async_capture(lambda:True)
    assert any(url.endswith("/me/player") for _, url, _ in session.calls)
    assert all(method == "GET" for method, _, _ in session.calls)
    commands.async_play_radio_station.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("current", [None, {}, {"uri": "malformed"}])
async def test_malformed_queue_current_cannot_hide_positive_upcoming_conflict(hass, current):
    entity, session, _, commands = await _saved(hass)
    session.queue["currently_playing"] = current
    session.queue["queue"][0] = {"uri": TRACK}
    with pytest.raises(AudioCommandError):
        await entity._spotify_return.async_resume(lambda:True)
    assert any(url.endswith("/me/player/queue") for _, url, _ in session.calls)
    assert all(method == "GET" for method, _, _ in session.calls)
    commands.async_play_catalogue.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("capability", ["restricted-initial", "restricted-final", "malformed-current"])
async def test_capability_only_loss_without_positive_conflict_stays_quiet(hass, caplog, capability):
    entity, session, _, commands = await _saved(hass)
    injected=[]
    if capability == "restricted-initial":
        session.current["device"]["is_restricted"] = True
    elif capability == "restricted-final":

        async def restrict(url) -> None:
            if url.endswith('/me'):
                injected.append(url)
                session.current["device"]["is_restricted"] = True

        session.on_read = restrict
    else:
        session.queue["currently_playing"] = None
    await entity.async_select_source("Spotify")
    if capability=='restricted-final':assert len(injected)==1
    commands.async_spotify_handoff.assert_awaited_once()
    commands.async_play_catalogue.assert_not_awaited()
    assert all(method == "GET" for method, _, _ in session.calls)
    assert not [
        r for r in caplog.records if r.levelno >= logging.WARNING and r.name.startswith("custom_components.loxone")
    ]
