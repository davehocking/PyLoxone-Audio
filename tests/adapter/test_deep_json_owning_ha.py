"""Malformed native event must not kill the real HA-owned audio listener."""
from test_audioserver_ha import audio_setup as audio_setup, zone_entity_id

async def test_deep_json_does_not_kill_owning_listener(hass, audio_setup):
    import json
    await audio_setup.setup()
    entity = zone_entity_id(hass, 7)
    from test_audioserver_ha import EVENT
    hass.bus.async_fire(EVENT, {'play-7': 2})
    await hass.async_block_till_done()
    assert hass.states.get(entity).state == 'playing'
    queue = audio_setup.queues[0]
    await queue.put(json.dumps({'audio_event': [{'playerid': 7, 'title': 'Before malformed frame'}]}))
    await hass.async_block_till_done()
    assert hass.states.get(entity).attributes.get('media_title') == 'Before malformed frame'
    await queue.put('[' * 10000 + ']' * 10000)
    await queue.put(json.dumps({'audio_event': [{'playerid': 7, 'title': 'Still receiving after malformed frame'}]}))
    await hass.async_block_till_done()
    assert hass.states.get(entity).attributes.get('media_title') == 'Still receiving after malformed frame'
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()
