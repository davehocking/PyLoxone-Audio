"""Independent published-auth lifetime probe, actual token producer + owning HA.

External responses/peers are invented. No metadata cache, generation, guard or
constant is patched. Unpublished restoration is explicitly a limited control.
"""
import asyncio
import json
import pytest
from custom_components.loxone.pyloxone_api import audioserver as wire
from custom_components.loxone.pyloxone_api.connection import LoxoneConnection
from custom_components.loxone.pyloxone_api.message import TextMessage
from test_audioserver_ha import audio_setup
from test_audioserver_playback import SyntheticAudioSocket, rsa_key
from test_audio_modes_ha import FULL, mode_harness, request
from test_review_races_ha import eventually
from test_stage2_modes_ha import output

@pytest.mark.parametrize('phase',['auth','reply','cleanup'])
@pytest.mark.parametrize('history',['stable','identical-published','persistent-published','ABA-published','ABA-unpublished'])
async def test_review_actual_token_publication_revokes_old_mode_lifetime(
    hass,audio_setup,monkeypatch,rsa_key,phase,history,
):
    h=await mode_harness(hass,audio_setup,monkeypatch,rsa_key,source='library')
    co=hass.data['loxone'][h.entry.entry_id]
    publications=[]
    def changed(token):
        # This callback is invoked by the ACTUAL producer after its assignment.
        assert api.get_token_dict()['token']==token['token']
        publications.append({'producer_updated_before_callback':True,
                             'is_original':token['token']=='synthetic-active-token'})
        co._on_token_changed(token)
    api=LoxoneConnection('synthetic.invalid','synthetic-user','synthetic-password',
        token={'token':'synthetic-active-token','valid_until':9999999999,'hash_alg':'SHA256'},
        token_change_callback=changed)
    monkeypatch.setattr(co.api,'get_token_dict',api.get_token_dict)
    # Exactly the production getter expression, replacing mode_harness's constant getter.
    h.commands._credentials=lambda:(h.entry.options.get('username',''),co.api.get_token_dict().get('token',''))
    async def publish(value):
        raw=json.dumps({'LL':{'control':'jdev/sys/refreshjwt/synthetic','Code':200,
                            'value':{'token':value,'validUntil':9999999999}}})
        await api._websocket_event(TextMessage(raw))
        assert api.get_token_dict()['token']==value
    sparse={k:v for k,v in h.rows[7].items() if k not in {'pbr','plshuffle','plrepeat'}}
    sparse.update(audiopath='library:local:track:independent-auth-B',time=1)
    answer={**sparse,'pbr':FULL,'plshuffle':True,'plrepeat':3}
    mode_connect=wire.connect
    peers=[];read_commands=[];perturbed=False
    async def perturb():
        nonlocal perturbed
        if perturbed:return
        perturbed=True
        if history=='identical-published':await publish('synthetic-active-token')
        elif history=='persistent-published':await publish('synthetic-replacement-token')
        elif history=='ABA-published':
            await publish('synthetic-replacement-token');await publish('synthetic-active-token')
        elif history=='ABA-unpublished':
            # There is deliberately no published observation in this control.
            api._token.token='synthetic-replacement-token'
            api._token.token='synthetic-active-token'
    class Peer(SyntheticAudioSocket):
        async def send(self,message):
            if message=='audio/7/status':
                self.sent.append(message);read_commands.append(message)
                if phase=='reply':await perturb()
                self.queue.put_nowait(json.dumps({'status_result':[answer]}))
            else:
                await super().send(message)
                if message.startswith('secure/authenticate/') and phase=='auth':await perturb()
        async def __aexit__(self,*args):
            if phase=='cleanup':await perturb()
            await super().__aexit__(*args)
    def connect(*args,**kwargs):
        p=Peer(rsa_key);peers.append(p);return p
    monkeypatch.setattr(wire,'connect',connect)
    await h.emit(sparse)
    assert await eventually(lambda:perturbed and not h.metadata._recoveries)
    await hass.async_block_till_done()
    state=hass.states.get(h.entities[7].entity_id)
    revoked=history in {'persistent-published','ABA-published'}
    report={'phase':phase,'history':history,'publications':publications,
            'registered_token_persisted':h.entry.data.get('token')==api.get_token_dict()['token'] if publications else None,
            'reads':read_commands,'all_peers_closed':all(p.closed for p in peers),
            'mode_obligation_present':7 in h.metadata._mode_recovery,
            'published_shuffle':state.attributes.get('shuffle'),
            'published_repeat':state.attributes.get('repeat'),'writes':h.writes,
            'expected_revocation':revoked,'constants_changed':False,'revision_or_cache_changed':False}
    output(f'independent-auth-{history}-{phase}.json',report)
    assert all(p.closed for p in peers) and not h.writes
    assert (h.entities[7].shuffle is None)==revoked, 'Published token revocation must not revive old recovery after token restoration'
    assert (7 not in h.metadata._mode_recovery) if revoked else h.entities[7].repeat=='one'
    assert len(read_commands)==(0 if phase=='auth' and revoked else 1)
    # A later explicit request captures fresh authority, not permanent disablement.
    if history=='persistent-published':await publish('synthetic-active-token')
    # Later valid passive data + registered service use the original mode peer.
    monkeypatch.setattr(wire,'connect',mode_connect)
    await h.emit({**sparse,'pbr':FULL,'plshuffle':False,'plrepeat':0})
    assert h.entities[7].shuffle is False and h.entities[7].repeat=='off'
    await request(hass,h,7,'repeat','one')
    assert h.writes==['audio/7/repeat/3'] and h.entities[7].repeat=='one'
