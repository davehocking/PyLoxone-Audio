"""Native-client-schema synthetic group fixtures, not hardware recordings."""

import json
import pytest
from pyloxone_audio import grouping as g

SERVER = "11111111-2222-3333-4444555555555555"


def action(player):
    return f"{player:08x}-2222-3333-4444555555555555"


def member_uuid(player):
    return f"{player:08x}-2222-3333-4444-555555555555"


def identities(count=6):
    return tuple(
        g.AudioPlayerIdentity(p, action(p), SERVER) for p in range(1, count + 1)
    )


def row(group="group-a", players=(1, 2), kind="dynamic"):
    return {
        "group": group,
        "type": kind,
        "mastervolume": 0,
        "players": [{"playerid": p, "id": member_uuid(p)} for p in players],
    }


def payload(*rows):
    return json.dumps({"audio_sync_event": list(rows)})


def test_explicit_empty_is_authoritative_independent_snapshot():
    result = g.parse_group_snapshot(payload(), SERVER, identities())
    assert result is not None, "explicit empty native snapshot is known, not absent"
    assert result.server_uuid == SERVER
    assert result.groups == ()


def test_native_members_are_leader_first_and_original_ids_are_retained():
    result = g.parse_group_snapshot(payload(row(players=(2, 1))), SERVER, identities())
    assert result is not None
    group = result.groups[0]
    assert (group.group_id, group.kind, group.players) == ("group-a", "dynamic", (2, 1))
    assert group.members[0].control_uuid == member_uuid(2)
    assert g.uuid_key(group.members[0].control_uuid) == g.uuid_key(action(2))


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "not-json",
        "{}",
        "[]",
        "null",
        {"audio_sync_event": None},
        {"audio_sync_event": {}},
        {"audio_sync_event": [None]},
        {"audio_sync_event": [{}]},
        {"audio_sync_event": [row(kind="future")]},
        {"audio_sync_event": [row(players=())]},
        {"audio_sync_event": [row(), row()]},
        {"audio_sync_event": [row(), row("group-b", (2, 3))]},
        {"audio_sync_event": [row(players=(1, 1))]},
        {"audio_sync_event": [row(players=(1, 7))]},
        {"audio_sync_event": [dict(row(), group="../escape")]},
        {"audio_sync_event": [dict(row(), group="new")]},
        {"audio_sync_event": [dict(row(), mastervolume=True)]},
        {"audio_sync_event": [dict(row(), mastervolume=float("nan"))]},
    ],
)
def test_invalid_complete_snapshot_is_unknown_not_partial_or_empty(value):
    assert g.parse_group_snapshot(value, SERVER, identities()) is None


@pytest.mark.parametrize(
    "player_id,uuid",
    [
        (True, member_uuid(1)),
        ("1", member_uuid(1)),
        (1, member_uuid(2)),
        (1, action(1).replace("-", "")),
        (1, " " + member_uuid(1)),
        (1, member_uuid(1).replace("-", "_", 1)),
    ],
)
def test_group_member_requires_exact_numeric_and_valid_uuid_pair(player_id, uuid):
    data = row()
    data["players"][0] = {"playerid": player_id, "id": uuid}
    assert g.parse_group_snapshot(payload(data), SERVER, identities()) is None


@pytest.mark.parametrize(
    "ids,server",
    [
        (
            (
                g.AudioPlayerIdentity(1, action(1), SERVER),
                g.AudioPlayerIdentity(1, action(2), SERVER),
            ),
            SERVER,
        ),
        (
            (
                g.AudioPlayerIdentity(1, action(1), SERVER),
                g.AudioPlayerIdentity(2, action(1), SERVER),
            ),
            SERVER,
        ),
        (
            (
                g.AudioPlayerIdentity(1, action(1), action(99)),
                g.AudioPlayerIdentity(2, action(2), SERVER),
            ),
            SERVER,
        ),
        ((), "not-a-server"),
    ],
)
def test_ambiguous_or_foreign_inventory_does_not_certify_empty(ids, server):
    assert g.parse_group_snapshot(payload(), server, ids) is None


def test_static_dynamic_overlap_is_retained_without_losing_native_order():
    result = g.parse_group_snapshot(
        payload(row("fixed", (1, 2), "static"), row("moving", (3, 1, 2))),
        SERVER,
        identities(),
    )
    assert result is not None
    assert [x.players for x in result.groups] == [(1, 2), (3, 1, 2)]


@pytest.mark.parametrize(
    "token",
    [
        "1" * 32,
        action(1) + "\n",
        action(1) + " ",
        action(1).replace("-", "--", 1),
        1,
        None,
        member_uuid(1).replace("-", "", 1),
    ],
)
def test_uuid_validation_precedes_equivalence(token):
    assert g.uuid_key(token) is None


def test_projection_uses_typed_native_groups_and_never_leaks_partial_membership():
    snapshot = g.parse_group_snapshot(
        payload(row("fixed", (1, 2), "static"), row("moving", (3, 1, 2))),
        SERVER,
        identities(),
    )
    assert g.project_group_members(
        snapshot.groups, {1: "media_player.a", 2: "media_player.b"}
    ) == {1: None, 2: None}
    assert g.project_group_members(
        snapshot.groups, {1: "media_player.a", 2: "media_player.b", 3: "media_player.c"}
    ) == {
        1: ("media_player.c", "media_player.a", "media_player.b"),
        2: ("media_player.c", "media_player.a", "media_player.b"),
        3: ("media_player.c", "media_player.a", "media_player.b"),
    }
