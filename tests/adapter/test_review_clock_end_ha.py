"""Independent end-of-duration and raw-diagnostic preservation controls."""
import asyncio
from datetime import datetime,timedelta
import json
import pytest
from homeassistant.util import dt as dt_util
from test_audioserver_ha import audio_setup
from test_audioserver_playback import SyntheticAudioSocket,rsa_key
from test_audio_modes_ha import mode_harness
from test_stage2_modes_ha import output
from pyloxone_audio import native,clock as native_clock
from custom_components.loxone.pyloxone_api import audioserver as wire


def clock_fixture(monkeypatch):
    wall=[dt_util.utcnow()]
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return wall[0].astimezone(tz) if tz is not None else wall[0].replace(tzinfo=None)
    monkeypatch.setattr(native,'datetime',Clock);monkeypatch.setattr(native_clock,'datetime',Clock)
    monkeypatch.setattr(dt_util,'utcnow',lambda:wall[0])
    return wall

async def test_review_duration_end_withholds_expired_anchor_and_does_not_spin(
    hass,audio_setup,monkeypatch,rsa_key,
):
    wall=clock_fixture(monkeypatch);start=wall[0]
    h=await mode_harness(hass,audio_setup,monkeypatch,rsa_key,source='library')
    room=h.entities[7];reads=[];sockets=[]
    current=[{**h.rows[7],'duration':40,'time':30}]
    class Peer(SyntheticAudioSocket):
        async def send(self,message):
            if message=='audio/7/status':
                self.sent.append(message);reads.append(message)
                self.queue.put_nowait(json.dumps({'status_result':[current[0]]}))
            else:await super().send(message)
    def connect(*a,**kw):
        peer=Peer(rsa_key);sockets.append(peer);return peer
    monkeypatch.setattr(wire,'connect',connect)
    for elapsed in [0,4,8,10]:
        wall[0]=start+timedelta(seconds=elapsed)
        current[0]={**current[0],'time':30+elapsed}
        await h.emit(current[0]);await hass.async_block_till_done()
    for _ in range(200):
        if reads and not h.metadata._recoveries:break
        await asyncio.sleep(0.001)
    assert h.metadata._client.get(7).position==40
    assert h.metadata.get(7) is None
    assert room.media_position is None
    assert reads==['audio/7/status']
    assert all(s.closed for s in sockets) and not h.writes
    output('duration-end.json',{'reads':reads,'raw_position':40,'expired_presentation_unknown':True,'no_spin':True,'no_writes':True})

async def test_review_redundant_clock_anchors_do_not_suppress_raw_diagnostics(
    hass,audio_setup,monkeypatch,rsa_key,
):
    wall=clock_fixture(monkeypatch);start=wall[0]
    h=await mode_harness(hass,audio_setup,monkeypatch,rsa_key,source='library')
    room=h.entities[7]
    await h.emit({**h.rows[7],'time':30});await hass.async_block_till_done()
    anchor=(room.media_position,room.media_position_updated_at)
    h.emitter.enabled=True
    for elapsed in [4,8,12]:
        wall[0]=start+timedelta(seconds=elapsed)
        await h.emit({**h.rows[7],'time':30+elapsed});await hass.async_block_till_done()
        assert (room.media_position,room.media_position_updated_at)==anchor
    feedback=[event for event in h.events if event.get('stage')=='feedback']
    output('raw-diagnostics.json',{'events':h.events,'anchor_unchanged':True,'raw_position':h.metadata._client.get(7).position})
    # The emitter's event schema is taken from its actual public output.
    assert len(feedback)==3
    assert [event['position'] for event in feedback]==[34,38,42]
    assert h.metadata._client.get(7).received_at==wall[0]
