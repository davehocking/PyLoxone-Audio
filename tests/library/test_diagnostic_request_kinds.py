"""Native preparation/control phases stay identifiable without raw parameters."""
from unittest.mock import AsyncMock
import json
import pytest
from pyloxone_audio import native
from pyloxone_audio.diagnostic_events import DiagnosticEmitter


@pytest.mark.parametrize('command,kind,operation',[
 ('audio/cfg/getservices','browse','getservices'),
 ('audio/cfg/getradios','browse','getradios'),
 ('audio/cfg/getroomfavs/7/0/32','browse','getroomfavs'),
 ('audio/cfg/getinputs','browse','getinputs'),
 ('audio/cfg/getmediafolder/SECRET-folder/0/50','browse','getmediafolder'),
 ('audio/cfg/getservicefolder/tunein/SECRET-account/SECRET-folder/0/50','browse','getservicefolder'),
 ('audio/cfg/globalsearch/SECRET-query','search','globalsearch'),
 ('audio/cfg/dgroup/update/0','group_change','dgroup'),
 ('audio/grouped/play/7,8','group_transport','play'),
 ('audio/grouped/playuploadedfile/SECRET-file/7#20','announcement','playuploadedfile'),
 ('audio/7/status','status','status'),
])
async def test_all_shared_native_work_is_classified_without_disclosing_parameters(monkeypatch,command,kind,operation):
    rows=[];d=DiagnosticEmitter(b'synthetic-key',rows.append);d.enabled=True
    socket=AsyncMock();socket.recv.return_value='{"synthetic_result":true}'
    context=AsyncMock();context.__aenter__.return_value=socket
    monkeypatch.setattr(native,'connect',lambda *a,**k:context)
    monkeypatch.setattr(native.AudioServerCommands,'_authenticate',AsyncMock())
    commands=native.AudioServerCommands('audio.example.invalid',lambda:('u','t'));commands.diagnostics=d
    assert await commands._async_request(command,'synthetic_result')is True
    assert all(r.get('request_kind')==kind for r in rows)
    assert all(r.get('operation')==operation for r in rows)
    assert 'SECRET'not in json.dumps(rows)
    assert [call.args[0]for call in socket.send.await_args_list]==[command]
