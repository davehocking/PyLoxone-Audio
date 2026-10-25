"""Fifth source-review regressions through actual HA, synthetic only."""
# ruff: noqa: S101, SLF001, INP001, F811, F401
import asyncio
from unittest.mock import AsyncMock

import pytest
from aiohttp import ClientError
from homeassistant.exceptions import HomeAssistantError
from test_audioserver_ha import audio_setup
from test_source_simple_session_ha import session_room


@pytest.mark.asyncio
@pytest.mark.parametrize('external',['pause','item'])
async def test_external_native_change_during_failed_optional_read_cannot_be_rebased(hass,audio_setup,monkeypatch,external):
    entity,emit,writes,session,row=await session_room(hass,audio_setup,monkeypatch)
    await emit(row)
    entered,release=asyncio.Event(),asyncio.Event()
    original=session.async_request
    async def delayed(method,url,**kwargs):
        if url.endswith('/me/player'):
            entered.set(); await release.wait()
            raise ClientError('Synthetic optional read loss after native change')
        return await original(method,url,**kwargs)
    monkeypatch.setattr(session,'async_request',delayed)
    action=asyncio.create_task(hass.services.async_call('media_player','select_source',{'entity_id':entity.entity_id,'source':'Spotify'},blocking=True))
    try:
        await asyncio.wait_for(entered.wait(),1)
        changed={**row,**({'mode':'pause'} if external=='pause' else {'audiopath':'spotify:track:'+'N'*22})}
        await emit(changed)
        release.set()
        result=await asyncio.gather(action,return_exceptions=True)
        assert writes==[], 'A changed external native selection must prevent all fallback/resume writes'
        assert isinstance(result[0],HomeAssistantError)
        assert entity._audio_metadata.get(7).native_mode==changed['mode']
        assert entity._audio_metadata.get(7).audio_path==changed['audiopath']
        assert entity._source_task is None
    finally:
        release.set(); action.cancel(); await asyncio.gather(action,return_exceptions=True)
