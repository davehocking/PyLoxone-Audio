"""Full native HA Browse traversal with invented local-library identities."""
import json
from urllib.parse import quote, unquote

import pytest
from custom_components.loxone.pyloxone_api import audioserver as wire
from test_reusable_session_ha import reusable_peer as reusable_peer
from test_room_transport_fences_ha import room_peer as room_peer
from test_audio_grouping_ha import grouped_setup as grouped_setup
from test_audio_grouping_ha import audio_setup as audio_setup
from test_audioserver_playback import rsa_key as rsa_key


@pytest.mark.parametrize('reuse', [False, True])
async def test_native_ha_library_traverses_decoded_nested_pages(hass, reusable_peer, monkeypatch, reuse):
    p = reusable_peer
    p.co.audio_commands.reuse_session = reuse
    await p.g.feed(p.entry)
    original_connect = wire.connect
    folder_calls = []
    root = 'library:local:folder:invented root'
    album = 'library:local:folder:invented album+café'
    track = 'library:local:track:invented-song'
    pages = {
        ('0', 0): [{'id': root, 'name': 'Invented collection', 'type': 1}],
        (root, 0): [{'id': album, 'name': 'Invented album', 'type': 1}],
        (album, 0): [{'id': track, 'name': 'Invented song', 'type': 2}],
    }
    def connect(*args, **kwargs):
        socket = original_connect(*args, **kwargs)
        original_send = socket.send
        async def send(message):
            if message.startswith('audio/cfg/getmediafolder/'):
                socket.sent.append(message)
                p.wires.append(message)
                parts = message.split('/')
                folder, offset = unquote(parts[3]), int(parts[4])
                folder_calls.append((folder, offset))
                items = pages[(folder, offset)]
                socket.queue.put_nowait(json.dumps({'command': unquote(message), 'getmediafolder_result': [
                    {'start': offset, 'totalitems': len(items), 'items': items}
                ]}))
            else:
                await original_send(message)
        socket.send = send
        return socket
    monkeypatch.setattr(wire, 'connect', connect)
    entity = p.g.entities[p.ids[1]]
    browse = await entity.async_browse_media()
    current = next(c for c in browse.children if c.title == 'Local Library')
    for title in ('Invented collection', 'Invented album', 'Invented song'):
        result = await entity.async_browse_media(current.media_content_type, current.media_content_id)
        assert [c.title for c in result.children] == [title]
        current = result.children[0]
    assert current.can_play and not current.can_expand
    # Root discovery also refreshes configured source inventory once.
    assert folder_calls == [('0', 0), ('0', 0), (root, 0), (album, 0)]
    assert [m for m in p.wires if '/getmediafolder/' in m] == [
        'audio/cfg/getmediafolder/' + quote(f, safe='') + '/0/50' for f in ('0', '0', root, album)
    ]
    assert sum(m.startswith('secure/authenticate/') for s in p.sockets for m in s.sent) == (1 if reuse else len(p.sockets))
    assert len(p.sockets) == 1 if reuse else len(p.sockets) >= 3
    assert not any('/play' in m or '/library/' in m for m in p.wires)
    p.co.api.send_websocket_command.assert_not_awaited()
