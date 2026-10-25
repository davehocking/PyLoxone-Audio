"""Explicit enabled/disabled comparison through HA's real source service.

Only external Spotify and native transport boundaries are synthetic. This is
software-path evidence, not an audible hardware or Spotify-account test.
"""
import asyncio
import json
from urllib.parse import unquote
import pytest
from homeassistant.exceptions import HomeAssistantError
from test_audioserver_ha import audio_setup
from test_source_simple_session_ha import session_room
from custom_components.loxone.pyloxone_api import audioserver as wire

@pytest.mark.asyncio
@pytest.mark.parametrize('enabled,other_receiver', [(True,False),(False,False),(True,True),(False,True)])
async def test_spotify_enabled_disabled_source_return(hass,audio_setup,monkeypatch,enabled,other_receiver):
    entity,emit,writes,session,remembered = await session_room(hass,audio_setup,monkeypatch)
    newer_track = 'spotify:track:' + 'Z' * 22
    session.current['item']['uri'] = newer_track
    if other_receiver:
        session.current['device']['id'] = 'e' * 40
    provider = hass.config_entries.async_get_entry(entity._spotify_binding.entry_id)
    provider.disabled_by = None if enabled else 'user'
    native_spotify_commands = []
    async def request(client,command,key,*,is_current,on_send,**kwargs):
        assert is_current()
        if on_send is not None:
            on_send()
        writes.append(command)
        parts = command.split('/')
        if parts[2:4] == ['serviceplay','spotify']:
            path = unquote('/'.join(parts[5:]))
            native_spotify_commands.append(path)
            row = {**remembered,'audiopath':newer_track if not path else remembered['audiopath'],'time':67 if not path else 0}
        elif parts[2] == 'position':
            row = {**remembered,'time':float(parts[3])}
        else:
            raise AssertionError('Unexpected synthetic command: '+command)
        asyncio.get_running_loop().call_soon(audio_setup.queues[0].put_nowait,json.dumps({'audio_event':[row]}))
        return [{'position':float(parts[3])}] if parts[2]=='position' else None
    monkeypatch.setattr(wire.AudioServerCommands,'_async_request',request)
    action = hass.services.async_call('media_player','select_source',{'entity_id':entity.entity_id,'source':'Spotify'},blocking=True)
    if enabled and other_receiver:
        with pytest.raises(HomeAssistantError):
            await action
        assert native_spotify_commands == [] and writes == []
    else:
        await action
        assert len(native_spotify_commands) == 1
        if enabled:
            assert native_spotify_commands == [''], 'Enhanced return must not replace live content'
            assert entity._audio_metadata.get(7).audio_path == newer_track
        else:
            assert native_spotify_commands[0], 'Native fallback needs qualified remembered content'
            assert entity._audio_metadata.get(7).audio_path == remembered['audiopath']
    if not enabled:
        assert session.calls == [], 'Disabled HA Spotify must not be queried'
    assert all(method=='GET' and not url.endswith('/queue') for method,url,_ in session.calls)
