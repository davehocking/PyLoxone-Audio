"""Observe actual owned-HA publication without collecting unrelated state."""
import json
from homeassistant.helpers import entity_registry as er
from custom_components.loxone.const import DOMAIN
from test_audioserver_ha import audio_setup,zone_entity_id


async def test_actual_publication_records_owned_audio_only_and_sanitizes_attributes(hass,audio_setup,tmp_path):
    hass.config.config_dir=str(tmp_path)
    entry=await audio_setup.setup(playback=True)
    owner=hass.data[DOMAIN][entry.entry_id].audio_diagnostics
    await owner.async_set_enabled(True)
    entity=zone_entity_id(hass,7)
    attrs={'volume_level':.37,'media_position':12,'media_duration':180,'media_title':'SECRET-title','source':'SECRET-source','access_token':'SECRET-token','audio_track_id':'synthetic-track'}
    hass.states.async_set(entity,'paused',attrs)
    hass.states.async_set('media_player.unrelated_private_device','playing',attrs)
    await hass.async_block_till_done()
    report=await owner.async_export()
    rows=[r for r in report['events']if r['stage']=='state_published']
    assert len(rows)==1,'Actual owned HA state publication is not observable'
    assert rows[0]['ha_state']=='paused'and rows[0]['volume']==37
    assert rows[0]['position']==12 and rows[0]['duration']==180
    assert rows[0]['player']==owner.emitter.alias('player',7)
    assert rows[0]['ha_context_id']
    assert 'SECRET'not in json.dumps(report)
    assert 'unrelated_private_device'not in json.dumps(report)
    assert not any(r['stage']=='send_attempt'for r in report['events'])
    await owner.async_close()
    size=owner.queue.qsize()
    hass.states.async_set(entity,'playing',attrs)
    await hass.async_block_till_done()
    assert owner.queue.qsize()==size
