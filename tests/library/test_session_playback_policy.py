"""Playback retention driven by existing mapped native metadata callbacks."""
import pytest
from pyloxone_audio import native, session
from pyloxone_audio.metadata import AudioMetadataCoordinator
from session_support import Clock, Peer, settle


def publish(metadata, player, mode):
    updates = native.parse_audio_events({'audio_event': [{'playerid': player, 'mode': mode, 'eventype': 0, 'audiopath': 'spotify:track:synthetic'}]})
    updates = tuple(metadata._client._receiver._apply(row) for row in updates)
    metadata._on_update(updates)


@pytest.mark.parametrize('end', ['pause', 'stop', 'unknown', 'stale', 'removed', 'disconnect'])
async def test_any_mapped_playing_room_retains_then_starts_idle_allowance(monkeypatch, end):
    clock, peer = Clock(), Peer()
    monkeypatch.setattr(session, 'monotonic', clock.time)
    monkeypatch.setattr(session, 'call_later', clock.call_later)
    monkeypatch.setattr(native, 'connect', peer.connect)
    commands = native.AudioServerCommands('synthetic.invalid', lambda: ('u', 't'))
    commands.reuse_session = True
    metadata = AudioMetadataCoordinator('synthetic.invalid')
    remove = {p: metadata.async_add_reconciler(p, commands, intent=lambda: 0, available=lambda: True) for p in (7, 8)}
    try:
        await commands.async_execute(7, 'pause')
        # Nonplaying updates, other server/unmapped room activity must not be
        # mistaken for this server's positively playing mapped room.
        publish(metadata, 7, 'pause')
        for _ in range(31):
            publish(metadata, 8, 'play')
            publish(metadata, 99, 'play')
            await clock.advance(20)
        assert peer.closes == 0
        if end == 'removed':
            remove[8]()
        elif end == 'disconnect':
            metadata._client._receiver._reset()
        elif end != 'stale':
            publish(metadata, 8, end)
        # A quiet final play sample has a bounded 30s lease; it is not eternal.
        grace = 10 if end == 'stale' else 0
        await clock.advance(299 + grace)
        assert peer.closes == 0
        await clock.advance(1)
        assert peer.closes == 1
        # Required reads remain enabled after active expiry.
        await commands.async_player_status(7, is_current=lambda: True)
        assert peer.opens == 2
    finally:
        await metadata.async_stop()
        await commands.async_close()
        await peer.finish()
