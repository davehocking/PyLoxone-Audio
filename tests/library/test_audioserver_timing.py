"""Synthetic seconds-field tests for the passive seeking prerequisite."""

from __future__ import annotations

# Assertions, magic fixture values and namespace tests are intentional.
# ruff: noqa: S101, INP001, PLR2004

import pytest

from pyloxone_audio.native import parse_audio_events


@pytest.mark.parametrize("field", ["time", "duration"])
@pytest.mark.parametrize("bad", [None, True, False, "63", [], {}, -1, float("nan"), float("inf"), 10**400])
def test_bad_timing_does_not_become_seconds_or_discard_track(field: str, bad: object) -> None:
    """Reject malformed seconds independently of otherwise useful metadata."""
    row = {
        "playerid": 7,
        "audiopath": "spotify:track:synthetic",
        "mode": "play",
        "title": "Kept title",
        "time": 63,
        "duration": 180,
        field: bad,
    }
    (metadata,) = parse_audio_events({"audio_event": [row]})
    assert metadata.title == "Kept title"
    assert metadata.source == "Spotify"
    assert metadata.position is None
    assert metadata.position_updated_at is None
    assert metadata.duration == (180 if field == "time" else None)


@pytest.mark.parametrize("position", [0, 0.125, 63, 180])
def test_zero_fractional_and_track_end_seconds_are_preserved(position: float) -> None:
    """A zero is not missing, and conversion must not truncate fractions."""
    (metadata,) = parse_audio_events(
        {
            "audio_event": [
                {
                    "playerid": 7,
                    "mode": "pause",
                    "audiopath": "library:local:track:synthetic",
                    "time": position,
                    "duration": 180,
                }
            ]
        }
    )
    assert metadata.position == position
    assert metadata.duration == 180
    assert metadata.position_updated_at is not None
    assert metadata.position_updated_at.utcoffset().total_seconds() == 0


@pytest.mark.parametrize(("position", "duration"), [(1, 0), (0, 0), (181, 180)])
def test_timeless_or_overrun_track_has_no_usable_position(position: float, duration: float) -> None:
    """An overrun is not silently clamped into an invented valid observation."""
    (metadata,) = parse_audio_events(
        {
            "audio_event": [
                {
                    "playerid": 7,
                    "mode": "play",
                    "audiopath": "spotify:track:synthetic",
                    "time": position,
                    "duration": duration,
                }
            ]
        }
    )
    assert metadata.position is None
    assert metadata.position_updated_at is None
    assert metadata.duration == (duration or None)


@pytest.mark.parametrize(
    "extra",
    [
        {"audiopath": "loxoneradio:stream:synthetic"},
        {"audiopath": "tunein:station:synthetic"},
        {"audiopath": "linein:synthetic#1"},
        {"audiopath": "airplay"},
        {"audiopath": "custom:station:synthetic"},
        {"audiopath": "spotify:track:"},
        {"audiopath": "spotify:playlist:synthetic"},
        {"audiopath": "", "sourceName": "Spotify"},
        {"audiopath": "unknown:synthetic"},
        {"mode": "unknown"},
        {"mode": None},
        {"eventype": 3},
        {"eventype": 100},
        {"eventype": "broken"},
        {"eventype": 3, "mode": "stop"},
        {"audiopath": "airplay", "type": 7},
    ],
)
def test_unsupported_source_mode_or_interruption_has_no_track_timing(extra: dict) -> None:
    """A plausible duration must not invent timing for a live or interrupted source."""
    row = {"playerid": 7, "mode": "play", "audiopath": "spotify:track:synthetic", "time": 63, "duration": 180, **extra}
    (metadata,) = parse_audio_events({"audio_event": [row]})
    assert metadata.position is None
    assert metadata.duration is None
    assert metadata.position_updated_at is None


@pytest.mark.parametrize("mode", ["play", "pause", "stop"])
@pytest.mark.parametrize("path", ["spotify:track:synthetic", "library:local:track:synthetic"])
def test_valid_seconds_ignore_conflicting_millisecond_fields(mode: str, path: str) -> None:
    """Only source-established seconds are interpreted in this first increment."""
    (metadata,) = parse_audio_events(
        {
            "audio_event": [
                {
                    "playerid": 7,
                    "mode": mode,
                    "audiopath": path,
                    "time": 0,
                    "duration": 180,
                    "position_ms": 999999,
                    "progress_ms": 999999,
                    "duration_ms": 1,
                }
            ]
        }
    )
    assert metadata.position == 0
    assert metadata.duration == 180


def test_millisecond_only_payload_does_not_invent_seconds() -> None:
    """Unverified field precedence remains explicitly unsupported."""
    (metadata,) = parse_audio_events(
        {
            "audio_event": [
                {
                    "playerid": 7,
                    "mode": "play",
                    "audiopath": "spotify:track:synthetic",
                    "position_ms": 63000,
                    "duration_ms": 180000,
                }
            ]
        }
    )
    assert metadata.position is None
    assert metadata.duration is None
    assert metadata.position_updated_at is None
