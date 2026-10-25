"""Event semantics using attributed contributor samples and explicit synthetic variants."""

from __future__ import annotations

# Assertions, numeric protocol values and intentional lifecycle inspection are test evidence.
# ruff: noqa: S101, INP001, PLR2004, SLF001

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from pyloxone_audio.native import AudioEventReceiver, parse_audio_events

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from pyloxone_audio.native import AudioZoneMetadata

FIXTURES = Path(__file__).parent / "fixtures" / "audioserver"


def snapshot(receiver: AudioEventReceiver, player_id: int) -> AudioZoneMetadata:
    """Require an observed snapshot before asserting any of its fields."""
    row = receiver.get(player_id)
    assert row is not None
    return row


def test_contributed_tts_capture_is_an_active_target_zone_event() -> None:
    """Decode the contributor's full target entry, not merely its music fields."""
    payload = json.loads((FIXTURES / "sebastian_tts.json").read_text())
    (zone,) = parse_audio_events(payload)
    assert zone.player_id == 15
    assert zone.title == "TTS: test"
    assert zone.source is None
    assert zone.event == "tts"
    assert zone.event_active is True


@pytest.mark.parametrize(
    ("code", "name"),
    [
        (1, "doorbell"),
        (2, "alarm_clock"),
        (3, "tts"),
        (5, "custom_sound"),
        (7, "announcement"),
        (100, "alarm"),
        (101, "fire_alarm"),
        (42, "event_42"),
    ],
)
def test_playing_event_codes_have_stable_automation_names(code: int, name: str) -> None:
    """Mapping is adapted from Sebastian's POC; unknown positive codes stay explicit."""
    (zone,) = parse_audio_events({"audio_event": [{"playerid": 7, "eventype": code, "mode": "play"}]})
    assert zone.event == name
    assert zone.event_active is True


@pytest.mark.parametrize(
    ("mode", "active"), [("stop", False), ("pause", False), (None, None), ("future", None), ([], None)]
)
def test_tts_broadcast_data_requires_target_playback(mode: object, *, active: bool | None) -> None:
    """Synthetic variants of Sebastian's target capture cannot make other zones speak."""
    payload = json.loads((FIXTURES / "sebastian_tts.json").read_text())
    payload["audio_event"][0].update(playerid=18, name="Synthetic non-target", mode=mode)
    (zone,) = parse_audio_events(payload)
    assert zone.event is None
    assert zone.event_active is active
    assert zone.title is None
    assert zone.artist is None
    assert zone.album is None
    assert zone.cover_url is None
    assert zone.audio_path is None
    assert zone.source is None


@pytest.mark.parametrize("code", [True, False, "3", 3.0, -1, {}, []])
def test_malformed_event_codes_are_unknown_not_false_event_ends(code: object) -> None:
    """Bad optional fields must neither alias a valid code nor assert event completion."""
    (zone,) = parse_audio_events({"audio_event": [{"playerid": 7, "eventype": code, "mode": "play"}]})
    assert zone.event is None
    assert zone.event_active is None


@pytest.mark.parametrize("code", [None, 0])
def test_explicit_no_event_is_inactive(code: int | None) -> None:
    """Missing/null/zero codes on a zone snapshot signify no reported event."""
    (zone,) = parse_audio_events({"audio_event": [{"playerid": 7, "eventype": code, "mode": "play"}]})
    assert zone.event is None
    assert zone.event_active is False


def test_event_data_cannot_masquerade_as_music_source() -> None:
    """Event metadata describes the interruption, not an underlying music service."""
    (zone,) = parse_audio_events(
        {"audio_event": [{"playerid": 7, "eventype": 3, "mode": "play", "audiopath": "spotify:synthetic"}]}
    )
    assert zone.source is None


@pytest.mark.parametrize(
    ("filename", "title", "source"),
    [
        ("sebastian_tunein.json", "Creed - Higher 2001", "TuneIn"),
        ("sebastian_loxone_radio.json", "Universal Solution - In Your System", "Loxone Radio"),
    ],
)
def test_contributed_music_captures_remain_non_event_metadata(filename: str, title: str, source: str) -> None:
    """The complete source samples also guard against false `type`-based announcements."""
    (zone,) = parse_audio_events(json.loads((FIXTURES / filename).read_text()))
    assert zone.player_id == 22
    assert zone.title == title
    assert zone.source == source
    assert zone.event is None
    assert zone.event_active is False


class ManualClock:
    """Run the receiver's real timer callbacks without wall-clock sleeps."""

    def __init__(self) -> None:
        """Start at zero elapsed time, independent of the wall-clock timezone."""
        self.now = 0.0
        self.handles: list[asyncio.TimerHandle] = []

    def call_later(self, delay: float, callback: Callable[..., None], *args: Any) -> asyncio.TimerHandle:
        """Create a real handle, but advance it only when the test asks."""
        handle = asyncio.TimerHandle(self.now + delay, callback, args, asyncio.get_running_loop())
        self.handles.append(handle)
        return handle

    def advance_to(self, when: float) -> None:
        """Execute all due uncancelled callbacks in timestamp order."""
        assert when >= self.now
        while self.handles and (handle := min(self.handles, key=lambda item: item.when())).when() <= when:
            self.handles.remove(handle)
            self.now = handle.when()
            if not handle.cancelled():
                handle._run()
        self.now = when


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "name"), [(100, "alarm"), (101, "fire_alarm"), (2, "alarm_clock")])
async def test_recorded_alarm_flaps_have_one_stable_end(monkeypatch: pytest.MonkeyPatch, code: int, name: str) -> None:
    """Reconstruct minimal synthetic rows from the attributed compact timeline."""
    clock = ManualClock()
    monkeypatch.setattr(asyncio.get_running_loop(), "call_later", clock.call_later)
    notifications = []
    receiver = AudioEventReceiver(notifications.append)
    lines = (FIXTURES / "sebastian_alarm_end.txt").read_text().splitlines()
    times = [
        sum(float(part) * scale for part, scale in zip(line.split()[0].split(":"), (3600, 60, 1), strict=True))
        for line in lines
    ]
    offsets = [when - times[0] for when in times]

    async def frames() -> AsyncIterator[str]:
        for offset, line in zip(offsets, lines, strict=True):
            clock.advance_to(offset)
            event_code = None if "eventype=None" in line else code
            # Only the last two modes were recorded; earlier play is synthetic.
            mode = "stop" if "mode=stop" in line else "play"
            yield json.dumps({"audio_event": [{"playerid": 22, "mode": mode, "eventype": event_code}]})
            assert snapshot(receiver, 22).event == name
            assert snapshot(receiver, 22).event_active is True
        # Quiet begins at the first inactive row after the last playing event,
        # which precedes the two explicit stopped rows in this recording.
        last_playing = max(
            index for index, line in enumerate(lines) if "eventype=None" not in line and "mode=stop" not in line
        )
        stable_start = offsets[last_playing + 1]
        clock.advance_to(stable_start + 1.499)
        assert snapshot(receiver, 22).event == name
        clock.advance_to(stable_start + 1.5)
        assert snapshot(receiver, 22).event is None
        assert snapshot(receiver, 22).event_active is False
        events = [row.event for update in notifications for row in update]
        assert events.count(None) == 1

    await receiver.async_listen(frames())


@pytest.mark.asyncio
async def test_disconnect_cancels_pending_end_before_reconnection(monkeypatch: pytest.MonkeyPatch) -> None:
    """A pending end cannot outlive its stream or emit into the next connection."""
    clock = ManualClock()
    monkeypatch.setattr(asyncio.get_running_loop(), "call_later", clock.call_later)
    notifications = []
    receiver = AudioEventReceiver(notifications.append)

    async def disconnected() -> AsyncIterator[str]:
        yield '{"audio_event":[{"playerid":22,"eventype":100,"mode":"play"}]}'
        yield '{"audio_event":[{"playerid":22,"mode":"stop"}]}'
        assert len(clock.handles) == 1
        assert not clock.handles[0].cancelled()

    await receiver.async_listen(disconnected())
    assert receiver.get(22) is None
    assert notifications[-1] == ()
    assert all(handle.cancelled() for handle in clock.handles)

    async def reconnected() -> AsyncIterator[str]:
        yield '{"audio_event":[{"playerid":22,"eventype":3,"mode":"play"}]}'
        count = len(notifications)
        clock.advance_to(10)
        assert len(notifications) == count
        assert snapshot(receiver, 22).event == "tts"

    await receiver.async_listen(reconnected())


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [1, 3, 5, 7, 42])
async def test_non_flapping_events_finish_immediately(monkeypatch: pytest.MonkeyPatch, code: int) -> None:
    """TTS, doorbells and announcements must not inherit alarm-end latency."""
    clock = ManualClock()
    monkeypatch.setattr(asyncio.get_running_loop(), "call_later", clock.call_later)
    receiver = AudioEventReceiver(lambda _rows: None)

    async def frames() -> AsyncIterator[str]:
        yield json.dumps({"audio_event": [{"playerid": 7, "eventype": code, "mode": "play"}]})
        assert snapshot(receiver, 7).event_active is True
        yield '{"audio_event":[{"playerid":7,"mode":"stop"}]}'
        assert snapshot(receiver, 7).event_active is False
        assert snapshot(receiver, 7).event is None
        assert clock.handles == []

    await receiver.async_listen(frames())


@pytest.mark.asyncio
async def test_replacement_event_cancels_only_its_own_pending_end(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replacing one zone's alarm with TTS must not terminate either incorrectly."""
    clock = ManualClock()
    monkeypatch.setattr(asyncio.get_running_loop(), "call_later", clock.call_later)
    receiver = AudioEventReceiver(lambda _rows: None)

    async def frames() -> AsyncIterator[str]:
        yield (
            '{"audio_event":[{"playerid":7,"eventype":100,"mode":"play"},{"playerid":8,"eventype":101,"mode":"play"}]}'
        )
        yield '{"audio_event":[{"playerid":7},{"playerid":8}]}'
        assert len(clock.handles) == 2
        clock.advance_to(0.5)
        yield '{"audio_event":[{"playerid":7,"eventype":3,"mode":"play"}]}'
        clock.advance_to(2)
        assert snapshot(receiver, 7).event == "tts"
        assert snapshot(receiver, 7).event_active is True
        assert snapshot(receiver, 8).event is None
        assert snapshot(receiver, 8).event_active is False

    await receiver.async_listen(frames())


@pytest.mark.asyncio
async def test_end_timer_retains_latest_music_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Debounce only event attributes; no stale track may return at timer expiry."""
    clock = ManualClock()
    monkeypatch.setattr(asyncio.get_running_loop(), "call_later", clock.call_later)
    receiver = AudioEventReceiver(lambda _rows: None)

    async def frames() -> AsyncIterator[str]:
        yield '{"audio_event":[{"playerid":7,"eventype":100,"mode":"play"}]}'
        yield '{"audio_event":[{"playerid":7,"title":"First track","audiopath":"spotify:synthetic"}]}'
        clock.advance_to(0.5)
        yield '{"audio_event":[{"playerid":7,"title":"Latest track","audiopath":"tunein:synthetic"}]}'
        assert snapshot(receiver, 7).title == "Latest track"
        assert snapshot(receiver, 7).event == "alarm"
        clock.advance_to(1.5)
        assert snapshot(receiver, 7).title == "Latest track"
        assert snapshot(receiver, 7).source == "TuneIn"
        assert snapshot(receiver, 7).event_active is False

    await receiver.async_listen(frames())


@pytest.mark.asyncio
async def test_unknown_event_state_invalidates_pending_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    """Corrupt activity information cannot become a delayed false all-clear."""
    clock = ManualClock()
    monkeypatch.setattr(asyncio.get_running_loop(), "call_later", clock.call_later)
    notifications = []
    receiver = AudioEventReceiver(notifications.append)

    async def frames() -> AsyncIterator[str]:
        yield '{"audio_event":[{"playerid":7,"eventype":100,"mode":"play"}]}'
        yield '{"audio_event":[{"playerid":7}]}'
        yield '{"audio_event":[{"playerid":7,"eventype":100,"mode":"future"}]}'
        assert snapshot(receiver, 7).event_active is None
        count = len(notifications)
        clock.advance_to(10)
        assert len(notifications) == count
        assert snapshot(receiver, 7).event_active is None

    await receiver.async_listen(frames())
