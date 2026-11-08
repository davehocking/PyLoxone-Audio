"""Pure additive HA contract planning against already qualified native snapshots."""

import pytest
from pyloxone_audio import grouping as g
from test_audio_grouping import SERVER, identities, payload, row


def snapshot(*rows):
    return g.parse_group_snapshot(payload(*rows), SERVER, identities(8))


def updates(plan):
    return [(x.group_id, x.members) for x in plan.updates]


@pytest.mark.parametrize(
    "rows,target,added,expected,scope",
    [
        ((), 1, (2,), [(None, (1, 2))], {1, 2}),
        (
            (row("destination", (2, 1)),),
            1,
            (3,),
            [("destination", (2, 1, 3))],
            {1, 2, 3},
        ),
        ((row("destination", (1, 2)),), 1, (2, 1, 2), [], {1, 2}),
        ((), 1, (), [], {1}),
        (
            (row("destination", (1, 2)), row("source", (3, 4, 5))),
            1,
            (3,),
            [("source", (4, 5)), ("destination", (1, 2, 3))],
            {1, 2, 3, 4, 5},
        ),
        (
            (row("destination", (1, 2)), row("source", (3, 4))),
            2,
            (3,),
            [("source", ()), ("destination", (1, 2, 3))],
            {1, 2, 3, 4},
        ),
        (
            (row("source", (2, 3)),),
            1,
            (2,),
            [("source", ()), (None, (1, 2))],
            {1, 2, 3},
        ),
        (
            (row("source", (2, 3)), row("other", (4, 5))),
            1,
            (2, 4),
            [("source", ()), ("other", ()), (None, (1, 2, 4))],
            {1, 2, 3, 4, 5},
        ),
    ],
)
def test_join_is_additive_preserves_leader_and_reconciles_every_source(
    rows, target, added, expected, scope
):
    before = snapshot(*rows)
    plan = g.plan_join(before, target, added, frozenset(range(1, 9)))
    assert updates(plan) == expected
    assert plan.scope == frozenset(scope)
    assert before == snapshot(*rows)


@pytest.mark.parametrize(
    "rows,target,expected,scope",
    [
        ((row("old", (1, 2, 3)),), 2, [("old", (1, 3))], {1, 2, 3}),
        ((row("old", (1, 2, 3)),), 1, [("old", (2, 3))], {1, 2, 3}),
        ((row("old", (2, 1)),), 1, [("old", ())], {1, 2}),
        ((row("old", (2, 1)),), 2, [("old", ())], {1, 2}),
        ((), 1, [], {1}),
    ],
)
def test_unjoin_preserves_remainder_or_dissolves_only_exact_pair(
    rows, target, expected, scope
):
    plan = g.plan_unjoin(snapshot(*rows), target, frozenset(range(1, 9)))
    assert updates(plan) == expected
    assert plan.scope == frozenset(scope)


@pytest.mark.parametrize(
    "rows,target,added,eligible",
    [
        ((), 1, (9,), {1, 2}),
        ((row("dest", (1, 2)),), 1, (3,), {1, 3}),
        ((row("source", (2, 3)),), 1, (2,), {1, 2}),
        ((), 1, (2,), {2}),
        ((row("fixed", (1, 2), "static"),), 1, (3,), {1, 2, 3}),
        ((row("fixed", (3, 4), "static"), row("dest", (1, 2))), 1, (3,), {1, 2, 3, 4}),
    ],
)
def test_plan_rejects_incomplete_foreign_or_static_affected_scope(
    rows, target, added, eligible
):
    with pytest.raises(ValueError):
        g.plan_join(snapshot(*rows), target, added, frozenset(eligible))


@pytest.mark.parametrize(
    "target,added", [(True, (2,)), (1, (True,)), (1, ("2",)), (1, (0,)), (1, None)]
)
def test_plan_rejects_coerced_or_malformed_player_arguments(target, added):
    with pytest.raises(ValueError):
        g.plan_join(snapshot(), target, added, frozenset(range(1, 9)))
