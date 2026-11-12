"""Mixed-state follower modes: real owning HA, invented metadata and transport."""
import pytest
from homeassistant.components.media_player import MediaPlayerEntityFeature as F
from test_audio_grouping_ha import grouped_setup, row
from test_audioserver_ha import audio_setup
from test_audioserver_playback import rsa_key
from test_group_modes_leader_ha import harness, request, modes


@pytest.mark.parametrize('follower_state', [0, 1, 2])
async def test_mixed_state_follower_retains_current_leader_modes(hass, grouped_setup, audio_setup, monkeypatch, rsa_key, follower_state):
    h = await harness(hass, grouped_setup, audio_setup, monkeypatch, rsa_key)
    await h.g.feed(h.entry, row('shared', (2, 1, 3)))
    await h.g.callbacks[h.entry.entry_id]['callback']({'play-2': 2, 'play-1': follower_state, 'play-3': 0})
    await h.emit(1, pbr=0, plshuffle=False, plrepeat=0)
    await h.emit(2, plshuffle=True, plrepeat=3)
    await hass.async_block_till_done()
    caller = h.entities[1]
    for view in (modes(hass, caller), (caller.shuffle, caller.repeat, caller.supported_features)):
        assert view[0] is True and view[1] == 'one'
        assert view[2] & F.SHUFFLE_SET and view[2] & F.REPEAT_SET
    assert not caller.supported_features & (F.BROWSE_MEDIA | F.SELECT_SOURCE | F.SEEK | F.MEDIA_ANNOUNCE)
    await request(hass, caller, 'repeat', 'all')
    await hass.async_block_till_done()
    assert h.writes == ['audio/2/repeat/1']
    assert modes(hass, caller)[:2] == (True, 'all')
    assert all(s.closed for s in h.sockets)
