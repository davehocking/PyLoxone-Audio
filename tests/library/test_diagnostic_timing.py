"""Actual shared native request timing, including cleanup after a valid reply."""
import asyncio
import json
from unittest.mock import AsyncMock
import pytest
from pyloxone_audio import native
from pyloxone_audio.diagnostic_events import DiagnosticEmitter,diagnostic_operation


@pytest.mark.parametrize('source',['tunein','loxoneradio','spotify','library','linein','airplay'])
@pytest.mark.parametrize('cleanup_error',[False,True,'unexpected'])
async def test_native_timing_separates_lock_connect_auth_send_response_and_cleanup(monkeypatch,source,cleanup_error):
    rows=[];closed=False
    def sink(row):
        if row['stage']=='request_finished':assert closed,'Transport completion must follow socket cleanup'
        rows.append(row)
    d=DiagnosticEmitter(b'synthetic-key',sink);d.enabled=True
    socket=AsyncMock();socket.recv.return_value='{"play_result":true}'
    class Context:
        async def __aenter__(self):await asyncio.sleep(.002);return socket
        async def __aexit__(self,*args):
            nonlocal closed
            await asyncio.sleep(.002);closed=True
            if cleanup_error=='unexpected':raise RuntimeError('SECRET unexpected cleanup details')
            if cleanup_error:raise OSError('SECRET cleanup details')
    monkeypatch.setattr(native,'connect',lambda *a,**k:Context())
    async def authenticate(*args):await asyncio.sleep(.002)
    monkeypatch.setattr(native.AudioServerCommands,'_authenticate',authenticate)
    commands=native.AudioServerCommands('audio.example.invalid',lambda:('SECRET-user','SECRET-token'))
    commands.diagnostics=d
    await commands._lock.acquire()
    async def release():await asyncio.sleep(.002);commands._lock.release()
    release_task=asyncio.create_task(release())
    command='audio/7/library/play/private-item'if source=='library'else f'audio/7/serviceplay/{source}/private-account/private-item'
    try:
        with diagnostic_operation('synthetic-root'):
            if cleanup_error:
                with pytest.raises(RuntimeError if cleanup_error=='unexpected'else native.AudioCommandError):await commands._async_request(command,'play_result')
            else:assert await commands._async_request(command,'play_result')is True
    finally:await release_task
    stages=[r['stage']for r in rows]
    for stage in ['request','lock_acquired','connection_opened','authenticated','send_attempt','send_completed','reply','request_finished']:assert stage in stages
    assert [stages.index(s)for s in ['request','lock_acquired','connection_opened','authenticated','send_completed','reply','request_finished']]==sorted(stages.index(s)for s in ['request','lock_acquired','connection_opened','authenticated','send_completed','reply','request_finished'])
    assert rows[-1]['outcome']==('error'if cleanup_error else'returned')
    assert rows[-1]['elapsed_ms']>=0
    assert all(r['request_kind']=='source_start'for r in rows)
    assert all(r['source']==source for r in rows)
    assert len({r['operation_id']for r in rows})==1
    assert len({r['request_id']for r in rows})==1
    assert [c.args[0]for c in socket.send.await_args_list]==[command]
    assert 'SECRET'not in json.dumps(rows)
