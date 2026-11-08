"""Typed HA entity registration, permission routing and real multi-entry lifecycle."""
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import voluptuous as vol
import yaml
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError, Unauthorized, UnknownUser
from homeassistant.helpers import entity_registry as er
from homeassistant.components.media_player import MediaPlayerEntityFeature as F
from custom_components.loxone.pyloxone_api import audioserver as wire
from test_audio_grouping_ha import action, row, structure
from test_audio_grouping_ha import grouped_setup as grouped_setup
from test_audio_grouping_ha import audio_setup as audio_setup
from test_audioserver_playback import SyntheticAudioSocket
from test_audioserver_playback import rsa_key as rsa_key
from test_room_transport_fences_ha import room_peer as room_peer


@pytest.mark.parametrize('data', [{}, {'action':'stop'}, {'action':'Play'}, {'action':True},
                                 {'action':1}, {'action':None}, {'action':[]},
                                 {'action':'play','volume_level':.2}, {'action':'pause','group_members':[]}])
async def test_registered_room_schema_refuses_invalid_action_or_extra_fields_before_io(hass, room_peer, data):
    with pytest.raises(vol.Invalid):
        await hass.services.async_call('loxone','audio_room_transport',data,target={'entity_id':room_peer.ids[1]},blocking=True)
    assert room_peer.sockets == []


async def test_room_service_uses_normal_ha_control_permissions(hass, room_peer, hass_read_only_user, hass_admin_user):
    p = room_peer
    for user, expected in ((hass_read_only_user, Unauthorized), (None, UnknownUser)):
        with pytest.raises(expected):
            await hass.services.async_call('loxone','audio_room_transport',{'action':'play'},target={'entity_id':p.ids[1]},context=Context(user_id=user.id if user else 'invented-unknown-user'),blocking=True)
    assert p.sockets == []
    await hass.services.async_call('loxone','audio_room_transport',{'action':'play'},target={'entity_id':p.ids[1]},context=Context(user_id=hass_admin_user.id),blocking=True)
    assert p.sent() == ['audio/1/play']


@pytest.mark.parametrize('boundary', ['unknown-group', 'fixed', 'static', 'foreign', 'missing', 'wrong-server',
                                       'unregistered', 'unavailable', 'disabled-playback', 'disabled-command', 'renamed', 'capability'])
async def test_direct_and_registered_room_target_refusals_never_send(hass, room_peer, monkeypatch, boundary):
    p = room_peer
    e = p.g.entities[p.ids[1]]
    target = p.ids[1]
    if boundary == 'unknown-group': p.co.audio_grouping.native.invalidate()
    elif boundary in ('fixed','wrong-server'):
        details = p.co.api.structure_file['controls'][action(1)]['details']
        details['groupObjects' if boundary == 'fixed' else 'server'] = [action(2)] if boundary == 'fixed' else action(99)
    elif boundary == 'static': await p.g.feed(p.entry,row('fixed',(1,2),'static'))
    elif boundary == 'foreign':
        target = er.async_get(hass).async_get_or_create('media_player','other','synthetic-foreign',suggested_object_id='foreign').entity_id
        hass.states.async_set(target,'paused',{'supported_features':int(F.PLAY|F.PAUSE)})
    elif boundary == 'missing': target = 'media_player.synthetic_missing'
    elif boundary == 'unregistered': er.async_get(hass).async_remove(target)
    elif boundary == 'unavailable': p.co.connection_available = False
    elif boundary == 'disabled-playback': e._audio_commands_enabled = False
    elif boundary == 'disabled-command': e._audio_commands = None
    elif boundary == 'renamed':
        er.async_get(hass).async_update_entity(target,new_entity_id='media_player.synthetic_renamed')
        await hass.async_block_till_done()
    elif boundary == 'capability': monkeypatch.setattr(e,'_room_transport_supported',lambda _:False)
    if boundary not in ('foreign','missing','renamed'):
        with pytest.raises(HomeAssistantError):
            await e.async_audio_room_transport('play')
    # HA may correctly skip unknown/unavailable targets rather than raise.
    try:
        await hass.services.async_call('loxone','audio_room_transport',{'action':'play'},target={'entity_id':target},blocking=True)
    except HomeAssistantError:
        pass
    assert p.sockets == []
    p.co.api.send_websocket_command.assert_not_awaited()


async def test_full_inherited_service_definitions_and_translations_preserved(hass, room_peer):
    root = Path(__file__).resolve().parents[2]
    host = Path(os.environ['PYLOXONE_AUDIO_HOST_ROOT'])
    current = yaml.safe_load((host/'custom_components/loxone/services.yaml').read_text())
    inherited = yaml.safe_load((root/'tests/adapter/fixtures/inherited-services.yaml').read_text())
    assert {key:current[key] for key in inherited} == inherited
    assert set(current) == set(inherited)|{'audio_room_transport','audio_room_volume','audio_group_manage'}
    for name,digest in json.loads((root/'tests/adapter/fixtures/gm03-inherited-translations.json').read_text()).items():
        relative=Path(name).relative_to('adapters/pyloxone/overlay')
        assert hashlib.sha256((host/relative).read_bytes()).hexdigest()==digest,name
    for service in ('audio_room_volume','audio_group_manage'):
        assert current[service]['name'] and current[service]['description']
        assert current[service]['target']['entity']=={'domain':'media_player','integration':'loxone'}
        assert all(field.get('name') for field in current[service]['fields'].values())
    spec = current['audio_room_transport']
    assert spec['fields']['action']['required'] is True
    assert spec['fields']['action']['selector']['select']['options'] == ['play','pause']
    assert spec['target']['entity'] == {'domain':'media_player','integration':'loxone'}
    # Validate/load the actual integration description with Core's own loader.
    # Loading EVERY unrelated Core service needs optional conversation packages
    # absent from this audio test environment, not from the delivered component.
    from homeassistant.helpers.service import _load_services_file
    from homeassistant.loader import async_get_integration
    integration = await async_get_integration(hass, 'loxone')
    descriptions = await hass.async_add_executor_job(_load_services_file, integration)
    assert 'audio_room_transport' in descriptions
    assert 'refresh_token' in descriptions
    assert 'reload' in descriptions


async def test_service_shared_across_actual_entries_unload_and_reload_not_captured_owner(hass, grouped_setup, audio_setup, monkeypatch, rsa_key):
    g = grouped_setup
    first, co1, ids1 = await g.setup()
    await g.feed(first,row('first',(1,2)))
    handler = hass.services.async_services()['loxone']['audio_room_transport']
    # A second invented server has distinct identities; no household config.
    second_source = structure()
    new_server, new_state = action(99), action(98)
    second_source['mediaServer'] = {new_server:{'uuidAction':new_server,'type':2,'states':{'grouping':new_state}}}
    second_source['controls'] = {action(p+20):{**c,'uuidAction':action(p+20),'name':f'Second synthetic {p}',
        'details':{**c['details'],'playerid':p+20,'server':new_server}}
        for p,c in enumerate(second_source['controls'].values(),1)}
    g.source.clear();g.source.update(copy.deepcopy(second_source))
    second = await audio_setup.setup(playback=True,title='Second synthetic Miniserver')
    co2 = hass.data['loxone'][second.entry_id]
    co2.audio_grouping.native.observe(json.dumps({'audio_sync_event':[]}))
    co2.audio_grouping.notify()
    await hass.async_block_till_done()
    ids2 = {p:er.async_get(hass).async_get_entity_id('media_player','loxone',action(p)) for p in range(21,27)}
    assert all(ids2.values())
    assert hass.services.async_services()['loxone']['audio_room_transport'] is handler
    sockets = []
    class Socket(SyntheticAudioSocket):
        async def send(self,message):
            if message.startswith('audio/') and message!='audio/cfg/getkey/full':
                self.sent.append(message)
                player,mode=message.split('/')[1:]
                assert player in ('1','21')
                self.queue.put_nowait(json.dumps({mode+'_result':True}))
            else: await super().send(message)
    def connect(*a,**k):
        s=Socket(rsa_key);sockets.append(s);return s
    monkeypatch.setattr(wire,'connect',connect)
    for co in (co1,co2): co.audio_commands._credentials=lambda:('synthetic-user','synthetic-active-token')
    for entity_id in (ids1[1],ids2[21]):
        await hass.services.async_call('loxone','audio_room_transport',{'action':'play'},target={'entity_id':entity_id},blocking=True)
    assert [m for s in sockets for m in s.sent if m in ('audio/1/play','audio/21/play')] == ['audio/1/play','audio/21/play']
    old_owner = co2.audio_grouping
    assert await hass.config_entries.async_unload(second.entry_id)
    assert old_owner.native._closed and not old_owner.native._requests
    await hass.services.async_call('loxone','audio_room_transport',{'action':'pause'},target={'entity_id':ids1[1]},blocking=True)
    assert await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()
    reloaded=hass.data['loxone'][second.entry_id]
    assert reloaded.audio_grouping is not old_owner
    reloaded.audio_grouping.native.observe(json.dumps({'audio_sync_event':[]}));reloaded.audio_grouping.notify()
    reloaded.audio_commands._credentials=lambda:('synthetic-user','synthetic-active-token')
    await hass.services.async_call('loxone','audio_room_transport',{'action':'pause'},target={'entity_id':ids2[21]},blocking=True)
    assert hass.services.async_services()['loxone']['audio_room_transport'] is handler
    assert all(s.closed for s in sockets)
    assert co1.audio_commands._socket is None and reloaded.audio_commands._socket is None
    co1.api.send_websocket_command.assert_not_awaited();reloaded.api.send_websocket_command.assert_not_awaited()
