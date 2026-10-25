"""Audio assertions split intact from the mixed fan/alarm/media regression."""
import pytest
from homeassistant.components.media_player import MediaPlayerEntityFeature
from custom_components.loxone.media_player import SUPPORT_LOXONE_AUDIO_ZONE, play_state_to_media_player_state

@pytest.mark.parametrize(
    ("play_state", "expected"),
    [
        (0, "IDLE"),
        (1, "PAUSED"),
        (2, "PLAYING"),
        (-1, "OFF"),
        # Unknown values fall back to a non-playing state instead of None.
        (-2, "IDLE"),
        (3, "IDLE"),
        (100, "IDLE"),
    ],
)
def test_play_state_to_media_player_state_table(play_state, expected) -> None:
    assert play_state_to_media_player_state(play_state).name == expected


def test_media_player_advertises_stop_feature() -> None:
    """STOP is advertised, so ``async_media_stop`` is reachable (not dead)."""
    assert SUPPORT_LOXONE_AUDIO_ZONE & MediaPlayerEntityFeature.STOP
    assert SUPPORT_LOXONE_AUDIO_ZONE & MediaPlayerEntityFeature.PAUSE
    assert SUPPORT_LOXONE_AUDIO_ZONE & MediaPlayerEntityFeature.PLAY
    # SELECT_SOURCE is not (and has never been) advertised:
    assert not (SUPPORT_LOXONE_AUDIO_ZONE & MediaPlayerEntityFeature.SELECT_SOURCE)
