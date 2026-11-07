"""Offline acceptance of HA action metadata and legacy explicit-token callers.

Uses the real integration and registered service, with only synthetic external I/O.
No rendered-browser or hardware claim is made by these tests.
"""
import asyncio

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.service import _load_services_file
from homeassistant.loader import async_get_integration

from test_audio_grouping_ha import grouped_setup, audio_setup, row, structure
from test_automation_group_intent_ha import manage


async def test_core_loads_ordinary_action_description_without_internal_token_fields(hass, grouped_setup):
    g = grouped_setup
    entry, co, ids = await g.setup()
    await g.feed(entry)
    integration = await async_get_integration(hass, 'loxone')
    descriptions = await hass.async_add_executor_job(_load_services_file, integration)
    spec = descriptions['audio_group_manage']
    assert set(spec['fields']) == {'action', 'members', 'override_existing_membership'}
    assert spec['target']['entity'] == [{'domain': ['media_player'], 'integration': 'loxone'}]
    assert spec['fields']['action']['required'] is True
    assert spec['fields']['action']['selector']['select']['options'] == ['create', 'add', 'remove', 'destroy']
    checkbox = spec['fields']['override_existing_membership']
    assert checkbox['name'] == 'Override any existing group membership'
    assert checkbox['default'] is False
    assert checkbox['selector'] == {'boolean': {}}
    assert 'interrupted' in checkbox['description']
    assert 'revision' not in spec['fields'] and 'group_id' not in spec['fields']


@pytest.mark.parametrize('player', range(1, 13))
async def test_same_automatic_group_action_works_for_each_of_twelve_registered_rooms(hass, grouped_setup, player):
    g = grouped_setup
    g.source.clear()
    g.source.update(structure(count=12))
    entry, co, _ = await g.setup()
    ids = {e._audio_player_id: e.entity_id for e in g.entities.values()}
    assert set(ids) == set(range(1, 13))
    g.wire(entry, co)
    await g.feed(entry)
    other = player % 12 + 1
    await manage(hass, ids, player, members=(other,))
    assert g.calls == [f'audio/cfg/dgroup/update/new/{player},{other}']
    assert co.audio_grouping.native.snapshot.groups[0].players == (player, other)


async def test_automatic_add_override_keeps_destination_leader_and_unselected_members(hass, grouped_setup):
    g = grouped_setup
    entry, co, ids = await g.setup()
    g.wire(entry, co)
    await g.feed(entry, row('destination', (2, 1)), row('old', (3, 4, 5)))
    await manage(hass, ids, 1, action='add', members=(3,), override_existing_membership=True)
    assert g.calls == ['audio/cfg/dgroup/update/old/4,5', 'audio/cfg/dgroup/update/destination/2,1,3']
    assert {r.group_id: r.players for r in co.audio_grouping.native.snapshot.groups} == {
        'old': (4, 5), 'destination': (2, 1, 3)}


@pytest.mark.parametrize('action,command', [
    ('remove', 'audio/cfg/dgroup/update/actual/2,3'),
    ('destroy', 'audio/cfg/dgroup/update/actual'),
])
async def test_automatic_edit_resolves_exact_group_without_form_tokens(hass, grouped_setup, action, command):
    g = grouped_setup
    entry, co, ids = await g.setup()
    g.wire(entry, co)
    await g.feed(entry, row('actual', (1, 2, 3)), row('untouched', (4, 5)))
    await manage(hass, ids, 1, action=action, members=())
    assert g.calls == [command]
    assert any(r.group_id == 'untouched' and r.players == (4, 5) for r in co.audio_grouping.native.snapshot.groups)


async def test_existing_r10_explicit_tokens_remain_authoritative_for_add_and_destroy(hass, grouped_setup):
    g = grouped_setup
    entry, co, ids = await g.setup()
    g.wire(entry, co)
    await g.feed(entry, row('actual', (2, 1)))
    d = co.audio_grouping.control_descriptor(1)
    await manage(hass, ids, 1, action='add', members=(3,), revision=d['revision'], group_id=d['group_id'])
    assert g.calls == ['audio/cfg/dgroup/update/actual/2,1,3']
    d = co.audio_grouping.control_descriptor(1)
    with pytest.raises(HomeAssistantError):
        await manage(hass, ids, 1, action='destroy', members=(), revision=d['revision'], group_id='wrong-literal')
    assert len(g.calls) == 1
    await manage(hass, ids, 1, action='destroy', members=(), revision=d['revision'], group_id=d['group_id'])
    assert g.calls == ['audio/cfg/dgroup/update/actual/2,1,3', 'audio/cfg/dgroup/update/actual']


@pytest.mark.parametrize('fault', ['static', 'unknown', 'uncertain', 'unavailable-remainder'])
async def test_override_cannot_bypass_actual_native_ownership_or_remainder_eligibility(hass, grouped_setup, fault):
    g = grouped_setup
    entry, co, ids = await g.setup()
    g.wire(entry, co)
    await g.feed(entry, row('old', (1, 2, 3), 'static' if fault == 'static' else 'dynamic'))
    if fault == 'unknown':
        co.audio_grouping.native.invalidate()
    elif fault == 'uncertain':
        co.audio_grouping.native.uncertain = True
    elif fault == 'unavailable-remainder':
        g.entities[ids[2]]._attr_available = False
    with pytest.raises(HomeAssistantError):
        await manage(hass, ids, 1, members=(4,), override_existing_membership=True)
    assert g.calls == []


async def test_automatic_intent_latches_auth_aba_while_waiting_for_shared_lock(hass, grouped_setup):
    g = grouped_setup
    entry, co, ids = await g.setup()
    g.wire(entry, co)
    await g.feed(entry)
    native = co.audio_grouping.native
    token = co.api.get_token_dict()
    original = co.api.get_token_dict
    await native._lock.acquire()
    task = asyncio.create_task(manage(hass, ids, 1, override_existing_membership=True))
    try:
        for _ in range(30):
            if native._requests:
                break
            await asyncio.sleep(0)
        assert native._requests
        co.api.get_token_dict = lambda: {**token, 'token': 'different-synthetic-token'}
        native.observe_current()
        co.api.get_token_dict = original
        native.observe_current()
    finally:
        co.api.get_token_dict = original
        native._lock.release()
        result = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 3)
    assert isinstance(result[0], HomeAssistantError)
    assert g.calls == []
    assert not native._requests and not native._tasks
