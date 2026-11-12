"""Paired source/wheel benchmark; actual native RSA/AES/strict status parser."""
import json
from pathlib import Path
from time import perf_counter
import pytest
from pyloxone_audio import native
from pyloxone_audio.diagnostic_events import DiagnosticEmitter
from session_support import Peer


@pytest.mark.parametrize('delays', [(0.02, 0.06, 0.03, 0.005), (0.02, 0.10, 0.15, 0.005)])
async def test_cold_and_warm_native_latency(monkeypatch, delays):
    peer = Peer(open_delay=delays[0], auth_delay=delays[1], close_delay=delays[2], reply_delay=delays[3])
    monkeypatch.setattr(native, 'connect', peer.connect)
    events = []
    observer = DiagnosticEmitter(b'synthetic', events.append)
    observer.enabled = True
    owner = native.AudioServerCommands('synthetic.invalid', lambda: ('u', 't'), diagnostics=observer)
    owner.reuse_session = True
    original_response = peer.response
    def response(command):
        action = command.split('/')[2]
        if action == 'status':
            result = {'status_result': [{'playerid': 7, 'mode': 'pause', 'eventype': 0, 'audiopath': 'spotify:track:synthetic'}]}
        elif action == 'getinputs':
            result = {'getinputs_result': []}
        else:
            result = {action + '_result': True}
        return {'command': command, **result}
    peer.response = response
    durations = []
    results = []
    try:
        for operation in ('status', 'pause', 'inputs', 'status'):
            start = perf_counter()
            if operation == 'status':
                result = await owner.async_player_status(7, is_current=lambda: True)
                results.append({'player': result.player_id, 'mode': result.native_mode})
            elif operation == 'pause':
                await owner.async_execute(7, 'pause')
                results.append(True)
            else:
                results.append(await owner.async_source_inputs())
            durations.append((perf_counter() - start) * 1000)
        assert peer.sends == ['audio/7/status', 'audio/7/pause', 'audio/cfg/getinputs', 'audio/7/status']
        assert results == [{'player': 7, 'mode': 'pause'}, True, [], {'player': 7, 'mode': 'pause'}]
        assert len([e for e in events if e['stage'] == 'request_finished' and e['outcome'] == 'returned']) == 4
        result = {'delays_s': delays, 'durations_ms': durations, 'wires': peer.sends, 'results': results,
                  'handshakes': peer.auths, 'closed_before_unload': peer.closes, 'events': events}
        Path('native-benchmark-' + str(delays[2]) + '.json').write_text(json.dumps(result, indent=2))
    finally:
        peer.response = original_response
        await owner.async_close()
        await peer.finish()
