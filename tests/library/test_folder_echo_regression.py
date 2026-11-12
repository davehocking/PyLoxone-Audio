"""Regression from observed native folder echoes, with invented catalogue IDs."""
from urllib.parse import unquote
import pytest
from pyloxone_audio import native
from session_support import Peer


@pytest.mark.parametrize('reuse', [False, True])
async def test_library_folder_decoded_echo_through_authenticated_native_owner(monkeypatch, reuse):
    peer = Peer()
    page = [{'start': 0, 'totalitems': 1, 'items': [{'type': 1, 'name': 'Synthetic album', 'id': 'library:local:folder:synthetic-album'}]}]
    peer.response = lambda command: {'command': unquote(command), 'getmediafolder_result': page}
    monkeypatch.setattr(native, 'connect', peer.connect)
    commands = native.AudioServerCommands('synthetic.invalid', lambda: ('synthetic-user', 'synthetic-token'), timeout=.3)
    commands.reuse_session = reuse
    try:
        assert await commands.async_media_folder('library', 'nouser', '0') == page
        assert await commands.async_media_folder('library', 'nouser', 'library:local:folder:synthetic-root') == page
        assert peer.sends == ['audio/cfg/getmediafolder/0/0/50', 'audio/cfg/getmediafolder/library%3Alocal%3Afolder%3Asynthetic-root/0/50']
        assert peer.opens == peer.auths == (1 if reuse else 2)
        if reuse:
            assert peer.closes == 0
    finally:
        await commands.async_close()
        await peer.finish()
    assert peer.closes == peer.opens


@pytest.mark.parametrize('service,account', [('library', 'nouser'), ('spotify', 'synthetic-account')])
@pytest.mark.parametrize('folder', ['synthetic:folder', 'synthetic folder/child', 'literal%3A', 'synthetic+café'])
async def test_catalogue_read_accepts_one_decoding_and_preserves_warm_pagination(monkeypatch, service, account, folder):
    peer = Peer()
    key = 'getmediafolder_result' if service == 'library' else 'getservicefolder_result'
    peer.response = lambda command: {'command': unquote(command), key: [{'items': [], 'totalitems': 0, 'start': int(command.split('/')[-2])}]}
    monkeypatch.setattr(native, 'connect', peer.connect)
    commands = native.AudioServerCommands('synthetic.invalid', lambda: ('u', 't'), timeout=.3)
    commands.reuse_session = True
    try:
        for offset in (0, 50):
            result = await commands.async_media_folder(service, account, folder, offset)
            assert result[0]['start'] == offset
        assert peer.opens == peer.auths == 1
        assert len(peer.sends) == 2 and peer.closes == 0
    finally:
        await commands.async_close()
        await peer.finish()


@pytest.mark.parametrize('foreign', ['folder', 'offset', 'limit', 'account', 'route', 'second-decoding'])
async def test_decoded_catalogue_reply_does_not_accept_foreign_identity(monkeypatch, foreign):
    peer = Peer()
    folder = 'literal%3A' if foreign == 'second-decoding' else 'synthetic:folder'
    correct = [{'items': [], 'marker': 'correct'}]
    wrong = [{'items': [], 'marker': 'foreign'}]
    async def inject(socket, command):
        echo = unquote(command)
        if foreign == 'folder': echo = echo.replace('synthetic:folder', 'another:folder')
        elif foreign == 'offset': echo = echo.rsplit('/', 2)[0] + '/50/50'
        elif foreign == 'limit': echo = echo[:-2] + '49'
        elif foreign == 'account': echo = echo.replace('/synthetic-account/', '/other-account/')
        elif foreign == 'route': echo = echo.replace('/getservicefolder/', '/getmediafolder/')
        else: echo = unquote(echo)
        assert echo != unquote(command) and echo != command
        socket.put({'command': echo, 'getservicefolder_result': wrong})
    peer.on_send = inject
    peer.response = lambda command: {'command': unquote(command), 'getservicefolder_result': correct}
    monkeypatch.setattr(native, 'connect', peer.connect)
    commands = native.AudioServerCommands('synthetic.invalid', lambda: ('u', 't'), timeout=.3)
    commands.reuse_session = True
    try:
        assert await commands.async_media_folder('spotify', 'synthetic-account', folder) == correct
        assert len(peer.sends) == 1
        assert peer.closes == 1, 'Foreign result taints this session; it must not remain warm'
    finally:
        await commands.async_close()
        await peer.finish()


async def test_percent_decoding_is_not_extended_to_playback_write_echoes(monkeypatch):
    peer = Peer()
    peer.response = lambda command: {'command': unquote(command), 'library_result': True}
    monkeypatch.setattr(native, 'connect', peer.connect)
    commands = native.AudioServerCommands('synthetic.invalid', lambda: ('u', 't'), timeout=.2)
    commands.reuse_session = True
    try:
        with pytest.raises(native.AudioCommandError):
            await commands._async_request('audio/7/library/library%3Alocal%3Afile%3Asynthetic', 'library_result')
        assert peer.sends == ['audio/7/library/library%3Alocal%3Afile%3Asynthetic']
    finally:
        await commands.async_close()
        await peer.finish()
