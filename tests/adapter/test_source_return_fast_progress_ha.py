"""Ordinary sub-50ms return feedback is not a conflicting seek."""
# ruff: noqa: ANN001, ANN202, D103, F811, INP001, PLR0913, S101, SLF001
from datetime import timedelta

import pytest
from homeassistant.exceptions import HomeAssistantError
from test_audioserver_ha import audio_setup  # noqa: F401
from test_audioserver_playback import rsa_key  # noqa: F401
from test_native_return_progress_wire_ha import native_return_harness


@pytest.mark.asyncio
@pytest.mark.parametrize("spotify", [False, True], ids=["library", "spotify"])
@pytest.mark.parametrize("progress", [0.005, 0.006], ids=["ordinary", "off-clock-rejected"])
async def test_ordinary_fast_feedback_during_return_seek_auth_is_not_a_new_seek(
    hass, audio_setup, monkeypatch, rsa_key, freezer, spotify, progress,
):
    samples = []

    async def advance(entity, emit, target):
        original = entity._audio_metadata.get(7)
        now = original.position_updated_at + timedelta(milliseconds=5)
        freezer.move_to(now)
        await emit({**target, "time": original.position + progress})
        samples.extend([original, entity._audio_metadata.get(7)])

    entity, sockets, _, shortcuts = await native_return_harness(
        hass, audio_setup, monkeypatch, rsa_key, spotify=spotify, tick=False,
        auth_change=advance,
    )
    error = None
    try:
        await hass.services.async_call("media_player", "select_source", {
            "entity_id": entity.entity_id,
            "source": "Spotify" if spotify else "Local Library",
        }, blocking=True)
    except HomeAssistantError as exc:
        error = exc
    writes = [m for s in sockets for m in s.sent if m.startswith("audio/7/")]
    assert len(samples) == 2
    assert (samples[1].position_updated_at - samples[0].position_updated_at).total_seconds() == 0.005
    assert error is None, {
        "failure": getattr(entity, "_audio_last_source_failure", None),
        "writes": writes,
    }
    assert writes[-1] == "audio/7/position/45.0"
    assert len(writes) == 2
    assert shortcuts == []
    assert entity._audio_metadata.get(7).position == 45
    assert all(s.closed for s in sockets)
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()
