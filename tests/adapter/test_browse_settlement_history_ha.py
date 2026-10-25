"""Real Browse history commits require feedback AND successful native settlement."""
from __future__ import annotations

import asyncio
import pytest
from homeassistant.exceptions import HomeAssistantError
from test_audioserver_ha import audio_setup
from test_audioserver_playback import rsa_key
from test_native_return_progress_wire_ha import native_return_harness
from test_native_source_return_ha import PARENT, TRACK

from custom_components.loxone.audio_catalogue import CatalogueTarget
from custom_components.loxone.pyloxone_api import audioserver as wire


@pytest.mark.asyncio
@pytest.mark.parametrize('settlement', ['accepted', 'rejected', 'transport'])
async def test_browse_history_waits_for_successful_settlement(
    hass, audio_setup, monkeypatch, rsa_key, settlement,
):
    """Matching B feedback during a send cannot overwrite retained A on failure."""
    requested = 'library:local:track:0'
    entity, sockets, _samples, shortcuts = await native_return_harness(
        hass, audio_setup, monkeypatch, rsa_key, spotify=False, tick=False,
        source_echo=False, source_feedback={'audiopath': requested},
    )
    catalogue = entity._radio_catalogue
    assert catalogue.source_session('Local Library').audio_path == TRACK
    folder = catalogue._item(CatalogueTarget('folder', 'Local Library', 'library', PARENT))
    page = await entity.async_browse_media(folder.media_content_type, folder.media_content_id)
    selected = page.children[0]
    assert catalogue.resolve(selected.media_content_id).audio_path == requested
    feedback, release = asyncio.Event(), asyncio.Event()
    connect_original = wire.connect

    def connect(*args, **kwargs):
        socket = connect_original(*args, **kwargs)
        send_original = socket.send

        async def send(message):
            await send_original(message)
            if message.startswith('audio/7/library/play/'):
                # The real authenticated request has sent once and the receiver
                # has applied B; deliberately hold the terminal command reply.
                feedback.set()
                await release.wait()
                if settlement == 'transport':
                    raise OSError('Synthetic transport failure after feedback')
                reply = {'command': message}
                if settlement == 'rejected':
                    reply['error'] = 'Synthetic exact rejection after feedback'
                import json
                socket.queue.put_nowait(json.dumps(reply))

        socket.send = send
        return socket

    monkeypatch.setattr(wire, 'connect', connect)
    action = asyncio.create_task(hass.services.async_call(
        'media_player', 'play_media', {
            'entity_id': entity.entity_id,
            'media_content_type': selected.media_content_type,
            'media_content_id': selected.media_content_id,
        }, blocking=True,
    ))
    try:
        await asyncio.wait_for(feedback.wait(), 2)
        assert not action.done()
        assert entity._audio_metadata.get(7).audio_path == requested
        assert catalogue.source_session('Local Library').audio_path == TRACK
        release.set()
        if settlement == 'accepted':
            await asyncio.wait_for(action, 2)
            assert catalogue.source_session('Local Library').audio_path == requested
            assert not entity._audio_commands.source_fences
        else:
            with pytest.raises(HomeAssistantError):
                await asyncio.wait_for(action, 2)
            assert catalogue.source_session('Local Library').audio_path == TRACK
            assert 7 in entity._audio_commands.source_fences
        await hass.async_block_till_done()
        writes = [m for s in sockets for m in s.sent if m.startswith('audio/7/')]
        assert len(writes) == 1
        assert '/library/play/' in writes[0]
        assert all(s.closed for s in sockets)
        assert shortcuts == []
        audio_setup.apis[0].send_websocket_command.assert_not_awaited()
    finally:
        release.set()
        await asyncio.gather(action, return_exceptions=True)
