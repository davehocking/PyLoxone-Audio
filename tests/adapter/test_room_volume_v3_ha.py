"""Owner-corrected room/native and explicit group contract; invented I/O only."""
import pytest
from custom_components.loxone.const import SENDDOMAIN
from test_audio_grouping_ha import action, row
from test_audio_grouping_ha import grouped_setup as grouped_setup
from test_audio_grouping_ha import audio_setup as audio_setup


@pytest.mark.parametrize('target', [1, 2])
async def test_native_setter_changes_only_selected_room(hass, grouped_setup, target):
    g = grouped_setup
    entry, co, ids = await g.setup()
    await g.feed(entry, row('one', (1, 2)), row('other', (3, 4)))
    await g.callbacks[entry.entry_id]['callback']({**{f'play-{p}': 1 for p in ids}, **{f'volume-{p}': 10*p for p in ids}})
    await hass.async_block_till_done()
    writes = []
    async def feedback(event):
        writes.append(dict(event.data))
        player = next(p for p in ids if action(p) == event.data['uuid'])
        await g.callbacks[entry.entry_id]['callback']({f'volume-{player}': int(event.data['value'].split('/')[1])})
    remove = hass.bus.async_listen(SENDDOMAIN, feedback)
    try:
        await hass.services.async_call('media_player', 'volume_set', {'volume_level': .45}, target={'entity_id': ids[target]}, blocking=True)
        await hass.async_block_till_done()
        assert writes == [{'uuid': action(target), 'value': 'volume/45'}]
        for p in ids:
            expected = .45 if p == target else p/10
            state = hass.states.get(ids[p])
            assert state.attributes['volume_level'] == expected
            assert state.attributes['loxone_room_volume_level'] == expected
    finally:
        remove()


@pytest.mark.parametrize('levels,requested,expected', [
    ([10,40],45,[30,60]), ([10,11],12,[11,12]),
    ([90,100],100,[95,100]), ([0,10],0,[0,5]),
    ([0,100],50,[0,100]), ([28,28],29,[29,29]),
])
async def test_explicit_group_service_uses_qualified_additive_engine(hass, grouped_setup, levels, requested, expected):
    g = grouped_setup
    entry, co, ids = await g.setup()
    await g.feed(entry, row('one', (1,2)), row('other', (3,4)))
    await g.callbacks[entry.entry_id]['callback']({**{f'play-{p}': 1 for p in ids}, **{f'volume-{p}': (levels[p-1] if p <= 2 else p*10) for p in ids}})
    await hass.async_block_till_done()
    writes = []
    async def feedback(event):
        writes.append(dict(event.data))
        player = next(p for p in ids if action(p) == event.data['uuid'])
        await g.callbacks[entry.entry_id]['callback']({f'volume-{player}': int(event.data['value'].split('/')[1])})
    remove = hass.bus.async_listen(SENDDOMAIN, feedback)
    try:
        assert hass.services.has_service('loxone', 'audio_group_volume')
        await hass.services.async_call('loxone', 'audio_group_volume', {'volume_percent': requested}, target={'entity_id': ids[2]}, blocking=True)
        await hass.async_block_till_done()
        assert writes == [{'uuid': action(p), 'value': f'volume/{v}'} for p,v,old in zip((1,2),expected,levels) if old != v]
        mean = ((sum(expected)*2+len(expected))//(2*len(expected)))/100
        for p in (1,2):
            attrs = hass.states.get(ids[p]).attributes
            assert attrs['volume_level'] == attrs['loxone_room_volume_level'] == expected[p-1]/100
            assert attrs['loxone_group_volume_level'] == mean
            assert attrs['loxone_group_control']['version'] == 3
        assert hass.states.get(ids[3]).attributes['volume_level'] == .3
    finally:
        remove()
