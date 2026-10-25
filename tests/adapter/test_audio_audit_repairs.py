"""Audit regressions. Synthetic inputs only; never household control or media."""

from __future__ import annotations

# Assertion/numeric protocol/private helper use is intentional test evidence.
# ruff: noqa: S101, INP001, PLR2004, SLF001

import asyncio

import pytest

from custom_components.loxone.pyloxone_api.audioserver import AudioServerCommands, parse_audio_events


@pytest.mark.asyncio
async def test_ack_survives_more_than_64_unrelated_frames() -> None:
    """A frame count must not reject a positive reply inside the elapsed deadline."""
    queue = asyncio.Queue()
    for _ in range(128):
        queue.put_nowait('{"audio_event":[{"playerid":9,"mode":"play"}]}')
    queue.put_nowait(b"synthetic binary frame")
    queue.put_nowait("not JSON")
    queue.put_nowait('{"play_result":true}')

    class Socket:
        async def recv(self) -> str | bytes:
            return await queue.get()

    async with asyncio.timeout(1):
        assert await AudioServerCommands._reply(Socket(), "play_result") is True


@pytest.mark.asyncio
async def test_continuous_buffered_noise_still_obeys_elapsed_deadline() -> None:
    """An immediately ready receive must not starve timeout cancellation."""

    class Socket:
        async def recv(self) -> str:
            return '{"unrelated":true}'

    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.01):
            await AudioServerCommands._reply(Socket(), "play_result")


@pytest.mark.parametrize(("mode", "active"), [("play", True), ("pause", False), ("stop", False), (None, None)])
def test_reported_airplay_announcement_type_is_zone_qualified(mode: str | None, *, active: bool | None) -> None:
    """Synthetic reconstruction of #523's measured AirPlay type7 contract."""
    (zone,) = parse_audio_events(
        {
            "audio_event": [
                {
                    "playerid": 7,
                    "type": 7,
                    "audiopath": "airplay",
                    "mode": mode,
                    "title": "Synthetic interruption",
                    "artist": "Old artist",
                    "album": "Old album",
                }
            ]
        }
    )
    assert zone.event_active is active
    assert zone.event == ("announcement" if active else None)
    assert zone.source is None
    assert zone.title == ("Synthetic interruption" if active else None)


@pytest.mark.parametrize(
    "row",
    [
        {"type": 7, "audiopath": "spotify:synthetic"},
        {"type": 7, "audiopath": "airplay-other"},
        {"type": 7, "audiopath": ""},
        {"type": "7", "audiopath": "airplay"},
        {"type": 7.0, "audiopath": "airplay"},
        {"type": True, "audiopath": "airplay"},
        {"type": 4, "audiopath": "airplay"},
    ],
)
def test_type_is_not_a_generic_event_code(row: dict) -> None:
    """Normal music type values must never alias eventype values."""
    (zone,) = parse_audio_events({"audio_event": [{"playerid": 7, "mode": "play", **row}]})
    assert zone.event is None
    assert zone.event_active is False


@pytest.mark.parametrize("code", [3, "3", True, -1])
def test_native_eventype_takes_precedence_over_airplay_type(code: object) -> None:
    """Do not overwrite native or malformed event evidence with the fallback."""
    (zone,) = parse_audio_events(
        {
            "audio_event": [
                {
                    "playerid": 7,
                    "mode": "play",
                    "type": 7,
                    "audiopath": "airplay",
                    "eventype": code,
                }
            ]
        }
    )
    assert zone.event == ("tts" if type(code) is int and code == 3 else None)
    assert zone.event_active is (True if type(code) is int and code == 3 else None)
