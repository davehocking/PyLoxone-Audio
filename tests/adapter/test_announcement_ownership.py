"""Synthetic announcement ownership regression tests, with no household IO."""

# ruff: noqa: S101, INP001, ANN001, ANN002, ANN202, ANN204, D101, D102, D103, D107, ARG001, ARG002, ARG005, PLR2004, TRY003, EM101, SLF001, PLC0415, PT018
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.loxone import audio_announcement as module
from custom_components.loxone.pyloxone_api.audioserver import AudioCommandError, parse_audio_events


class Metadata:
    def __init__(self):
        self.row = parse_audio_events({"audio_event": [{"playerid": 7, "eventype": 0, "mode": "stop"}]})[0]
        self.listeners = set()

    def get(self, player):
        assert player == 7
        return self.row

    def async_add_listener(self, player, callback):
        self.listeners.add(callback)
        return lambda: self.listeners.discard(callback)

    def update(self, row):
        self.row = None if row is None else parse_audio_events({"audio_event": [row]})[0]
        for callback in tuple(self.listeners):
            callback()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_initial", [True, False])
async def test_missing_snapshot_or_upload_disconnect_prevents_dispatch(hass, monkeypatch, missing_initial):
    metadata = Metadata()
    if missing_initial:
        metadata.row = None

    async def upload(*args):
        metadata.update(None)

    commands = SimpleNamespace(async_upload_announcement=AsyncMock(side_effect=upload), async_announce=AsyncMock())
    with pytest.raises(AudioCommandError):
        await asyncio.wait_for(module.async_send_announcement(hass, commands, metadata, 7, b"wav", 0.01, 10), 0.2)
    commands.async_announce.assert_not_awaited()
    assert not metadata.listeners


@pytest.mark.asyncio
async def test_conflicting_event_during_authentication_prevents_send(hass):
    metadata = Metadata()
    writes = []

    async def announce(player, filename, volume, *, is_current=None, on_send=None):
        # Authentication/lock wait yields to the passive listener.
        metadata.update({"playerid": 7, "eventype": 5, "mode": "play", "audiopath": "file:///foreign.wav"})
        if is_current is not None and not is_current():
            raise AudioCommandError("stale")
        if on_send is not None:
            on_send()
        writes.append(filename)
        raise AudioCommandError("synthetic ACK loss")

    commands = SimpleNamespace(async_upload_announcement=AsyncMock(), async_announce=announce)
    with pytest.raises(AudioCommandError):
        await module.async_send_announcement(hass, commands, metadata, 7, b"wav", 0.01, 10)
    assert writes == []
    assert not metadata.listeners


@pytest.mark.asyncio
async def test_ack_loss_holds_player_fence_until_observed_owned_start_and_end(hass):
    metadata = Metadata()
    filenames = []

    async def announce(player, filename, volume, *, is_current=None, on_send=None):
        if on_send is not None:
            on_send()
        filenames.append(filename)
        raise AudioCommandError("synthetic ACK loss")

    commands = SimpleNamespace(async_upload_announcement=AsyncMock(), async_announce=announce)
    with pytest.raises(AudioCommandError):
        await module.async_send_announcement(hass, commands, metadata, 7, b"wav", 0.01, 10)
    # Normal idle after an uncertain send does not prove that a late start is impossible.
    metadata.update({"playerid": 7, "eventype": 0, "mode": "stop"})
    with pytest.raises(AudioCommandError):
        await module.async_send_announcement(hass, commands, metadata, 7, b"wav", 0.01, 10)
    assert len(filenames) == 1
    assert commands.async_upload_announcement.await_count == 1
    metadata.update({"playerid": 7, "eventype": 5, "mode": "play", "audiopath": "file:///tmp/" + filenames[0]})
    metadata.update({"playerid": 7, "eventype": 0, "mode": "stop"})
    assert not metadata.listeners
    with pytest.raises(AudioCommandError):
        await module.async_send_announcement(hass, commands, metadata, 7, b"wav", 0.01, 10)
    assert len(filenames) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "terminal",
    [
        {"playerid": 7},
        {"playerid": 7, "eventype": 0, "type": 7, "audiopath": "airplay", "mode": "stop"},
        {"playerid": 7, "mode": "stop"},
        {"playerid": 7, "mode": "stop", "audiopath": "spotify:"},
        {"playerid": 7, "mode": "stop", "audiopath": "unknown:synthetic"},
        {"playerid": 7, "mode": "unknown", "audiopath": "spotify:track:synthetic"},
        {"playerid": 7, "eventype": False, "mode": "stop", "audiopath": "spotify:track:synthetic"},
        {"playerid": 7, "eventype": "0", "mode": "stop", "audiopath": "spotify:track:synthetic"},
    ],
)
async def test_incomplete_end_does_not_complete_owned_announcement(hass, terminal):
    metadata = Metadata()
    started = asyncio.Event()

    async def announce(player, filename, volume, *, is_current=None, on_send=None):
        on_send()
        metadata.update({"playerid": 7, "eventype": 5, "mode": "play", "audiopath": "file:///tmp/" + filename})
        metadata.update(terminal)
        started.set()

    commands = SimpleNamespace(async_upload_announcement=AsyncMock(), async_announce=announce)
    task = asyncio.create_task(module.async_send_announcement(hass, commands, metadata, 7, b"wav", 0.01, 10))
    await started.wait()
    for _ in range(5):
        await asyncio.sleep(0)
    assert not task.done(), "Incomplete row falsely completed the announcement"
    metadata.update({"playerid": 7, "eventype": 0, "mode": "stop"})
    await asyncio.wait_for(task, 0.2)
    assert not metadata.listeners


@pytest.mark.asyncio
async def test_malformed_event_url_resolves_with_controlled_error(hass):
    metadata = Metadata()

    async def announce(player, filename, volume, *, is_current=None, on_send=None):
        on_send()
        metadata.update({"playerid": 7, "eventype": 5, "mode": "play", "audiopath": "file://["})

    commands = SimpleNamespace(async_upload_announcement=AsyncMock(), async_announce=announce)
    with pytest.raises(AudioCommandError):
        await asyncio.wait_for(module.async_send_announcement(hass, commands, metadata, 7, b"wav", 0.01, 10), 0.2)
    for release in tuple(commands.announcement_fences.values()):
        release()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["queued", "authentication"])
async def test_real_announcement_transport_rechecks_guard_before_single_write(monkeypatch, phase):
    from custom_components.loxone.pyloxone_api import audioserver as wire

    socket = AsyncMock()
    context = AsyncMock()
    context.__aenter__.return_value = socket
    monkeypatch.setattr(wire, "connect", lambda *args, **kwargs: context)
    valid = True

    async def authenticate(*args):
        nonlocal valid
        if phase == "authentication":
            valid = False

    monkeypatch.setattr(wire.AudioServerCommands, "_authenticate", authenticate)
    owner = wire.AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "synthetic"))
    marked = []
    if phase == "queued":
        await owner._lock.acquire()
    task = asyncio.create_task(
        owner.async_announce(
            7, "pyloxone-0123456789abcdef.wav", 10, is_current=lambda: valid, on_send=lambda: marked.append(True)
        )
    )
    if phase == "queued":
        await asyncio.sleep(0)
        valid = False
        owner._lock.release()
    with pytest.raises(AudioCommandError):
        await task
    assert not marked
    socket.send.assert_not_awaited()
    assert owner._socket is None


@pytest.mark.asyncio
async def test_cancellation_after_dispatch_retains_fence_and_late_event_releases_it(hass):
    metadata = Metadata()
    dispatched = asyncio.Event()
    filenames = []

    async def announce(player, filename, volume, *, is_current, on_send):
        assert is_current()
        on_send()
        filenames.append(filename)
        dispatched.set()
        await asyncio.Future()

    commands = SimpleNamespace(async_upload_announcement=AsyncMock(), async_announce=announce)
    task = asyncio.create_task(module.async_send_announcement(hass, commands, metadata, 7, b"wav", 0.01, 10))
    await dispatched.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(AudioCommandError):
        await module.async_send_announcement(hass, commands, metadata, 7, b"wav", 0.01, 10)
    assert len(filenames) == 1 and metadata.listeners
    metadata.update({"playerid": 7, "eventype": 5, "mode": "play", "audiopath": "file:///tmp/" + filenames[0]})
    metadata.update({"playerid": 7, "eventype": 0, "mode": "stop"})
    assert not metadata.listeners and not commands.announcement_fences


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["play", "pause", "stop"])
@pytest.mark.parametrize("event_field", [{}, {"eventype": None}])
async def test_known_source_frames_without_event_code_can_bound_announcement(hass, mode, event_field):
    # Synthetic reconstruction of the measured normal-frame shape; no real IDs.
    metadata = Metadata()
    normal = {"playerid": 7, "mode": mode, "audiopath": "spotify:track:synthetic", **event_field}
    metadata.update(normal)
    sent = []

    async def announce(player, filename, volume, *, is_current, on_send):
        assert is_current()
        on_send()
        sent.append(filename)
        metadata.update({"playerid": 7, "eventype": 5, "mode": "play", "audiopath": "file:///tmp/" + filename})
        metadata.update(normal)

    commands = SimpleNamespace(async_upload_announcement=AsyncMock(), async_announce=announce)
    await asyncio.wait_for(module.async_send_announcement(hass, commands, metadata, 7, b"wav", 0.01, 10), 0.2)
    assert len(sent) == 1
    assert not metadata.listeners and not commands.announcement_fences


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "broken",
    [
        None,
        {"playerid": 7, "eventype": 5, "mode": "play", "audiopath": "file://["},
        {"playerid": 7, "eventype": 5, "mode": "play", "audiopath": "file:///foreign.wav"},
    ],
)
async def test_broken_owned_sequence_cannot_release_fence_from_unrelated_idle(hass, broken):
    metadata = Metadata()
    filenames = []

    async def announce(player, filename, volume, *, is_current, on_send):
        assert is_current()
        on_send()
        filenames.append(filename)
        metadata.update({"playerid": 7, "eventype": 5, "mode": "play", "audiopath": "file:///tmp/" + filename})
        metadata.update(broken)

    commands = SimpleNamespace(async_upload_announcement=AsyncMock(), async_announce=announce)
    with pytest.raises(AudioCommandError):
        await module.async_send_announcement(hass, commands, metadata, 7, b"wav", 0.01, 10)
    metadata.update({"playerid": 7, "eventype": 0, "mode": "stop"})
    assert 7 in commands.announcement_fences, "Lost ownership was treated as observed completion"
    with pytest.raises(AudioCommandError):
        await module.async_send_announcement(hass, commands, metadata, 7, b"wav", 0.01, 10)
    assert len(filenames) == 1
    metadata.update({"playerid": 7, "eventype": 5, "mode": "play", "audiopath": "file:///tmp/" + filenames[0]})
    metadata.update({"playerid": 7, "eventype": 0, "mode": "stop"})
    assert not commands.announcement_fences and not metadata.listeners
