"""Exact automation intent: no additive target inheritance or silent stealing."""
import inspect
import pytest
from pyloxone_audio import grouping as g
from test_group_planning import snapshot,updates
from test_audio_grouping import row


def manage(before,action,target,members=(),group_id=None,override=False,eligible=None):
    assert 'override_existing_membership'in inspect.signature(g.plan_manage).parameters,'Explicit automation transfer intent is not implemented'
    return g.plan_manage(before,action,target,members,group_id,frozenset(range(1,9))if eligible is None else frozenset(eligible),override_existing_membership=override)


@pytest.mark.parametrize('rows,target,members,expected,scope',[
 ([],1,(2,),[(None,(1,2))],{1,2}),
 ([row('old',(1,2,3))],1,(4,),[('old',(2,3)),(None,(1,4))],{1,2,3,4}),
 ([row('old',(2,1,3))],1,(4,),[('old',(2,3)),(None,(1,4))],{1,2,3,4}),
 ([row('old',(1,2)),row('other',(3,4,5))],1,(3,),[('old',()),('other',(4,5)),(None,(1,3))],{1,2,3,4,5}),
 ([row('old',(2,1,3))],1,(2,3),[('old',()),(None,(1,2,3))],{1,2,3}),
 ([row('unrelated',(7,8)),row('old',(2,3))],1,(2,),[('old',()),(None,(1,2))],{1,2,3}),
])
def test_create_override_extracts_chosen_leader_and_only_selected_members(rows,target,members,expected,scope):
    before=snapshot(*rows)
    plan=manage(before,'create',target,members,override=True)
    assert updates(plan)==expected
    assert plan.scope==frozenset(scope)
    assert before==snapshot(*rows)


@pytest.mark.parametrize('override',[False,True])
def test_already_exact_membership_and_leader_is_idempotent_even_different_follower_order(override):
    plan=manage(snapshot(row('current',(1,3,2))),'create',1,(2,3),override=override)
    assert updates(plan)==[] and plan.scope==frozenset({1,2,3})


@pytest.mark.parametrize('rows,target,members,eligible',[
 ([row('occupied',(2,3))],1,(2,),set(range(1,9))),
 ([row('occupied',(1,3))],1,(2,),set(range(1,9))),
])
def test_default_off_rejects_conflicts_before_any_update(rows,target,members,eligible):
    with pytest.raises(ValueError):manage(snapshot(*rows),'create',target,members,eligible=eligible)


@pytest.mark.parametrize('rows,eligible',[
 ([row('fixed',(1,2),'static')],set(range(1,9))),
 ([row('fixed',(3,4),'static')],set(range(1,9))),
 ([row('old',(1,2,3))],{1,3,4}),
])
def test_override_cannot_touch_fixed_or_unavailable_unselected_group_members(rows,eligible):
    with pytest.raises(ValueError):manage(snapshot(*rows),'create',1,(3,4),override=True,eligible=eligible)


@pytest.mark.parametrize('override',[None,1,'true'])
def test_override_requires_a_literal_boolean(override):
    with pytest.raises(ValueError):manage(snapshot(),'create',1,(2,),override=override)


def test_add_override_remains_additive_and_keeps_actual_destination_leader():
    plan=manage(snapshot(row('destination',(2,1)),row('source',(3,4,5))),'add',1,(3,),group_id='destination',override=True)
    assert updates(plan)==[('source',(4,5)),('destination',(2,1,3))]
    assert plan.scope==frozenset({1,2,3,4,5})


@pytest.mark.parametrize('action',['remove','destroy'])
def test_override_is_not_silently_applied_to_other_operations(action):
    with pytest.raises(ValueError):manage(snapshot(row('current',(1,2))),action,1,group_id='current',override=True)
