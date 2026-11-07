"""R03-01: strict room ACK is opt-in; ordinary/grouped contracts survive."""
import json
import pytest
from pyloxone_audio import native
from test_audioserver_playback import SyntheticAudioSocket, rsa_key as rsa_key


@pytest.mark.parametrize('action', ['play', 'pause'])
@pytest.mark.parametrize('guarded', [False, True])
@pytest.mark.parametrize('kind', ['true', 'false', 'number', 'malformed', 'conflicting', 'identical', 'error'])
async def test_room_ack_is_unambiguous_without_changing_ordinary_callers(monkeypatch, rsa_key, action, guarded, kind):
    key = action + '_result'
    replies = {
        'true': json.dumps({key: True}), 'false': json.dumps({key: False}),
        'number': json.dumps({key: 1}), 'malformed': '{"'+key+'":tru}',
        'conflicting': '{"'+key+'":false,"'+key+'":true}',
        'identical': '{"'+key+'":true,"'+key+'":true}',
        'error': '{"error":"synthetic refusal","error":"","'+key+'":true}',
    }
    class Socket(SyntheticAudioSocket):
        async def send(self, message):
            if message == f'audio/13/{action}':
                self.sent.append(message)
                self.queue.put_nowait(replies[kind])
                return
            await super().send(message)
    socket = Socket(rsa_key)
    monkeypatch.setattr(native, 'connect', lambda *a, **kw: socket)
    commands = native.AudioServerCommands('synthetic.invalid', lambda: ('synthetic-user', 'synthetic-active-token'), timeout=.08)
    success = kind == 'true' or (not guarded and kind in ('conflicting', 'identical', 'error'))
    try:
        if success:
            await commands.async_execute(13, action, guard_cleanup=guarded)
        else:
            with pytest.raises(native.AudioCommandError):
                await commands.async_execute(13, action, guard_cleanup=guarded)
        assert socket.sent.count(f'audio/13/{action}') == 1
        assert socket.closed and commands._socket is None
    finally:
        await commands.async_close()


@pytest.mark.parametrize('key', ['grouped_play_result', 'grouped_pause_result'])
async def test_existing_grouped_parser_rejects_duplicates_without_opt_in(key):
    class Socket:
        async def recv(self):
            return '{"'+key+'":{},"'+key+'":{}}'
    with pytest.raises(native.AudioCommandError, match='duplicate'):
        await native.AudioServerCommands._reply(Socket(), key)
