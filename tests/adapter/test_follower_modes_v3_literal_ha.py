"""Literal actual compiled idle-follower widgets -> HA -> authenticated synthetic native."""
import json,os
from pathlib import Path
import pytest
from test_audio_grouping_ha import grouped_setup, row
from test_audioserver_ha import audio_setup
from test_group_modes_leader_ha import harness,rsa_key

@pytest.mark.parametrize('index',range(5))
async def test_literal_idle_follower_modes_route_only_current_leader(hass,grouped_setup,audio_setup,monkeypatch,rsa_key,index):
    trace=os.environ.get('GM03_FOCUS_REQUESTS')
    if not trace:raise RuntimeError('Required invented follower-mode literal trace missing')
    calls=json.loads(Path(trace).read_text());assert len(calls)==5
    call=calls[index];assert call['domain']=='media_player' and call['service'] in ('shuffle_set','repeat_set')
    h=await harness(hass,grouped_setup,audio_setup,monkeypatch,rsa_key,count=13)
    numbers={e.entity_id:p for p,e in h.entities.items()};states=call['states']
    target=call['data']['entity_id'];assert target in numbers and states[target]['state']=='idle'
    groups={}
    for entity in numbers:
        d=states[entity]['attributes']['loxone_group_control']
        if d['group_id'] is not None:groups[d['group_id']]=tuple(numbers[i] for i in d['members'])
    await h.g.feed(h.entry,*(row(name,members) for name,members in groups.items()))
    leader=numbers[states[target]['attributes']['group_members'][0]]
    assert leader!=numbers[target]
    for entity,p in numbers.items():
        attrs=states[entity]['attributes']
        await h.emit(p,plshuffle=attrs.get('shuffle',False),plrepeat={'off':0,'all':1,'one':3}[attrs.get('repeat','off')])
    await h.g.callbacks[h.entry.entry_id]['callback']({f'play-{p}':{'idle':0,'playing':2,'paused':1}.get(states[e.entity_id]['state'],0) for p,e in h.entities.items()})
    await hass.async_block_till_done();before=h.co.audio_grouping.native.snapshot.groups
    await hass.services.async_call(call['domain'],call['service'],call['data'],target=call.get('target'),blocking=True)
    op=call['service'].removesuffix('_set');value=call['data'][op]
    wire=('enable' if value else 'disable') if op=='shuffle' else {'off':0,'all':1,'one':3}[value]
    assert h.writes==[f'audio/{leader}/{op}/{wire}']
    assert h.co.audio_grouping.native.snapshot.groups==before
    assert all(s.closed for s in h.sockets) and h.co.audio_commands._socket is None
    assert not h.co.audio_grouping.native._requests and not h.co.audio_grouping.native._scope
    h.co.api.send_websocket_command.assert_not_awaited()
