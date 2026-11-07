"""Permanent F1 owning-HA reproductions plus withdrawal/recovery controls.

The first three functions preserve original reviewer assertions and case names.
External command I/O is synthetic; no household access.
"""
import json

import pytest
from homeassistant.components.media_player import MediaPlayerEntityFeature as F
from homeassistant.exceptions import HomeAssistantError
from test_audio_grouping_ha import (
    grouped_setup as grouped_setup,
    audio_setup as audio_setup,
    STATE,
    payload,
    row,
)


async def test_malformed_large_volume_must_invalidate_without_escaping_callback(hass, grouped_setup):
    g=grouped_setup
    entry,co,ids=await g.setup()
    await g.feed(entry,row('old',(1,2)),row('outside',(5,6)))
    malformed=row('old',(1,2))
    malformed['mastervolume']=10**400
    # A 401-digit JSON integer is far below this parser's 512KiB wire limit.
    # Ordinary malformed TEXT input must become unknown, never an exception.
    await g.callbacks[entry.entry_id]['callback']({STATE:payload(malformed,row('outside',(5,6)))})
    await hass.async_block_till_done()
    assert co.audio_grouping.native.snapshot is None
    assert not hass.states.get(ids[1]).attributes['supported_features'] & F.GROUPING


async def test_malformed_large_volume_must_not_leave_stale_membership_actionable(hass, grouped_setup):
    g=grouped_setup
    entry,co,ids=await g.setup()
    g.wire(entry,co)
    await g.feed(entry,row('old',(1,2)),row('outside',(5,6)))
    malformed=row('old',(1,2));malformed['mastervolume']=10**400
    escaped=None
    try:
        await g.callbacks[entry.entry_id]['callback']({STATE:payload(malformed,row('outside',(5,6)))})
    except OverflowError as exc:
        escaped=type(exc).__name__
    snapshot_retained=co.audio_grouping.native.snapshot is not None
    rejected=False
    try:
        await hass.services.async_call('media_player','unjoin',{'entity_id':ids[1]},blocking=True)
    except HomeAssistantError:
        rejected=True
    diagnostic={'escaped_callback_exception':escaped,'old_snapshot_retained':snapshot_retained,'request_rejected':rejected,'native_dispatches':g.calls,'outside_members':hass.states.get(ids[5]).attributes.get('group_members')}
    print('REVIEWER_MALFORMED_DIAGNOSTIC='+json.dumps(diagnostic,sort_keys=True))
    assert rejected and not g.calls, diagnostic


async def test_ordinary_pair_control_and_malformed_string_invalidation(hass, grouped_setup):
    g=grouped_setup
    entry,co,ids=await g.setup()
    g.wire(entry,co)
    await g.feed(entry,row('old',(1,2)),row('outside',(5,6)))
    await hass.services.async_call('media_player','unjoin',{'entity_id':ids[1]},blocking=True)
    assert g.calls==['audio/cfg/dgroup/update/old']
    assert hass.states.get(ids[5]).attributes['group_members']==[ids[5],ids[6]]
    await g.callbacks[entry.entry_id]['callback']({STATE:'not JSON'})
    assert co.audio_grouping.native.snapshot is None
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call('media_player','join',{'entity_id':ids[1],'group_members':[ids[2]]},blocking=True)
    assert g.calls==['audio/cfg/dgroup/update/old']


@pytest.mark.parametrize(
    "volume",
    [
        pytest.param(10**400, id="huge-positive-int"),
        pytest.param(-(10**400), id="huge-negative-int"),
        pytest.param(float("inf"), id="infinity"),
        pytest.param(float("nan"), id="nan"),
        pytest.param(True, id="bool"),
        pytest.param({}, id="object"),
    ],
)
async def test_numeric_invalidation_withdraws_all_authority_until_fresh_feedback(
    hass, grouped_setup, volume
):
    g = grouped_setup
    entry, co, ids = await g.setup()
    g.wire(entry, co)
    await g.feed(entry, row("old", (1, 2)), row("outside", (5, 6)))
    for p in (1, 2):
        assert hass.states.get(ids[p]).attributes["group_members"] == [ids[1], ids[2]]
    assert hass.states.get(ids[5]).attributes["group_members"] == [ids[5], ids[6]]
    malformed = dict(row("old", (1, 2)), mastervolume=volume)
    await g.callbacks[entry.entry_id]["callback"](
        {STATE: payload(malformed, row("outside", (5, 6)))}
    )
    await hass.async_block_till_done()
    assert co.audio_grouping.native.snapshot is None
    for entity_id in ids.values():
        state = hass.states.get(entity_id)
        assert state.state != "unavailable"
        assert state.attributes["supported_features"] & F.VOLUME_SET
        assert not state.attributes["supported_features"] & F.GROUPING
        assert not state.attributes.get("group_members")
    entity = g.entities[ids[1]]
    with pytest.raises(HomeAssistantError):
        await entity.async_join_players([ids[2]])
    with pytest.raises(HomeAssistantError):
        await entity.async_unjoin_player()
    for service, data in [
        ("join", {"entity_id": ids[1], "group_members": [ids[2]]}),
        ("unjoin", {"entity_id": ids[1]}),
    ]:
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call("media_player", service, data, blocking=True)
    assert g.calls == []
    co.api.send_websocket_command.assert_not_awaited()
    # Fresh feedback, not an attempted/replayed command, restores the capability.
    await g.feed(entry, row("fresh", (2, 1)), row("outside", (5, 6)))
    assert g.calls == []
    assert co.audio_grouping.native.snapshot is not None
    assert hass.states.get(ids[1]).attributes["supported_features"] & F.GROUPING
    assert hass.states.get(ids[1]).attributes["group_members"] == [ids[2], ids[1]]
    assert hass.states.get(ids[5]).attributes["group_members"] == [ids[5], ids[6]]
    await hass.services.async_call(
        "media_player", "unjoin", {"entity_id": ids[1]}, blocking=True
    )
    await hass.async_block_till_done()
    assert g.calls == ["audio/cfg/dgroup/update/fresh"]
    assert hass.states.get(ids[1]).attributes["group_members"] == [ids[1]]
    assert hass.states.get(ids[2]).attributes["group_members"] == [ids[2]]
    assert hass.states.get(ids[5]).attributes["group_members"] == [ids[5], ids[6]]
    assert hass.states.get(ids[6]).attributes["group_members"] == [ids[5], ids[6]]
