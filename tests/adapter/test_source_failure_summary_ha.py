"""Fixed ordinary warnings and actual errors through owning HA source entities."""
# Assertions, private guards, fixture shadowing and synthetic counts are intentional.
# ruff: noqa: S101, SLF001, F811, PLR2004, INP001

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import pytest
from homeassistant.exceptions import HomeAssistantError
from test_spotify_continuity_conflicts import _saved
from test_spotify_continuity_review import entity_boundary
from test_spotify_continuity import native
from test_audioserver_ha import audio_setup  # noqa: F401 - shared offline HA fixture
from test_native_source_return_ha import install_sources, library_row, RADIO

from custom_components.loxone.audio_radio import RadioTarget
from custom_components.loxone.pyloxone_api.audioserver import AudioCommandError
from custom_components.loxone.pyloxone_api import audioserver as wire

if TYPE_CHECKING:
    from collections.abc import Callable
    from homeassistant.core import HomeAssistant

LOGGER = "custom_components.loxone.media_player"


@pytest.mark.asyncio
async def test_ordinary_failure_retains_cause_before_translation(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A foreign owner prevents native writes and produces only a fixed warning."""
    entity, session, _snapshots, commands = await _saved(hass)
    session.current["device"]["id"] = "foreign-device-DO_NOT_LOG"
    caplog.set_level(logging.INFO, logger=LOGGER)
    handoffs_before = commands.async_spotify_handoff.await_count

    with pytest.raises(HomeAssistantError):
        await entity.async_select_source("Spotify")

    records = [r for r in caplog.records if r.name == LOGGER]
    assert len(records) == 1
    message = records[0].getMessage()
    assert message == "Audio source selection failed; no automatic retry was sent"
    assert "DO_NOT_LOG" not in message
    assert "audio_last_source_failure" not in entity.extra_state_attributes
    assert all(method == "GET" for method, _url, _kwargs in session.calls)
    commands.async_play_catalogue.assert_not_awaited()
    assert commands.async_spotify_handoff.await_count == handoffs_before


@pytest.mark.asyncio
async def test_ordinary_native_ambiguity_and_later_fence_keep_distinct_safe_causes(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No underlying exception text, media IDs or secrets escape fixed warnings."""
    entity, _session, snapshots, commands, _provider, _target = entity_boundary(hass, binding=None)
    snapshots[0] = native("tunein:station:before", mode="stop")
    target = entity._radio_catalogue._item(
        RadioTarget("station", "Synthetic", "world", audio_path="tunein:station:DO_NOT_LOG")
    )
    calls = []

    async def uncertain(
        _player: int,
        _service: str,
        _path: str,
        *,
        is_current: Callable[[], bool],
        on_send: Callable[[], None],
    ) -> None:
        assert is_current()
        on_send()
        calls.append(True)
        message = "https://secret.invalid/?token=DO_NOT_LOG"
        raise AudioCommandError(message)

    commands.async_play_radio_station.side_effect = uncertain
    caplog.set_level(logging.INFO, logger=LOGGER)
    for _ in range(2):
        with pytest.raises(HomeAssistantError):
            await entity.async_play_media(target.media_content_type, target.media_content_id)

    messages = [r.getMessage() for r in caplog.records if r.name == LOGGER]
    assert len(messages) == 2
    assert messages == ["Audio content selection failed; no automatic retry was sent"] * 2
    assert len(calls) == 2  # Two EXPLICIT requests, no automatic retry.
    assert 7 in commands.source_fences
    assert "DO_NOT_LOG" not in "\n".join(messages)
    assert "secret.invalid" not in "\n".join(messages)


@pytest.mark.asyncio
async def test_actual_ha_failed_source_state_keeps_safe_summary_with_logging_disabled(
    hass: HomeAssistant,
    audio_setup: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The service still raises and HA publishes no development failure state."""
    entity, emit, _calls = await install_sources(hass, audio_setup, monkeypatch)
    await emit(library_row())
    await emit({"playerid": 7, "mode": "play", "eventype": 0, "audiopath": RADIO})
    attempts = []

    async def failed(
        _self: Any,
        command: str,
        _key: str,
        *,
        is_current: Callable[[], bool],
        on_send: Callable[[], None],
        **_kwargs: Any,
    ) -> None:
        assert is_current()
        on_send()
        attempts.append(command)
        message = "Audio playback failed; no fallback or automatic retry was sent"
        raise AudioCommandError(message)

    monkeypatch.setattr(wire.AudioServerCommands, "_async_request", failed)
    caplog.set_level(logging.ERROR, logger=LOGGER)
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
    await hass.async_block_till_done()

    state = hass.states.get(entity.entity_id)
    assert "audio_last_source_failure" not in state.attributes
    assert len(attempts) == 1
    assert not [record for record in caplog.records if record.name == LOGGER]
