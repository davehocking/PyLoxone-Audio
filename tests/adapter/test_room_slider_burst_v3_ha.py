"""Owner's retained relative cadence; synthetic feedback, not household replay."""
import asyncio
import json
from pathlib import Path
from time import monotonic
import pytest
from custom_components.loxone.const import SENDDOMAIN
from test_audio_grouping_ha import action, row, grouped_setup, audio_setup


@pytest.mark.parametrize('feedback_delay', [.10, .60])
async def test_normal_room_slider_burst_at_retained_owner_cadence(hass, grouped_setup, monkeypatch, feedback_delay):
    g = grouped_setup
    entry, co, ids = await g.setup()
    await g.feed(entry, row('one', (1,2,3,4,5)))
    await g.callbacks[entry.entry_id]['callback']({**{f'play-{p}':2 for p in ids}, **{f'volume-{p}':(25 if p==1 else 20) for p in ids}})
    await hass.async_block_till_done()
    errors, writes, tasks = [], [], []
    original = co.audio_grouping.native.async_volume
    async def traced(*args, **kwargs):
        try:
            return await original(*args, **kwargs)
        except Exception as error:
            errors.append({'type':type(error).__name__, 'message':str(error), 'elapsed':monotonic()-start})
            raise
    monkeypatch.setattr(co.audio_grouping.native, 'async_volume', traced)
    async def feedback(event):
        writes.append(dict(event.data))
        await asyncio.sleep(feedback_delay)
        await g.callbacks[entry.entry_id]['callback']({'volume-1':int(event.data['value'].split('/')[1])})
    remove = hass.bus.async_listen(SENDDOMAIN, feedback)
    start = monotonic()
    async def request(at, value):
        await asyncio.sleep(max(0, at-(monotonic()-start)))
        await hass.services.async_call('media_player','volume_set',{'volume_level':value/100},target={'entity_id':ids[1]},blocking=True)
    try:
        tasks = [asyncio.create_task(request(at, v)) for at,v in [(0,22),(.46335,20),(.65833,18),(1.304142,16),(1.4612,16)]]
        outcomes = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 20)
        await hass.async_block_till_done()
        report = {'feedback_delay':feedback_delay, 'outcomes':[type(v).__name__ if isinstance(v, BaseException) else 'returned' for v in outcomes], 'native_errors':errors, 'writes':writes, 'final_room':g.entities[ids[1]]._room_volume_percent, 'deadline':co.audio_grouping.native.timeout, 'historical_cause_proven':False}
        Path(f'room-burst-{feedback_delay}.json').write_text(json.dumps(report,indent=2)+'\n')
        assert all(v is None for v in outcomes), report
        assert all(w['uuid']==action(1) for w in writes)
        assert g.entities[ids[1]]._room_volume_percent == 16
        assert all(g.entities[ids[p]]._room_volume_percent == 20 for p in (2,3,4,5))
        assert not co.audio_grouping.native._scope and not co.audio_grouping.native._requests
    finally:
        for task in tasks:
            if not task.done(): task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        remove()
