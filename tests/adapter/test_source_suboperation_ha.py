"""
Actual failure outcomes separate shared source send from corrective seek.

Actual HA service/entity/receiver and independently authenticated synthetic wire;
no household calls, provider activation or real media/configuration fixtures.
"""
# Literal wire counts and shared fixture imports are intentional.
# ruff: noqa: S101, INP001, F401, F811, SLF001, PLR2004
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import pytest
from homeassistant.exceptions import HomeAssistantError
from test_audioserver_ha import audio_setup
from test_audioserver_playback import rsa_key
from test_native_return_progress_wire_ha import native_return_harness

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

LOGGER = "custom_components.loxone.audio_diagnostics"


@pytest.mark.asyncio
async def test_failed_source_transport_is_identified_without_debug_or_replay(
    hass: HomeAssistant,
    audio_setup: Any,
    monkeypatch: pytest.MonkeyPatch,
    rsa_key: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Library-playing feedback cannot upgrade an unresolved source dispatch."""
    entity, sockets, _samples, _shortcuts = await native_return_harness(
        hass, audio_setup, monkeypatch, rsa_key,
        spotify=False, tick=False, source_echo=False,
        source_feedback={"audiopath": "spotify:track:wrong-provider"},
    )
    caplog.set_level(logging.ERROR, logger=LOGGER)
    service = {"entity_id": entity.entity_id, "source": "Local Library"}
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("media_player", "select_source", service, blocking=True)
    await hass.async_block_till_done()
    sent = [m for socket in sockets for m in socket.sent if m.startswith("audio/7/")]
    assert len(sent) == 1
    assert "/position/" not in sent[0]
    assert "audio_last_source_failure" not in hass.states.get(entity.entity_id).attributes
    assert 7 in entity._audio_commands.source_fences
    assert not [r for r in caplog.records if r.name == LOGGER]
    assert all(socket.closed for socket in sockets)
    # No automatic replay absent a new explicit request.
    await hass.async_block_till_done()
    assert sent == [m for socket in sockets for m in socket.sent if m.startswith("audio/7/")]


@pytest.mark.asyncio
@pytest.mark.parametrize("dispatched", [False, True], ids=["auth-guard-rejection", "missing-position-reply"])
async def test_corrective_seek_evidence_is_not_the_prior_source_send(  # noqa: PLR0913 - explicit HA/wire fixtures
    hass: HomeAssistant,
    audio_setup: Any,
    monkeypatch: pytest.MonkeyPatch,
    rsa_key: Any,
    caplog: pytest.LogCaptureFixture,
    *, dispatched: bool,
) -> None:
    """A latched action-wide attempt must not pretend this suboperation sent."""
    async def supersede(_entity: Any, emit: Any, target: dict[str, Any]) -> None:
        await emit({**target, "time": 75})

    entity, sockets, _samples, _shortcuts = await native_return_harness(
        hass, audio_setup, monkeypatch, rsa_key,
        spotify=False, tick=False, position_reply=False,
        auth_change=None if dispatched else supersede,
    )
    caplog.set_level(logging.ERROR, logger=LOGGER)
    service = {"entity_id": entity.entity_id, "source": "Local Library"}
    await hass.services.async_call("media_player", "select_source", service, blocking=True)
    await hass.async_block_till_done()
    sent = [m for socket in sockets for m in socket.sent if m.startswith("audio/7/")]
    # Both same-track progress and a missing optional reply preserve source success.
    assert len(sent) == 2
    assert sent[-1] == "audio/7/position/45.0"
    assert all(socket.closed for socket in sockets)
    assert not entity._audio_commands.source_fences
    assert getattr(entity, "_audio_last_source_failure", None) is None
    assert not [r for r in caplog.records if r.name == LOGGER]
