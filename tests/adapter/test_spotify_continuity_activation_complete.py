"""Incomplete observed activation evidence is terminal, including at real actions."""

# ruff: noqa: S101, INP001, ANN001, ANN003, ANN202, D103, SLF001, PLR2004, PLR0915, PT018
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError
from test_spotify_continuity import native
from test_spotify_continuity_activation import ActivationSession
from test_spotify_continuity_review import entity_boundary

from custom_components.loxone.audio_radio import RADIO_MEDIA_TYPE, RadioTarget
from custom_components.loxone.pyloxone_api.audioserver import AudioCommandError


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["profile", "native-accounts", "playback", "queue", "send-middleware"])
@pytest.mark.parametrize("recover", [False, True], ids=["unknown-persists", "later-healthy"])
async def test_entity_rejects_incomplete_activation_at_every_final_boundary(hass, tmp_path, phase, recover):
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
    # Direct legacy-helper coverage only; current departure never captures.
    await entity._spotify_return.async_capture(lambda:True)
    await entity.async_play_media(RADIO_MEDIA_TYPE, item.media_content_id)
    assert entity._spotify_return.bookmark is not None and session.current is None
    actual_plays = []
    healthy = None
    injected = False
    playback_reads = queue_reads = 0

    def inject():
        nonlocal injected, healthy
        assert not injected
        injected = True
        healthy = snapshots[0]
        assert healthy.position == 13.264 and healthy.native_mode == "stop"
        snapshots[0] = replace(healthy, position=None)

    def recover_later():
        if recover and injected:
            snapshots[0] = healthy

    async def observe(url):
        nonlocal playback_reads, queue_reads
        if not session.transfer_count:
            return
        if injected:
            recover_later()
            return
        if url.endswith("/me/player"):
            playback_reads += 1
        if url.endswith("/queue"):
            queue_reads += 1
        if ((phase == "profile" and url.endswith("/me"))
            or (phase == "playback" and url.endswith("/me/player") and playback_reads == 3)
            or (phase == "queue" and url.endswith("/queue") and queue_reads == 3)):
            inject()

    session.on_read = observe
    original_accounts = commands.async_service_accounts

    async def accounts():
        # Profile's incomplete frame must be rejected BEFORE this later healthy observation.
        recover_later()
        result = await original_accounts()
        if phase == "native-accounts" and session.transfer_count and not injected:
            inject()
        return result

    commands.async_service_accounts = AsyncMock(side_effect=accounts)
    original_request = session.async_request

    async def request(method, url, **kwargs):
        if method == "PUT" and url.endswith("/play"):
            if phase == "send-middleware":
                inject()
            else:
                recover_later()
        return await original_request(method, url, **kwargs)

    session.async_request = request
    original_put = session.on_put

    async def play_handler():
        actual_plays.append("play")
        await original_put()

    session.on_put = play_handler
    with pytest.raises(AudioCommandError):
        await entity._spotify_return.async_resume(lambda:True)
    assert injected
    assert session.transfer_count == 1
    assert actual_plays == []
    assert entity._spotify_return.uncertain
    commands.async_play_catalogue.assert_not_awaited()
    commands.async_play_radio_station.assert_awaited_once()
    # Even a healthy frame after failure must not rehabilitate this consumed attempt.
    snapshots[0] = healthy if recover else snapshots[0]
    with pytest.raises(AudioCommandError):
        await entity._spotify_return.async_resume(lambda:True)
    assert session.transfer_count == 1 and actual_plays == []
    commands.async_play_catalogue.assert_not_awaited()
