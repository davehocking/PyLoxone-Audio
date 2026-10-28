"""Native session first through real HA plus independently authenticated synthetic wire."""
# ruff: noqa: S101, SLF001, INP001, F811, F401, ANN001, D103, PLR2004
from __future__ import annotations
import asyncio
import json
from copy import deepcopy

import pytest
from test_audioserver_ha import audio_setup
from test_audioserver_playback import SyntheticAudioSocket, rsa_key
from test_source_simple_session_ha import session_room
from custom_components.loxone.pyloxone_api import audioserver as wire


@pytest.mark.asyncio
@pytest.mark.parametrize('order', ['echo-first', 'proof-first', 'no-echo'])
async def test_native_session_ha_auth_wire_waits_for_actual_playing_not_early_echo(hass, audio_setup, monkeypatch, rsa_key, order):
    actual_request = wire.AudioServerCommands._async_request
    entity, _emit, shortcut_writes, session, spotify = await session_room(hass,audio_setup,monkeypatch)
    await _emit({**spotify, 'mode': 'pause'})
    monkeypatch.setattr(wire.AudioServerCommands,'_async_request',actual_request)
    entity._audio_commands._credentials = lambda: ('synthetic-user','synthetic-active-token')
    entity._audio_commands._timeout = 1
    sockets=[]
    sent, release = asyncio.Event(), asyncio.Event()
    queue = deepcopy(session.queue)
    class Socket(SyntheticAudioSocket):
        async def send(self,message):
            if message.startswith('audio/7/'):
                self.sent.append(message)
                assert message == 'audio/7/serviceplay/spotify/synthetic-account/'
                if order == 'echo-first':
                    self.queue.put_nowait(json.dumps({'command':message}))
                sent.set()
                await release.wait()
                audio_setup.queues[0].put_nowait(json.dumps({'audio_event':[spotify]}))
                if order == 'proof-first':
                    self.queue.put_nowait(json.dumps({'command':message}))
            else:
                await super().send(message)
    def connect(*args,**kwargs):
        socket=Socket(rsa_key)
        sockets.append(socket)
        return socket
    monkeypatch.setattr(wire,'connect',connect)
    action=asyncio.create_task(hass.services.async_call('media_player','select_source',{'entity_id':entity.entity_id,'source':'Spotify'},blocking=True))
    try:
        try:
            await asyncio.wait_for(sent.wait(),2)
        except TimeoutError:
            raise AssertionError({'action':repr(action), 'failure':getattr(entity,'_audio_last_source_failure',None), 'sockets':[socket.sent for socket in sockets], 'provider':session.calls}) from None
        assert not action.done(), 'Command echo is not confirmed playback'
        release.set()
        await asyncio.wait_for(action,3)
        assert shortcut_writes == []
        assert len(sockets)==1 and all(socket.closed for socket in sockets)
        assert session.queue == queue
        assert all(method=='GET' and not url.endswith('/queue') for method,url,_ in session.calls)
        assert entity._audio_metadata.get(7).source == 'Spotify'
        assert not entity._audio_commands.source_observations
        assert not entity._audio_commands.source_fences
        audio_setup.apis[0].send_websocket_command.assert_not_awaited()
    finally:
        release.set()
        action.cancel()
        await asyncio.gather(action,return_exceptions=True)
