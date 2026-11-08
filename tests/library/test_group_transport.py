"""Synthetic grouped-reply rejection at actual command parser boundary."""
import json
from unittest.mock import AsyncMock
import pytest
from pyloxone_audio import native


@pytest.mark.parametrize('reply', [
    True, False, None, {}, {'players': []}, {'players': False},
    {'players': [{'playerid':1,'mode':'play'}]},
    {'players': [{'playerid':1,'mode':'play'},{'playerid':1,'mode':'play'}]},
    {'players': [{'playerid':1,'mode':'play'},{'playerid':3,'mode':'play'}]},
    {'players': [{'playerid':1,'mode':'play'},{'playerid':2,'mode':'pause'}]},
    {'players': [{'playerid':1,'mode':'play'},{'playerid':True,'mode':'play'}]},
    {'players': [{'playerid':1,'mode':'play'},{'playerid':2.0,'mode':'play'}]},
    {'players': [{'playerid':1,'mode':'play'},{'playerid':10**400,'mode':'play'}]},
    {'players': [{'playerid':1,'mode':'play'},{'playerid':2,'mode':'play','extra':False}]},
    {'players': [{'playerid':1,'mode':'play'},{'playerid':2,'mode':'play'}], 'extra':0},
])
async def test_group_transport_rejects_incomplete_negative_or_ambiguous_exact_reply(monkeypatch, reply):
    client = native.AudioServerCommands('synthetic.invalid', lambda: ('synthetic','synthetic'))
    request = AsyncMock(return_value=reply)
    monkeypatch.setattr(client, '_async_request', request)
    with pytest.raises(native.AudioCommandError):
        await client.async_group_transport((1,2), 'play', is_current=lambda: True)
    assert request.await_count == 1


@pytest.mark.parametrize('members', [(), (1,), (1,1), (True,2), (0,2), (-1,2), ('1',2), (1.0,2), (10**400,2), tuple(range(1,258)), [1,2], None])
async def test_invalid_group_transport_input_never_sends(monkeypatch, members):
    client = native.AudioServerCommands('synthetic.invalid', lambda: ('synthetic','synthetic'))
    request = AsyncMock()
    monkeypatch.setattr(client, '_async_request', request)
    with pytest.raises(ValueError):
        await client.async_group_transport(members, 'play', is_current=lambda: True)
    request.assert_not_awaited()


async def test_duplicate_group_reply_json_keys_cannot_be_last_wins_success(monkeypatch):
    class Socket:
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def send(self, command): pass
        async def recv(self):
            return '{"grouped_play_result":{"players":[{"playerid":1,"mode":"pause","mode":"play"},{"playerid":2,"mode":"play"}]}}'
    client = native.AudioServerCommands('synthetic.invalid', lambda: ('synthetic','synthetic'))
    monkeypatch.setattr(native, 'connect', lambda *a,**k: Socket())
    monkeypatch.setattr(client, '_authenticate', AsyncMock())
    with pytest.raises(native.AudioCommandError):
        await client.async_group_transport((1,2), 'play', is_current=lambda: True)
