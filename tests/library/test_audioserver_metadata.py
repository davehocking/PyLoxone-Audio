"""
Synthetic event fixtures derived from the field contract in issue #523.

These fixtures are invented for offline validation, NOT device captures.
"""
# Pytest assertions and fixture IDs are intentional; upstream tests are a namespace.
# ruff: noqa: S101, PLR2004, INP001

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

from pyloxone_audio.native import AudioEventReceiver, parse_audio_events

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def test_metadata_uses_player_id_instead_of_room_name() -> None:
    """Same display names must not merge different physical player IDs."""
    payload = {
        "audio_event": [
            {
                "playerid": 15,
                "name": "Same room",
                "title": "Track A",
                "artist": "Artist A",
                "album": "Album A",
                "coverurl": "https://example.invalid/a.jpg",
                "audiopath": "spotify:track:synthetic",
            },
            {"playerid": 16, "name": "Same room", "title": "Track B"},
        ]
    }
    result = parse_audio_events(payload)
    assert [item.player_id for item in result] == [15, 16]
    assert result[0].title == "Track A"
    assert result[0].artist == "Artist A"
    assert result[0].album == "Album A"
    assert result[0].cover_url == "https://example.invalid/a.jpg"
    assert result[0].audio_path == "spotify:track:synthetic"
    assert result[1].title == "Track B"


@pytest.mark.parametrize(
    ("path", "source_name", "expected"),
    [
        ("spotify:track:synthetic", "", "Spotify"),
        ("tunein:station:synthetic", "", "TuneIn"),
        ("loxoneradio:stream:synthetic", "", "Loxone Radio"),
        ("linein:synthetic#1", "", "Line-In"),
        ("airplay", "", "AirPlay"),
        ("", "Spotify", "Spotify"),
        ("unknown:track:synthetic", "Spotify", None),
        ("", "", None),
    ],
)
def test_source_uses_audio_path_not_ambiguous_audio_type(path: str, source_name: str, expected: str | None) -> None:
    """Only explicit observed path shapes, or the Spotify transition, identify source."""
    result = parse_audio_events(
        {
            "audio_event": [
                {"playerid": 15, "audiopath": path, "audiotype": 0, "sourceName": source_name},
            ]
        }
    )
    assert result[0].source == expected


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "greeting",
        {},
        {"getkey_result": [{}]},
        {"audio_event": None},
        {"audio_event": {}},
        {"audio_event": "invalid"},
    ],
)
def test_non_event_payloads_are_ignored(payload: object) -> None:
    """Greetings, command replies and malformed envelopes contain no zone update."""
    assert parse_audio_events(payload) == ()


def test_malformed_rows_do_not_hide_other_zones() -> None:
    """Reject invalid IDs and metadata types without discarding valid siblings."""
    rows = [
        None,
        "bad",
        {},
        {"playerid": True},
        {"playerid": 0},
        {"playerid": -1},
        {"playerid": 1.5},
        {"playerid": "nope"},
        {
            "playerid": "16",
            "title": 42,
            "artist": {},
            "album": "",
            "coverurl": False,
            "audiopath": [],
            "sourceName": [],
        },
    ]
    result = parse_audio_events({"audio_event": rows})
    assert len(result) == 1
    assert result[0].player_id == 16
    assert result[0].title is None
    assert result[0].artist is None
    assert result[0].album is None
    assert result[0].cover_url is None
    assert result[0].audio_path is None
    assert result[0].source is None


@pytest.mark.asyncio
async def test_receiver_replays_events_without_sending_commands() -> None:
    """One stream consumer ignores protocol replies and clears stale data at EOF."""
    notifications = []
    receiver = AudioEventReceiver(notifications.append)
    assert receiver.get(15) is None

    async def frames() -> AsyncIterator[str | bytes]:
        yield "LWSS synthetic greeting"
        yield '{"getkey_result": []}'
        yield b"not a text frame"
        yield json.dumps(
            {
                "audio_event": [
                    {"playerid": 15, "title": "Track A", "audiopath": "spotify:track:synthetic"},
                    {"playerid": 16, "title": "Track B"},
                ]
            }
        )
        zone = receiver.get(15)
        assert zone is not None
        assert zone.title == "Track A"
        zone = receiver.get(16)
        assert zone is not None
        assert zone.title == "Track B"
        yield '{"audio_event": [{"playerid": 15}]}'
        zone = receiver.get(15)
        assert zone is not None
        assert zone.title is None
        zone = receiver.get(16)
        assert zone is not None
        assert zone.title == "Track B"

    await receiver.async_listen(frames())
    assert receiver.get(15) is None
    assert receiver.get(16) is None
    assert [tuple(row.player_id for row in rows) for rows in notifications] == [(), (15, 16), (15,), ()]


@pytest.mark.asyncio
async def test_receiver_rejects_concurrent_stream_without_resetting_owner() -> None:
    """A second reader must not steal or invalidate the current stream's state."""
    receiver = AudioEventReceiver(lambda _updates: None)

    async def empty() -> AsyncIterator[str]:
        for frame in ():
            yield frame

    async def frames() -> AsyncIterator[str]:
        yield '{"audio_event": [{"playerid": 15, "title": "Owner track"}]}'
        with pytest.raises(RuntimeError, match="already listening"):
            await receiver.async_listen(empty())
        zone = receiver.get(15)
        assert zone is not None
        assert zone.title == "Owner track"

    await receiver.async_listen(frames())


@pytest.mark.asyncio
async def test_cancellation_clears_metadata_and_allows_a_new_stream() -> None:
    """Validate the same unwind path on cancellation, not only normal EOF."""
    ready = asyncio.Event()
    notifications = []
    receiver = AudioEventReceiver(notifications.append)

    async def frames() -> AsyncIterator[str]:
        yield '{"audio_event": [{"playerid": 15, "title": "Old track"}]}'
        ready.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(receiver.async_listen(frames()))
    try:
        await asyncio.wait_for(ready.wait(), timeout=1)
        zone = receiver.get(15)
        assert zone is not None
        assert zone.title == "Old track"
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert receiver.get(15) is None
    assert notifications[-1] == ()

    async def reconnected() -> AsyncIterator[str]:
        assert receiver.get(15) is None
        yield '{"audio_event": [{"playerid": 16, "title": "New track"}]}'
        assert receiver.get(15) is None
        zone = receiver.get(16)
        assert zone is not None
        assert zone.title == "New track"

    await receiver.async_listen(reconnected())
    assert receiver.get(16) is None
