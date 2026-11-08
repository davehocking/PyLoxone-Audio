"""F1 numeric feedback regressions; synthetic native snapshots only."""

import json
import sys

import pytest

from pyloxone_audio.grouping import parse_group_snapshot
from test_audio_grouping import SERVER, identities, row


@pytest.mark.parametrize("wire", [False, True], ids=["dict", "json"])
@pytest.mark.parametrize(
    "volume",
    [
        pytest.param(10**400, id="huge-positive-int"),
        pytest.param(-(10**400), id="huge-negative-int"),
        pytest.param(float("inf"), id="positive-infinity"),
        pytest.param(float("-inf"), id="negative-infinity"),
        pytest.param(float("nan"), id="nan"),
        pytest.param(True, id="true"),
        pytest.param(False, id="false"),
        pytest.param(None, id="null"),
        pytest.param({}, id="object"),
        pytest.param([], id="array"),
        pytest.param("0", id="string"),
    ],
)
def test_unusable_volume_is_all_unknown_without_numeric_exception(volume, wire):
    malformed = dict(row(), mastervolume=volume)
    value = {"audio_sync_event": [row("outside", (5, 6)), malformed]}
    if wire:
        value = json.dumps(value)
    assert parse_group_snapshot(value, SERVER, identities()) is None


@pytest.mark.parametrize("wire", [False, True], ids=["dict", "json"])
@pytest.mark.parametrize(
    "volume",
    [
        pytest.param(0, id="zero-int"),
        pytest.param(-12, id="negative-int"),
        pytest.param(150, id="above-100-int"),
        pytest.param(10**300, id="large-representable-int"),
        pytest.param(0.0, id="zero-float"),
        pytest.param(-12.5, id="negative-float"),
        pytest.param(150.25, id="above-100-float"),
        pytest.param(sys.float_info.max, id="max-finite-float"),
    ],
)
def test_finite_volume_is_preserved_without_range_or_normalisation(volume, wire):
    value = {"audio_sync_event": [dict(row(), mastervolume=volume)]}
    if wire:
        value = json.dumps(value)
    snapshot = parse_group_snapshot(value, SERVER, identities())
    assert snapshot is not None
    assert snapshot.groups[0].master_volume == volume
    assert type(snapshot.groups[0].master_volume) is type(volume)
    assert snapshot.groups[0].players == (1, 2)


@pytest.mark.parametrize("number", ["1e400", "-1e400"])
def test_json_exponent_overflow_is_unknown(number):
    value = json.dumps({"audio_sync_event": [row()]})
    value = value.replace('"mastervolume": 0', '"mastervolume": ' + number)
    assert parse_group_snapshot(value, SERVER, identities()) is None
