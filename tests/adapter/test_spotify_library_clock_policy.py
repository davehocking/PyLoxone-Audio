"""Bounded sample-rate policy, using synthetic immutable native timestamps."""
# ruff: noqa: S101, SLF001, INP001, ANN001, D103, PLR2004

from dataclasses import replace
from datetime import timedelta

import pytest
from homeassistant.util import dt as dt_util

from custom_components.loxone import spotify_continuity as continuity
from test_spotify_continuity import native


def samples(elapsed=0.25, progress=0.25):
    now = dt_util.utcnow()
    started = now - timedelta(seconds=elapsed)
    old = replace(native(), source="Local Library", position=45.0, native_mode="play",
                  received_at=started, position_updated_at=started)
    new = replace(old, position=45.0 + progress, received_at=now, position_updated_at=now)
    return old, new


@pytest.mark.parametrize("elapsed", [0.05, 0.1, 0.25, 1.0, 4.0])
def test_measured_ordinary_rate_is_not_a_newer_selection(elapsed):
    old, new = samples(elapsed, elapsed)
    assert continuity._library_clock_unchanged(old, new)


@pytest.mark.parametrize(("elapsed", "progress"), [
    (0.001, 0.001), (0.25, 0.001), (0.25, -0.001), (0.25, 0.35),
    (0.25, 0.15), (4.0, 4.051), (4.0, 3.949), (0.25, 20.0),
])
def test_uncertain_or_discontinuous_rate_is_not_authority(elapsed, progress):
    old, new = samples(elapsed, progress)
    assert not continuity._library_clock_unchanged(old, new)


@pytest.mark.parametrize("mode", ["pause", "stop"])
def test_nonplaying_clock_does_not_gain_progress_tolerance(mode):
    old, new = samples()
    assert not continuity._library_clock_unchanged(replace(old, native_mode=mode), replace(new, native_mode=mode))


@pytest.mark.parametrize("change", [
    "missing-start", "missing-end", "same-anchor", "backward-anchor", "future-anchor",
    "future-envelope", "missing-envelope", "reordered-envelope", "unreceived-clock",
    "old-overlap",
])
def test_invalid_sample_timing_cannot_establish_natural_progress(change):
    old, new = samples()
    if change == "missing-start":
        old = replace(old, position_updated_at=None)
    elif change == "missing-end":
        new = replace(new, position_updated_at=None)
    elif change == "same-anchor":
        new = replace(new, position_updated_at=old.position_updated_at)
    elif change == "backward-anchor":
        new = replace(new, position_updated_at=old.position_updated_at - timedelta(seconds=1))
    elif change == "future-anchor":
        new = replace(new, position_updated_at=dt_util.utcnow() + timedelta(seconds=1))
    elif change == "future-envelope":
        new = replace(new, received_at=dt_util.utcnow() + timedelta(seconds=1))
    elif change == "missing-envelope":
        new = replace(new, received_at=None)
    elif change == "reordered-envelope":
        new = replace(new, received_at=old.received_at - timedelta(seconds=1))
    elif change == "unreceived-clock":
        old = replace(old, received_at=old.position_updated_at - timedelta(seconds=1))
    else:
        # A delayed old frame spans the purported new anchor: no positive ordering.
        old = replace(old, received_at=new.position_updated_at + timedelta(microseconds=1))
        new = replace(new, received_at=new.received_at + timedelta(microseconds=2))
    assert not continuity._library_clock_unchanged(old, new)


def test_frozen_static_sample_is_still_accepted_without_rebasing():
    old, _new = samples()
    assert continuity._library_clock_unchanged(old, old)
    assert continuity._library_clock_unchanged(old, replace(old, received_at=dt_util.utcnow()))


def test_later_good_sample_is_compared_to_original_not_a_seeked_rebase():
    old, new = samples(elapsed=1.0, progress=1.0)
    changed = replace(new, position=50.0)
    assert not continuity._library_clock_unchanged(old, changed)
    assert continuity._library_clock_unchanged(old, new)
    assert old.position == 45.0
