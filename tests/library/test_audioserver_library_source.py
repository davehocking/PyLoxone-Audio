"""Synthetic exact-source regressions; no household paths or credentials."""

# ruff: noqa: S101, INP001
import pytest
from pyloxone_audio.native import parse_audio_events


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("library:local:track:opaque-synthetic-id", "Local Library"),
        ("library:local:track:", ""),
        ("library:local:folder:opaque-synthetic-id", ""),
        ("file:///home/public/Event_Sounds/tts/synthetic.mp3", ""),
        ("https://example.invalid/local/music.mp3", ""),
    ],
)
def test_local_library_requires_exact_nonempty_track_namespace(path: str, expected: str) -> None:
    """Accept a track namespace without mistaking folders or events for music."""
    row = parse_audio_events({"audio_event": [{"playerid": 1, "audiopath": path}]})[0]
    assert row.source == (expected or None)


def test_local_track_in_event_never_becomes_music_source() -> None:
    """An interruption cannot inherit the pre-event music source."""
    row = parse_audio_events(
        {"audio_event": [{"playerid": 1, "audiopath": "library:local:track:synthetic", "eventype": 3, "mode": "play"}]}
    )[0]
    assert row.source is None
