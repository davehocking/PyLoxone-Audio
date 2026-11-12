"""New owner incident; invented13-room HA setup, no household I/O."""
import asyncio
import json
from pathlib import Path
from time import perf_counter

import pytest
from custom_components.loxone import audio_grouping as grouping
from custom_components.loxone.const import SENDDOMAIN
from test_audio_grouping_ha import grouped_setup as grouped_setup
from test_audio_grouping_ha import audio_setup as audio_setup
from test_audio_grouping_ha import action, structure, row


@pytest.mark.parametrize('overlap', [0, 7])
async def test_first_group_volume_with_fresh_feedback_and_overlapping_requests(hass, grouped_setup, monkeypatch, overlap):
    g = grouped_setup
    g.source.clear()
    g.source.update(structure(count=13))
    entry, co, _ = await g.setup()
    ids = {e._audio_player_id: i for i, e in g.entities.items()}
    await g.feed(entry, row('invented-group', (1, 2, 3, 4, 5)))
    initial = {p: ([17, 20, 20, 20, 30][p-1] if p <= 5 else 10) for p in ids}
    await g.callbacks[entry.entry_id]['callback']({**{f'play-{p}': 1 for p in ids}, **{f'volume-{p}': v for p, v in initial.items()}})
    await hass.async_block_till_done()
    owner = co.audio_grouping
    binding_calls = 0
    original_binding = grouping.grouping_binding
    def binding(*args):
        nonlocal binding_calls
        binding_calls += 1
        return original_binding(*args)
    monkeypatch.setattr(grouping, 'grouping_binding', binding)
    start = perf_counter()
    descriptor = owner.control_descriptor(1)
    descriptor_elapsed = perf_counter() - start
    descriptor_calls = binding_calls
    assert descriptor['members'] == [ids[p] for p in range(1, 6)]
    binding_calls = 0
    writes, errors, callbacks = [], [], []
    first_send = asyncio.Event()
    async def feedback(event):
        player = next(p for p in ids if action(p) == event.data['uuid'])
        value = int(event.data['value'].split('/')[1])
        writes.append({'player': player, 'value': value, 'time': perf_counter()-start})
        first_send.set()
        await asyncio.sleep(.01)
        await g.callbacks[entry.entry_id]['callback']({f'volume-{player}': value})
        callbacks.append({'player': player, 'value': value, 'time': perf_counter()-start})
    remove = hass.bus.async_listen(SENDDOMAIN, feedback)
    native = owner.native.async_volume
    async def volume(*args, **kwargs):
        try:
            return await native(*args, **kwargs)
        except Exception as error:
            errors.append({'type': type(error).__name__, 'message': str(error), 'time': perf_counter()-start})
            raise
    monkeypatch.setattr(owner.native, 'async_volume', volume)
    def call(value):
        return hass.services.async_call('loxone', 'audio_group_volume', {'entity_id': ids[1], 'volume_percent': value}, blocking=True)
    tasks = []
    try:
        start = perf_counter()
        first = asyncio.create_task(call(22))
        tasks.append(first)
        await asyncio.wait_for(first_send.wait(), 10)
        for value in [40, 40, 40, 36, 52, 52, 52][:overlap]:
            tasks.append(asyncio.create_task(call(value)))
        outcomes = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 80)
        await hass.async_block_till_done()
        receipt = {
            'overlap': overlap, 'elapsed_s': perf_counter()-start,
            'descriptor_binding_calls': descriptor_calls, 'descriptor_elapsed_s': descriptor_elapsed,
            'operation_binding_calls': binding_calls, 'writes': writes, 'feedback': callbacks,
            'errors': errors, 'outcomes': [type(v).__name__ if isinstance(v, BaseException) else 'returned' for v in outcomes],
        }
        Path(f'volume-measurement-{overlap}.json').write_text(json.dumps(receipt, indent=2))
        assert outcomes[0] is None, receipt
        assert [(x['player'], x['value']) for x in writes[:5]] == [(1,18),(2,21),(3,21),(4,21),(5,31)]
        assert len(writes) == 5, receipt  # Queued stale requests must not add writes.
        assert len(callbacks) == 5, receipt
        assert all(type(outcome).__name__ == 'HomeAssistantError' for outcome in outcomes[1:]), receipt
        assert not owner.native._scope and not owner.native._requests
        assert not owner.native._lock.locked()
        assert descriptor_calls <= 2, 'One synchronous descriptor must not reparse topology for every candidate/member combination'
    finally:
        remove()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
