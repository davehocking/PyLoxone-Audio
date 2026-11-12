"""Additional actual-service isolation/late-feedback/revocation controls.

Shortened deadlines are supplementary only, not the owner eight-second oracle.
"""
import asyncio
import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from custom_components.loxone.const import SENDDOMAIN
from test_audio_grouping_ha import action, row, payload, STATE
from test_audio_grouping_ha import grouped_setup as grouped_setup
from test_audio_grouping_ha import audio_setup as audio_setup
from test_audioserver_playback import rsa_key as rsa_key


@pytest.mark.parametrize('phase', ['first-unconfirmed', 'second-unconfirmed', 'outside-volume', 'cancel'])
@pytest.mark.parametrize('players', [(1, 2), (4, 3)])
async def test_actual_feedback_is_not_target_and_late_feedback_never_replays(hass, grouped_setup, players, phase):
    g=grouped_setup; entry,co,ids=await g.setup()
    first,second=players
    await g.feed(entry,row('pair',players))
    callback=g.callbacks[entry.entry_id]['callback']
    await callback({**{f'play-{p}':2 for p in ids},**{f'volume-{p}':20 for p in ids},f'volume-{first}':10,f'volume-{second}':38})
    await hass.async_block_till_done()
    owner=co.audio_grouping;owner.native.timeout=.12
    writes=[];sent=asyncio.Event();confirm=False
    async def feedback(event):
        writes.append(dict(event.data)); sent.set()
        p=next(p for p in ids if action(p)==event.data['uuid'])
        if confirm or (phase=='second-unconfirmed' and p==first):
            await callback({f'volume-{p}':int(event.data['value'].split('/')[1])})
        elif phase=='outside-volume': await callback({f'volume-{second}':50})
    remove=hass.bus.async_listen(SENDDOMAIN,feedback)
    task=asyncio.create_task(hass.services.async_call('loxone','audio_group_volume',{'volume_percent':7},target={'entity_id':ids[second]},blocking=True))
    try:
        await sent.wait()
        if phase=='cancel':task.cancel()
        result=(await asyncio.gather(task,return_exceptions=True))[0]
        assert isinstance(result, (HomeAssistantError,asyncio.CancelledError))
        assert writes==[{'uuid':action(first),'value':'volume/0'}]+([{'uuid':action(second),'value':'volume/21'}] if phase=='second-unconfirmed' else [])
        await hass.async_block_till_done()
        assert not owner.native.uncertain and owner.control_descriptor(first) is not None
        expected_first=0 if phase=='second-unconfirmed' else 10
        expected_second=50 if phase=='outside-volume' else 38
        assert g.entities[ids[first]]._room_volume_percent==expected_first
        assert g.entities[ids[second]]._room_volume_percent==expected_second
        assert hass.states.get(ids[first]).attributes['loxone_group_volume_level']==(expected_first+expected_second)/200
        before=list(writes)
        await callback({f'volume-{first}':0})
        await hass.async_block_till_done()
        assert writes==before and hass.states.get(ids[first]).attributes['loxone_group_volume_level']==expected_second/200
        confirm=True
        await hass.services.async_call('loxone','audio_room_volume',{'volume_percent':21},target={'entity_id':ids[second]},blocking=True)
        assert writes==before+[{'uuid':action(second),'value':'volume/21'}]
        assert g.entities[ids[first]]._room_volume_percent==0
        assert hass.states.get(ids[first]).attributes['loxone_group_volume_level']==.11
        assert not owner.native._scope and not owner.native._requests and not owner.native._tasks
    finally:
        task.cancel();await asyncio.gather(task,return_exceptions=True);remove()


@pytest.mark.parametrize('boundary', ['auth-aba','registry-aba','source-aba','group-aba','unknown','disconnect','unload'])
async def test_revoked_actual_volume_never_continues_and_unknown_topology_stays_closed(hass,grouped_setup,boundary):
    g=grouped_setup;entry,co,ids=await g.setup()
    await g.feed(entry,row('pair',(2,1)),row('untouched',(3,4)))
    callback=g.callbacks[entry.entry_id]['callback']
    await callback({**{f'volume-{p}':10*p for p in ids},**{f'play-{p}':2 for p in ids}})
    await hass.async_block_till_done()
    owner=co.audio_grouping;owner.native.timeout=.15
    writes=[]
    async def on_send(event):
        writes.append(dict(event.data))
        if boundary=='auth-aba':
            original=co.api.get_token_dict
            try:
                for token in ('synthetic-replacement-token',original()['token']):
                    co.api.get_token_dict=lambda token=token:{'token':token}
                    co._on_token_changed({'token':token})
            finally:co.api.get_token_dict=original
        elif boundary=='registry-aba':
            registry=er.async_get(hass)
            registry.async_update_entity(ids[1],disabled_by=er.RegistryEntryDisabler.USER)
            owner.notify()
            registry.async_update_entity(ids[1],disabled_by=None)
            owner.notify()
        elif boundary=='source-aba':
            entity=g.entities[ids[1]]
            entity._source_task=asyncio.current_task();owner.notify()
            entity._source_task=None;owner.notify()
        elif boundary=='group-aba':
            await callback({STATE:payload(row('different',(2,5)),row('untouched',(3,4)))})
            await callback({STATE:payload(row('pair',(2,1)),row('untouched',(3,4)))})
        elif boundary=='unknown':await callback({STATE:'{}'})
        elif boundary=='disconnect':g.callbacks[entry.entry_id]['on_state']('disconnected')
        else:await owner.async_close()
    remove=hass.bus.async_listen(SENDDOMAIN,on_send)
    try:
        with pytest.raises((HomeAssistantError,asyncio.CancelledError)):
            await hass.services.async_call('loxone','audio_group_volume',{'volume_percent':35},target={'entity_id':ids[1]},blocking=True)
        assert writes==[{'uuid':action(2),'value':'volume/40'}]
        assert not owner.native._scope and not owner.native._tasks and not owner.native._requests
        if boundary in ('unknown','disconnect','unload'):
            assert owner.native.snapshot is None
            if boundary == 'disconnect':
                # HA skips unavailable entities before invoking the adapter.
                assert not g.entities[ids[1]].available
                await hass.services.async_call('media_player','join',{'group_members':[ids[5]]},target={'entity_id':ids[1]},blocking=True)
            else:
                with pytest.raises(HomeAssistantError):
                    await hass.services.async_call('media_player','join',{'group_members':[ids[5]]},target={'entity_id':ids[1]},blocking=True)
            assert len(writes)==1
        elif boundary!='registry-aba':
            # Re-registration itself is intentionally not performed here.
            # A fresh management request may use still-current membership.
            g.wire(entry,co)
            await hass.services.async_call('media_player','join',{'group_members':[ids[5]]},target={'entity_id':ids[1]},blocking=True)
            assert g.calls==['audio/cfg/dgroup/update/pair/2,1,5']
    finally:remove()


async def test_qualified_owner_peer_status_rejection_is_unknown_and_closes_authenticated_socket(
    hass, grouped_setup, audio_setup, monkeypatch, rsa_key,
):
    """Exercise the exact added fixture deterministically, not a timer race."""
    from pathlib import Path
    from types import SimpleNamespace
    import conftest
    from custom_components.loxone.pyloxone_api import audioserver as wire
    from pyloxone_audio import AudioCommandError
    from test_audioserver_playback import SyntheticAudioSocket

    fixture = conftest._owner_oracle_read_peer.__wrapped__(
        SimpleNamespace(path=Path('test_owner_volume_recovery_ha.py'),
                        getfixturevalue=lambda name: {'hass': hass, 'audio_setup': audio_setup}[name]), monkeypatch,
    )
    next(fixture)
    g = grouped_setup
    _, co, _ = await g.setup()
    sockets = []

    def connect(*args, **kwargs):
        socket = SyntheticAudioSocket(rsa_key)
        sockets.append(socket)
        return socket

    monkeypatch.setattr(wire, 'connect', connect)
    co.audio_commands._credentials = lambda: ('synthetic-user', 'synthetic-active-token')
    try:
        with pytest.raises(AudioCommandError, match='missing or ambiguous'):
            await co.audio_commands.async_player_status(3, is_current=lambda: True)
        assert len(sockets) == 1 and sockets[0].closed
        assert sockets[0].sent[-1] == 'audio/3/status'
        assert len(sockets[0].sent) == 3  # getkey, real synthetic auth, status
        assert co.audio_commands._socket is None and not co.audio_commands._lock.locked()
        assert co.audio_metadata.get(3) is None
    finally:
        next(fixture, None)
