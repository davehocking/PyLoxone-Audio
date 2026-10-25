"""Current native-session controls replacing removed provider transfer phases.

Synthetic snapshots/transports only. No household or provider control is used.
"""
from dataclasses import replace
from datetime import timedelta
from copy import deepcopy
import asyncio

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from test_spotify_continuity import native, TRACK
from test_spotify_continuity_conflicts import _saved
from custom_components.loxone import audio_sources


@pytest.mark.asyncio
@pytest.mark.parametrize('invalid',['old-frame','missing-item','foreign-user','paused','event-active'])
@pytest.mark.parametrize('recover',[False,True])
async def test_native_handoff_requires_exact_postsend_proof_without_automatic_replay(hass,monkeypatch,invalid,recover):
    entity,session,snapshots,commands=await _saved(hass)
    session.calls.clear()  # Capture-helper fixture setup is not the native path.
    queue=deepcopy(session.queue)
    sent=[]
    observed_change=audio_sources._async_observed_change
    async def bounded(*args,**kwargs):
        return await observed_change(*args,**{**kwargs,'timeout':0.03})
    monkeypatch.setattr(audio_sources,'_async_observed_change',bounded)
    async def send(player,account,*,is_current,on_send):
        assert is_current()
        on_send()
        sent.append((player,account))
        bad=native()
        if invalid=='old-frame':bad=replace(bad,received_at=dt_util.utcnow()-timedelta(seconds=6))
        elif invalid=='missing-item':bad=replace(bad,audio_path=None)
        elif invalid=='foreign-user':bad=replace(bad,source_name='foreign-user')
        elif invalid=='paused':bad=replace(bad,native_mode='pause')
        else:bad=replace(bad,event_active=True,event_idle=False)
        snapshots[0]=bad
        observation=commands.source_observations[7]
        assert not observation.done(), 'Invalid feedback is not exact playing proof'
        if recover and invalid!='event-active':snapshots[0]=native()
    commands.async_spotify_handoff.side_effect=send
    # Event preemption is terminal even if later frames recover. Other invalid
    # frames may be followed by real exact proof before transport settlement.
    if recover and invalid!='event-active':
        await entity.async_select_source('Spotify')
        assert not commands.source_fences
    else:
        with pytest.raises(HomeAssistantError):await entity.async_select_source('Spotify')
        assert commands.source_fences
        snapshots[0]=native()
        await asyncio.sleep(0)
    assert sent==[(7,'native-owner')]
    commands.async_play_catalogue.assert_not_awaited()
    commands.async_play_radio_station.assert_not_awaited()
    assert all(method=='GET' and not url.endswith('/queue') for method,url,_ in session.calls)
    assert session.queue==queue
    assert entity._source_task is None
    assert not entity._spotify_return._account['lock'].locked()
    assert snapshots[0].audio_path==TRACK
