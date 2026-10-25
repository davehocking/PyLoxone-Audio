"""Losing observed provider identity must not be rehabilitated by healthy reads."""

# ruff: noqa: S101, INP001, ANN001, ANN003, ANN202, D103, SLF001, PLR2004, PT018
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError
from test_spotify_continuity import module, native
from test_spotify_continuity_activation import ActivationSession, detached_boundary
from test_spotify_continuity_review import entity_boundary

from custom_components.loxone.audio_radio import RADIO_MEDIA_TYPE, RadioTarget
from custom_components.loxone.pyloxone_api.audioserver import AudioCommandError


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["second-match", "native-not-ready", "final-playback"])
@pytest.mark.parametrize("recover", [False, True], ids=["persists", "later-healthy"])
async def test_observed_provider_loss_consumes_real_entity_attempt(hass, tmp_path, phase, recover):
    entity, original, snapshots, commands, provider, _ = entity_boundary(hass)
    hass.config.config_dir = str(tmp_path)
    session = ActivationSession(original, Path(hass.config.path(".storage", "pyloxone_spotify_return_dispatch")))
    provider.runtime_data.session = session
    original_radio = commands.async_play_radio_station.side_effect

    async def radio(*args, **kwargs):
        await original_radio(*args, **kwargs)
        session.current = None

    commands.async_play_radio_station = AsyncMock(side_effect=radio)
    item = entity._radio_catalogue._item(
        RadioTarget("station", "Synthetic radio", "world", audio_path="tunein:station:synthetic")
    )
    # Preserve dormant helper controls directly, not as entity return policy.
    await entity._spotify_return.async_capture(lambda:True)
    await entity.async_play_media(RADIO_MEDIA_TYPE, item.media_content_id)
    controller = entity._spotify_return
    assert controller.bookmark is not None and session.current is None
    reads = 0
    lost = False
    plays = []
    original_request = session.async_request

    async def delayed_native():
        snapshots[0] = native("tunein:station:synthetic", mode="play")

    if phase == "native-not-ready":
        session.after_transfer = delayed_native

    async def request(method, url, **kwargs):
        nonlocal reads, lost
        if method == "GET" and url.endswith("/me/player") and session.transfer_count:
            reads += 1
            target = 3 if phase == "final-playback" else 2
            if reads == target or (lost and not recover):
                lost = True
                return SimpleNamespace(status=204, release=lambda: None)
            if phase == "native-not-ready" and reads > target:
                snapshots[0] = native(mode="stop")
        return await original_request(method, url, **kwargs)

    session.async_request = request
    original_put = session.on_put

    async def play():
        plays.append(True)
        await original_put()

    session.on_put = play
    with pytest.raises(AudioCommandError):
        await controller.async_resume(lambda:True)
    assert lost and session.transfer_count == 1 and plays == []
    assert controller.uncertain
    commands.async_play_catalogue.assert_not_awaited()
    # Restore healthy evidence and retry: consumed runtime and disk fences remain.
    snapshots[0] = native(mode="stop")
    session.async_request = original_request
    with pytest.raises(AudioCommandError):
        await controller.async_resume(lambda:True)
    assert session.transfer_count == 1 and plays == []
    commands.async_play_catalogue.assert_not_awaited()
    for key in tuple(hass.data):
        if isinstance(key, str) and key.startswith("pyloxone_spotify_return"):
            hass.data.pop(key)
    await module().async_restore_dispatch_fences(hass)
    assert module().spotify_room_uncertain(hass, controller.room, controller.player)


@pytest.mark.asyncio
async def test_initial_provider_latency_before_any_identity_observation_remains_bounded(hass, tmp_path):
    controller, session, _, _, _ = await detached_boundary(hass, tmp_path)
    reads = 0
    original_request = session.async_request

    async def request(method, url, **kwargs):
        nonlocal reads
        if method == "GET" and url.endswith("/me/player") and session.transfer_count:
            reads += 1
            if reads == 1:
                return SimpleNamespace(status=204, release=lambda: None)
        return await original_request(method, url, **kwargs)

    session.async_request = request
    await controller.async_resume(lambda: True)
    assert session.transfer_count == 1 and not controller.uncertain and controller.bookmark is None
    assert len([c for c in session.calls if c[0] == "PUT" and c[1].endswith("/play")]) == 1
