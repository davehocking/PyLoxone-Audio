"""Actual HA-published thirteen-room mixed-playing fixture, entirely invented I/O."""
import json
import os
from pathlib import Path
from test_audio_grouping_ha import grouped_setup, row
from test_audioserver_ha import audio_setup
from test_audioserver_playback import rsa_key
from test_group_modes_leader_ha import harness


async def test_export_actual_v3_and_mixed_follower_states(hass, grouped_setup, audio_setup, monkeypatch, rsa_key):
    h = await harness(hass, grouped_setup, audio_setup, monkeypatch, rsa_key, count=13)
    await h.g.feed(h.entry, row('shared', (2,1,3,4,5)))
    await h.g.callbacks[h.entry.entry_id]['callback']({**{f'play-{p}': (2 if p in (2,4) else 0) for p in h.entities}, **{f'volume-{p}': (10 if p==1 else 40 if p==2 else 20) for p in h.entities}})
    await h.emit(2, plshuffle=True, plrepeat=3)
    await hass.async_block_till_done()
    snapshots = []
    async def capture(label):
        await hass.async_block_till_done()
        snapshots.append({'scenario':label, 'target': h.entities[1].entity_id, 'states': {e.entity_id:hass.states.get(e.entity_id).as_dict() for e in h.entities.values()}})
    await capture('initial')
    await h.g.feed(h.entry, row('shared', (3,1,2,4,5)))
    await h.emit(3, plshuffle=False, plrepeat=1)
    await capture('changed-leader')
    await h.g.feed(h.entry, row('shared', (2,1,3,4,5)))
    await capture('restored-leader')
    assert len(snapshots[0]['states']) == 13
    assert snapshots[0]['states'][h.entities[1].entity_id]['state'] == 'idle'
    assert snapshots[0]['states'][h.entities[2].entity_id]['state'] == 'playing'
    assert not h.writes and not h.sockets
    if output := os.environ.get('GM03_BROWSER_STATES'):
        Path(output).write_text(json.dumps({'snapshots':snapshots, 'display_registry':{'entities':[{'ei':e.entity_id,'pl':'loxone','lb':[]} for e in h.entities.values()], 'entity_categories':{}}, 'device_registry':[], 'provenance':'Actual owning HA states from invented13-room setup, not household recording'}, default=str, indent=2)+'\n')
