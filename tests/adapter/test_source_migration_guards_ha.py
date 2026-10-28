"""Case-level migration gaps: actual HA, synthetic native/provider I/O only."""
# ruff: noqa: S101, SLF001, INP001, F811, F401
import json
from unittest.mock import AsyncMock

import pytest
from aiohttp import ClientError
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from test_audioserver_ha import audio_setup
from test_source_simple_session_ha import session_room
from custom_components.loxone.pyloxone_api import audioserver as wire


@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['play','pause'])
@pytest.mark.parametrize('optional',['unloaded','disabled','outage','missing-session'])
async def test_foreign_native_account_cannot_authorize_bound_account_fallback(hass,audio_setup,monkeypatch,mode,optional):
    entity,emit,writes,session,row=await session_room(hass,audio_setup,monkeypatch)
    await emit({**row,'mode':mode,'sourceName':'Foreign native user'})
    entry=hass.config_entries.async_get_entry('synthetic-entry')
    if optional=='unloaded': entry.state=ConfigEntryState.NOT_LOADED
    elif optional=='disabled': entry.disabled_by='user'
    elif optional=='missing-session': entry.runtime_data.session=None
    else: monkeypatch.setattr(session,'async_request',AsyncMock(side_effect=ClientError('Synthetic optional outage')))
    with pytest.raises(HomeAssistantError):
        await entity.async_select_source('Spotify')
    assert writes==[], 'Unavailable optional auth must not turn foreign native playback into permission to replace it'
    assert all(m=='GET' for m,_,_ in session.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['item','account'])
async def test_readable_provider_cannot_replace_preexisting_paused_native_identity(hass,audio_setup,monkeypatch,change):
    entity,emit,writes,session,row=await session_room(hass,audio_setup,monkeypatch)
    await emit({**row,'mode':'pause',**({'audiopath':'spotify:track:'+'N'*22} if change=='item' else {'sourceName':'Foreign native user'})})
    if change == "account":
        with pytest.raises(HomeAssistantError):
            await entity.async_select_source("Spotify")
        assert writes == []
    else:
        # Source resume does not impose the provider read's exact historical item.
        await entity.async_select_source("Spotify")
        assert writes == ["audio/7/serviceplay/spotify/synthetic-account/"]
    assert all(m=='GET' for m,_,_ in session.calls)
