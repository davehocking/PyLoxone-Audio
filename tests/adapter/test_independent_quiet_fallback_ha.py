"""Independent quiet-stream fallback using real deadlines and authenticated peer."""
import asyncio,json,time
from custom_components.loxone.pyloxone_api import audioserver as wire
from test_audioserver_ha import audio_setup
from test_audioserver_playback import SyntheticAudioSocket,rsa_key
from test_audio_modes_ha import FULL,mode_harness
from test_review_races_ha import eventually
from test_stage2_modes_ha import output

async def test_review_quiet_sparse_failure_uses_real_freshness_fallback(hass,audio_setup,monkeypatch,rsa_key):
    h=await mode_harness(hass,audio_setup,monkeypatch,rsa_key,source='library')
    b={k:v for k,v in h.rows[7].items() if k not in {'pbr','plshuffle','plrepeat'}}
    b.update(audiopath='library:local:track:quiet-B',time=1)
    current=[b];entered=asyncio.Event();release=asyncio.Event();reads=[];peers=[]
    class Peer(SyntheticAudioSocket):
        async def send(self,message):
            if message.startswith('audio/') and message.endswith('/status'):
                self.sent.append(message);player=int(message.split('/')[1])
                row=h.rows[player]
                if player==7:
                    answer={**current[0],'pbr':FULL,'plshuffle':True,'plrepeat':3}
                    reads.append(time.monotonic())
                    if len(reads)==1:
                        entered.set();await release.wait()
                    row=answer
                self.queue.put_nowait(json.dumps({'status_result':[row]}))
            else:await super().send(message)
    def connect(*args,**kwargs):
        p=Peer(rsa_key);peers.append(p);return p
    monkeypatch.setattr(wire,'connect',connect)
    try:
        await h.emit(b);assert await eventually(entered.is_set)
        current[0]={**b,'time':2};await h.emit(current[0]);release.set()
        assert await eventually(lambda:not h.metadata._recoveries)
        assert h.entities[7].shuffle is None
        assert 29<h.metadata._retry_at[7]-asyncio.get_running_loop().time()<=30
        # No sparse producer and no manual freshness call; actual timer fallback.
        assert await eventually(lambda:h.entities[7].shuffle is True,seconds=33)
        await hass.async_block_till_done()
        output('independent-quiet-fallback.json',{'read_times_monotonic':reads,
            'read_spacing_real':reads[1]-reads[0] if len(reads)>1 else None,
            'reads':len(reads),'writes':h.writes,'shuffle':h.entities[7].shuffle,
            'repeat':h.entities[7].repeat,'closed':all(p.closed for p in peers),
            'production_constants_changed':False,'producer':'quiet after one genuine superseding row'})
        assert len(reads)==2 and reads[1]-reads[0]>=30
        assert h.entities[7].repeat=='one' and not h.writes and all(p.closed for p in peers)
    finally:release.set()
