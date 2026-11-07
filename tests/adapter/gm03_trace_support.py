"""Explicit GM03 successors for historical public-volume replay contracts.

Historical payloads remain literal public API requests, NOT new UI emissions.
Actual new room-row emissions are independently replayed by GM03 browser tests.
"""
import hashlib
import math
from custom_components.loxone.const import SENDDOMAIN
from test_audio_grouping_ha import action

def historical_source(root, trace):
    path=root/'tests/frontend/frozen-oracles'/(trace['source_sha256']+'.js.txt')
    assert hashlib.sha256(path.read_bytes()).hexdigest()==trace['source_sha256']
    return str(path.relative_to(root))

class VolumeFeedback:
    """Native receive callback from exact Miniserver bus writes, never an ACK."""
    def __init__(self,hass,g,entry,ids):
        self.reject=False
        self.writes=[]
        self.ids=ids
        async def received(event):
            self.writes.append(dict(event.data))
            if self.reject:return
            p=next(p for p in ids if action(p)==event.data['uuid'])
            await g.callbacks[entry.entry_id]['callback']({f'volume-{p}':int(event.data['value'].split('/')[1])})
        self.remove=hass.bus.async_listen(SENDDOMAIN,received)

    def expected(self,g,co,target,level):
        p=next(p for p,i in self.ids.items() if i==target)
        group=next((x for x in co.audio_grouping.native.snapshot.groups if p in x.players and x.kind=='dynamic'),None)
        if group is None:return [(action(p),f'volume/{int(level*100)}')]
        old=[g.entities[self.ids[i]]._room_volume_percent for i in group.players]
        assert all(type(v) is int for v in old)
        baseline=(2*sum(old)+len(old))//(2*len(old))
        delta=math.floor(level*100+.5)-baseline
        return [(action(i),f'volume/{new}') for i,v in zip(group.players,old) if (new:=max(0,min(100,v+delta)))!=v]

    def assert_raw(self,hass,before,wires):
        expected=dict(before)
        for uuid,value in wires:
            i=next(i for p,i in self.ids.items() if action(p)==uuid)
            expected[i]=int(value.split('/')[1])/100
        assert {i:hass.states.get(i).attributes.get('loxone_room_volume_level') for i in self.ids.values()}==expected
