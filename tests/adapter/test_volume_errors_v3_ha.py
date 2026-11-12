"""Volume-specific failure wording and actual Core service/translation loading."""
import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.service import _load_services_file
from homeassistant.helpers.translation import async_get_translations
from homeassistant.loader import async_get_integration
from test_audio_grouping_ha import grouped_setup, audio_setup, row


@pytest.mark.parametrize('domain,service,data,operation', [('media_player','volume_set',{'volume_level':.45},'volume_set'),('loxone','audio_group_volume',{'volume_percent':45},'volume_set'),('loxone','audio_room_volume',{'volume_percent':45},'audio_room_volume')])
async def test_volume_timeout_uses_volume_specific_translation(hass, grouped_setup, tmp_path, domain, service, data, operation):
    hass.config.config_dir = str(tmp_path)
    g = grouped_setup
    entry, co, ids = await g.setup()
    await g.feed(entry, row('one', (1,2)))
    await g.callbacks[entry.entry_id]['callback']({'play-1':1,'play-2':1,'volume-1':10,'volume-2':40})
    await hass.async_block_till_done()
    observer = co.audio_diagnostics
    await observer.async_set_enabled(True)
    co.audio_grouping.native.timeout = .05
    with pytest.raises(HomeAssistantError) as caught:
        await hass.services.async_call(domain,service,data,target={'entity_id':ids[1]},blocking=True)
    assert caught.value.translation_key == 'audioserver_volume_failed'
    translated = await async_get_translations(hass, 'en', 'exceptions', {'loxone'})
    message = translated['component.loxone.exceptions.audioserver_volume_failed.message']
    assert 'volume' in message.lower() and 'playback' not in message.lower()
    assert not co.audio_grouping.native._scope and not co.audio_grouping.native._requests
    events = (await observer.async_export())['events']
    requests = [r for r in events if r['stage']=='ha_service_request' and r.get('operation')==operation]
    outcomes = [r for r in events if r['stage']=='operation_finished' and r.get('operation')==operation]
    assert len(requests)==1 and requests[0]['volume']==45
    assert len(outcomes)==1 and outcomes[0]['outcome']=='error'
    assert outcomes[0]['ha_context_id']==requests[0]['ha_context_id']
    assert observer.journal.stats['invalid_records']==0 and observer.emitter.sink_failures==0


@pytest.mark.parametrize('language', ['en','nl','cs','es','it','pt-PT','de','fr','pt','pt-BR'])
async def test_group_volume_metadata_and_localised_error_are_loaded_by_core(hass, grouped_setup, language):
    await grouped_setup.setup()
    integration = await async_get_integration(hass, 'loxone')
    descriptions = await hass.async_add_executor_job(_load_services_file, integration)
    spec = descriptions['audio_group_volume']
    assert spec['target']['entity'] == [{'domain':['media_player'],'integration':'loxone'}]
    field = spec['fields']['volume_percent']
    assert field['required'] and field['selector']['number']['min'] == 0 and field['selector']['number']['max'] == 100
    services = await async_get_translations(hass, language, 'services', {'loxone'})
    assert services['component.loxone.services.audio_group_volume.name']
    assert services['component.loxone.services.audio_group_volume.fields.volume_percent.name']
    errors = await async_get_translations(hass, language, 'exceptions', {'loxone'})
    assert errors['component.loxone.exceptions.audioserver_volume_failed.message']
