"""Independent review08 native-fallback races, using synthetic fixtures only."""

# ruff: noqa: S101, INP001, ANN001, D103, SLF001
import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock
from Crypto.PublicKey import RSA
import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from test_spotify_continuity import CONFIG, native
from test_spotify_continuity_review import entity_boundary
from test_audioserver_playback import SyntheticAudioSocket
from custom_components.loxone import media_player as media
from custom_components.loxone.audio_radio import RADIO_MEDIA_TYPE
from custom_components.loxone.pyloxone_api import audioserver as wire
from custom_components.loxone.spotify_continuity import spotify_room_uncertain


@pytest.mark.asyncio
@pytest.mark.parametrize("bookmark", ["missing", "expired", "displaced"])
async def test_independent_playback_is_conflict_before_bookmark_fallback(hass, bookmark):
    entity, session, snapshots, commands, _, old = entity_boundary(hass)
    controller = entity._spotify_return
    await controller.async_capture(lambda: True)
    if bookmark == "missing":
        controller.bookmark = None
    elif bookmark == "expired":
        controller.bookmark = replace(controller.bookmark, captured=controller.bookmark.captured - 100)
    else:
        controller._account["owner"] = object()
    snapshots[0] = native("tunein:station:synthetic")
    entity._radio_catalogue.async_source_selection = AsyncMock(
        return_value=entity._radio_catalogue._item(old).media_content_id
    )
    await entity.async_select_source("Spotify")
    commands.async_spotify_handoff.assert_awaited_once()
    assert snapshots[0].audio_path==session.current['item']['uri']
    commands.async_play_catalogue.assert_not_awaited()
    assert all(call[0] == "GET" for call in session.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("binding", [None, "configured"])
@pytest.mark.parametrize("change", ["stop", "source"])
async def test_native_fallback_resolution_cannot_supersede_newer_room_action(hass, binding, change):
    entity, session, snapshots, commands, provider, old = entity_boundary(hass, CONFIG if binding else None)
    provider.state = ConfigEntryState.NOT_LOADED
    snapshots[0] = native("tunein:station:synthetic")
    entered, release = asyncio.Event(), asyncio.Event()

    async def resolve(_source) -> str:
        entered.set()
        await release.wait()
        return entity._radio_catalogue._item(old).media_content_id

    entity._radio_catalogue.async_source_selection = resolve
    task = asyncio.create_task(entity.async_select_source("Spotify"))
    try:
        async with asyncio.timeout(1):
            await entered.wait()
        if change == "stop":
            await entity.async_media_stop()
        else:
            snapshots[0] = native("tunein:station:newer-household-choice")
    finally:
        release.set()
        result = (await asyncio.gather(task, return_exceptions=True))[0]
    assert isinstance(result, (HomeAssistantError, asyncio.CancelledError))
    commands.async_play_catalogue.assert_not_awaited()
    assert all(call[0] == "GET" for call in session.calls)


@pytest.mark.asyncio
async def test_native_dispatch_guard_pins_selection_before_account_preparation(hass):
    entity, session, snapshots, commands, provider, old = entity_boundary(hass)
    provider.state = ConfigEntryState.NOT_LOADED
    snapshots[0] = native("tunein:station:synthetic")

    async def changed_accounts() -> list:
        snapshots[0] = native("tunein:station:newer-household-choice")
        return [{"cmd": "spotify", "id": "native-owner", "user": "native-user", "configerror": False}]

    commands.async_service_accounts = changed_accounts
    item = entity._radio_catalogue._item(old)
    with pytest.raises(HomeAssistantError):
        await entity.async_play_media(RADIO_MEDIA_TYPE, item.media_content_id)
    commands.async_play_catalogue.assert_not_awaited()
    assert all(call[0] == "GET" for call in session.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("remove_binding", [False, True])
async def test_real_pause_transport_and_volume_stop_keep_uncertainty(hass, monkeypatch, remove_binding):
    class PauseSocket(SyntheticAudioSocket):
        """Use the real authentication exchange and exact synthetic room pause."""

        async def send(self, message: str) -> None:
            """Acknowledge only the synthetic room's real pause wire command."""
            if message == "audio/7/pause":
                self.sent.append(message)
                self.queue.put_nowait('{"pause_result":true}')
            else:
                await super().send(message)

    entity, session, _, _, _, _ = entity_boundary(hass)
    controller = entity._spotify_return
    controller.uncertain = True
    client = wire.AudioServerCommands("audio.example.invalid", lambda: ("synthetic-user", "synthetic-active-token"))

    def fence() -> None:
        """Keep the synthetic uncertain fence installed until client shutdown."""

    client.source_fences[7] = fence
    entity._audio_commands = client
    socket = PauseSocket(RSA.generate(2048))
    monkeypatch.setattr(wire, "connect", lambda *_args, **_kwargs: socket)
    if remove_binding:
        entity._spotify_return = None
        entity._spotify_binding = None
    events = []
    unsubscribe = hass.bus.async_listen(media.SENDDOMAIN, lambda event: events.append(event.data))
    try:
        await entity.async_media_pause()
        await entity.async_set_volume_level(0.07)
        await entity.async_media_stop()
        await hass.async_block_till_done()
        assert client.source_fences[7] is fence
    finally:
        unsubscribe()
        await client.async_close()
    assert socket.sent[-1] == "audio/7/pause"
    assert socket.closed
    # Bus callbacks need not settle in the order these awaited services return.
    assert sorted(events, key=lambda event: event["value"]) == [
        {"uuid": entity.uuidAction, "value": "pause"},
        {"uuid": entity.uuidAction, "value": "volume/7"},
    ]
    assert spotify_room_uncertain(hass, entity.unique_id, 7)
    assert controller.uncertain
    assert all(call[0] == "GET" for call in session.calls)
