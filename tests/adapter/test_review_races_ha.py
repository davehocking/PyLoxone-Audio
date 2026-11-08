"""Independent owning-HA race probes. Invented peers, unchanged runtime.

The long noisy cases use real loop time beyond the production 30 s backoff;
no recovery/freshness/spacing constants or acceptance assertions are patched.
"""
import asyncio
import json
import time

import pytest
from homeassistant.components.media_player import MediaPlayerEntityFeature
from test_audioserver_ha import audio_setup
from test_audioserver_playback import SyntheticAudioSocket, rsa_key
from test_audio_modes_ha import FULL, mode_harness
from test_stage2_modes_ha import output
from custom_components.loxone.pyloxone_api import audioserver as wire

BITS=MediaPlayerEntityFeature.SHUFFLE_SET|MediaPlayerEntityFeature.REPEAT_SET

async def eventually(predicate, seconds=2.5):
    deadline=time.monotonic()+seconds
    while not predicate() and time.monotonic()<deadline:
        await asyncio.sleep(0.01)
    return bool(predicate())

@pytest.mark.parametrize('source',['library','spotify'])
@pytest.mark.parametrize('intervening',['none','other-player','bare-row','same-track-progress','next-track'])
async def test_review_pending_sparse_status_preserves_liveness_without_stale_revival(
    hass,audio_setup,monkeypatch,rsa_key,source,intervening,
):
    h=await mode_harness(hass,audio_setup,monkeypatch,rsa_key,source=source)
    room=h.entities[7]
    prefix='library:local' if source=='library' else 'spotify'
    b={k:v for k,v in h.rows[7].items() if k not in {'pbr','plshuffle','plrepeat'}}
    b.update(audiopath=prefix+':track:review-B',time=1)
    current=[dict(b)]
    entered,release=asyncio.Event(),asyncio.Event()
    reads,sockets,snapshots=[],[],[]
    started=time.monotonic()

    def snap(label):
        row=h.metadata.get(7)
        snapshots.append({'label':label,'elapsed_real':time.monotonic()-started,
            'path':row.audio_path if row else None,'shuffle':room.shuffle,'repeat':room.repeat,
            'features':int(room.supported_features),'requested':sorted(h.metadata._requested_refresh),
            'retry_delay':dict(h.metadata._retry_delay),'retry_at':dict(h.metadata._retry_at),
            'recoveries':sorted(h.metadata._recoveries),
            'revision':dict(h.metadata._client._receiver._feedback_revision)})

    class Peer(SyntheticAudioSocket):
        async def send(self,message):
            if message=='audio/7/status':
                self.sent.append(message)
                index=len(reads)
                reads.append({'command':message,'elapsed_real':time.monotonic()-started,'index':index})
                # Pin B's response before waiting; later reads return current C.
                answer={**current[0],'pbr':FULL,'plshuffle':True,'plrepeat':3}
                if index==0:
                    entered.set()
                    await release.wait()
                self.queue.put_nowait(json.dumps({'status_result':[answer]}))
            elif message.startswith('audio/') and message.endswith('/status'):
                # Other rooms' real 30-second freshness timers are allowed to
                # run normally; the synthetic peer must implement their reads.
                player=int(message.split('/')[1])
                self.sent.append(message)
                self.queue.put_nowait(json.dumps({'status_result':[h.rows[player]]}))
            else:
                await super().send(message)

    def connect(*_a,**_kw):
        peer=Peer(rsa_key);sockets.append(peer);return peer
    monkeypatch.setattr(wire,'connect',connect)
    try:
        await h.emit(b)
        assert await eventually(entered.is_set),'Qualifying A -> B must start one status read'
        snap('B-pending')
        assert not room.supported_features&BITS and room.shuffle is None
        if intervening=='other-player':
            await h.emit({**h.rows[8],'time':39})
        elif intervening=='bare-row':
            await h.emit({'playerid':7})
        elif intervening=='same-track-progress':
            current[0]={**b,'time':2};await h.emit(current[0])
        elif intervening=='next-track':
            current[0]={**b,'audiopath':prefix+':track:review-C','time':2}
            await h.emit(current[0])
        snap('intervening')
        release.set()
        assert await eventually(lambda:not h.metadata._recoveries)
        await hass.async_block_till_done()
        snap('first-read-completed')
        noisy=intervening in {'same-track-progress','next-track'}
        if noisy:
            # The stale B response must be rejected. Keep ordinary sparse native
            # progress fresh for longer than the actual first failure backoff.
            assert not room.supported_features&BITS and room.shuffle is None
            for index in range(8):
                await asyncio.sleep(4)
                current[0]={**current[0],'time':6+4*index}
                await h.emit(current[0]);await hass.async_block_till_done()
                snap('ongoing-sparse-'+str(index))
            await eventually(lambda:room.supported_features&BITS==BITS,seconds=1.5)
        else:
            await eventually(lambda:room.supported_features&BITS==BITS)
        snap('final')
        output(f'review-race-{source}-{intervening}.json',{'source':source,'intervening':intervening,
            'reads':reads,'snapshots':snapshots,'all_sockets_closed':all(s.closed for s in sockets),
            'writes':h.writes,'constants_modified':False,'real_elapsed':time.monotonic()-started})
        assert room.supported_features&BITS==BITS, (
            'Qualified sparse-track mode recovery is lost after superseded read; '
            'ongoing valid sparse feedback prevents all freshness-based retries')
        assert room.shuffle is True and room.repeat=='one'
        assert h.metadata.get(7).audio_path==current[0]['audiopath']
        assert len(reads)==(2 if noisy else 1)
        assert not h.writes and all(s.closed for s in sockets)
    finally:
        release.set()
