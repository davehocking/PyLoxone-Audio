"""Real owning source success followed by rejected warm optional seek."""
import pytest
from pyloxone_audio.diagnostic_events import DiagnosticEmitter
from test_audioserver_ha import audio_setup
from test_audioserver_playback import rsa_key
from test_source_return_simplification_ha import simplified_harness, select, sent_commands


@pytest.mark.parametrize('spotify', [False, True], ids=['library', 'spotify'])
async def test_rejected_warm_seek_retains_confirmed_source_without_replay(
    hass, audio_setup, monkeypatch, rsa_key, spotify,
):
    entity, controls, sockets, _emit = await simplified_harness(
        hass, audio_setup, monkeypatch, rsa_key, spotify=spotify,
    )
    commands = entity._audio_commands
    events = []
    emitter = DiagnosticEmitter(b'synthetic-warm-rejection', events.append)
    emitter.enabled = True
    commands.diagnostics = emitter
    controls['seek_reply'] = 'reject'
    try:
        await select(hass, entity, spotify=spotify)
        assert commands.reuse_session
        assert len(sockets) == 1
        assert sum(m.startswith('secure/authenticate/') for s in sockets for m in s.sent) == 1
        writes = sent_commands(sockets)
        assert len(writes) == 2
        assert writes[-1] == 'audio/7/position/45.0'
        assert sum(e['stage'] == 'session_reused' for e in events) == 1
        assert sum(e['stage'] == 'source_confirmed' for e in events) == 1
        assert sum(e['stage'] == 'restore_failed' for e in events) == 1
        assert not any(e['stage'] == 'restore_echo' for e in events)
        assert entity._audio_metadata.get(7).source == ('Spotify' if spotify else 'Local Library')
        assert entity._audio_metadata.get(7).position == 0
        assert not commands.source_fences and not commands.source_observations
        assert not hasattr(entity, '_audio_last_source_failure')
        # A negative reply retires the uncertain warm session before return.
        # No fixture cleanup may manufacture this result.
        assert sockets[0].closed
        assert commands._session is None
        audio_setup.apis[0].send_websocket_command.assert_not_awaited()
    finally:
        await commands.async_close()
