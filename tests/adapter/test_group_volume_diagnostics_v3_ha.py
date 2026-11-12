"""Explicit group action stays observable with the unchanged portable schema."""
from custom_components.loxone.const import SENDDOMAIN
from test_audio_grouping_ha import action, row, grouped_setup, audio_setup


async def test_explicit_group_diagnostics_retain_request_percent_and_terminal(hass, grouped_setup, tmp_path):
    hass.config.config_dir = str(tmp_path)
    g = grouped_setup
    entry, co, ids = await g.setup()
    await g.feed(entry, row('one', (1,2)))
    await g.callbacks[entry.entry_id]['callback']({'play-1': 1, 'play-2': 1, 'volume-1': 10, 'volume-2': 40})
    await hass.async_block_till_done()
    observer = co.audio_diagnostics
    await observer.async_set_enabled(True)
    async def feedback(event):
        player = next(p for p in ids if action(p) == event.data['uuid'])
        await g.callbacks[entry.entry_id]['callback']({f'volume-{player}': int(event.data['value'].split('/')[1])})
    remove = hass.bus.async_listen(SENDDOMAIN, feedback)
    try:
        await hass.services.async_call('loxone', 'audio_group_volume', {'volume_percent': 45}, target={'entity_id': ids[1]}, blocking=True)
        await hass.async_block_till_done()
        events = (await observer.async_export())['events']
        requests = [r for r in events if r['stage'] == 'ha_service_request' and r.get('operation') == 'volume_set']
        assert len(requests) == 1 and requests[0]['volume'] == 45
        outcomes = [r for r in events if r['stage'] == 'operation_finished' and r.get('operation') == 'volume_set']
        assert len(outcomes) == 1 and outcomes[0]['outcome'] == 'returned'
        assert requests[0]['ha_context_id'] == outcomes[0]['ha_context_id']
        assert observer.emitter.sink_failures == 0
        assert observer.journal.stats['invalid_records'] == 0
    finally:
        remove()
