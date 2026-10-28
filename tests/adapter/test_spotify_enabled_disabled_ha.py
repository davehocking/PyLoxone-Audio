"""HA Spotify state cannot influence native room return in 0.1.1.

Real owning HA config-entry reload and source service; entirely synthetic
provider/native transports. No claim about audible hardware or shared queues.
"""
import asyncio
import json
from urllib.parse import unquote
import pytest
from homeassistant.config_entries import ConfigEntryState
from test_audioserver_ha import audio_setup
from test_source_simple_session_ha import session_room
from test_spotify_continuity import CONFIG
from custom_components.loxone.pyloxone_api import audioserver as wire


@pytest.mark.asyncio
@pytest.mark.parametrize('enabled,other_receiver', [(True,False),(False,False),(True,True),(False,True)])
async def test_native_only_source_return_ignores_legacy_binding_and_unrelated_ha_spotify(
    hass, audio_setup, monkeypatch, enabled, other_receiver,
):
    entity, _emit, writes, session, remembered = await session_room(hass, audio_setup, monkeypatch)
    provider = hass.config_entries.async_get_entry(CONFIG['entry_id'])
    provider.disabled_by = None if enabled else 'user'
    session.current['item']['uri'] = 'spotify:track:' + 'Z' * 22
    if other_receiver:
        session.current['device']['id'] = 'e' * 40
    entry, = hass.config_entries.async_entries('loxone')
    hass.config_entries.async_update_entry(entry, options={**entry.options, 'audioserver_spotify_return': {
        'synthetic-zone-7': {**CONFIG, 'account_id': 'synthetic-account'},
    }})
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    entity = hass.data['media_player'].get_entity(entity.entity_id)
    queue = audio_setup.queues[-1]
    for row in (remembered, {'playerid': 7, 'mode': 'play', 'eventype': 0, 'audiopath': 'tunein:station:synthetic'}):
        queue.put_nowait(json.dumps({'audio_event': [row]}))
        await hass.async_block_till_done()
    writes.clear()
    native_spotify_commands = []

    async def request(client, command, key, *, is_current, on_send, **kwargs):
        assert is_current()
        if on_send is not None:
            on_send()
        writes.append(command)
        parts = command.split('/')
        if parts[2:4] == ['serviceplay', 'spotify']:
            path = unquote(parts[5])
            native_spotify_commands.append(path)
            row = {**remembered, 'time': 0}
        elif parts[2] == 'position':
            row = {**remembered, 'time': float(parts[3])}
        else:
            raise AssertionError('Unexpected synthetic command: ' + command)
        asyncio.get_running_loop().call_soon(queue.put_nowait, json.dumps({'audio_event': [row]}))
        return [{'position': float(parts[3])}] if parts[2] == 'position' else None

    monkeypatch.setattr(wire.AudioServerCommands, '_async_request', request)
    await hass.services.async_call('media_player', 'select_source', {
        'entity_id': entity.entity_id, 'source': 'Spotify',
    }, blocking=True)
    await hass.async_block_till_done()
    assert native_spotify_commands == [remembered['audiopath']]
    assert entity._audio_metadata.get(7).audio_path == remembered['audiopath']
    assert session.calls == [], 'Neither enabled nor disabled unrelated HA Spotify may be consulted'
    assert provider.disabled_by == (None if enabled else 'user')
    assert provider.state is ConfigEntryState.LOADED
    assert hass.config_entries.async_get_entry(CONFIG['entry_id']) is provider
