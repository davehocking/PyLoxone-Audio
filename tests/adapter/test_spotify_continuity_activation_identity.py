"""A binding-produced uncertainty journal must not disable unrelated native rooms."""

# ruff: noqa: S101, INP001, ANN001, D103, SLF001
import pytest
from test_spotify_continuity import CONFIG, module


@pytest.mark.asyncio
@pytest.mark.parametrize("user", ["synthetic-owner", "synthetic+owner@example.invalid", "A.0_-+@9"])
async def test_all_accepted_binding_characters_round_trip_as_room_specific_fences(hass, tmp_path, user):
    m = module()
    binding = m.SpotifyBinding.parse({**CONFIG, "user_id": user})
    hass.config.config_dir = str(tmp_path)
    directory = hass.config.path(".storage", "pyloxone_spotify_return_dispatch")
    fence = {
        "version": 1,
        "room": "synthetic-room",
        "player": 7,
        "user": binding.user_id,
        "device": binding.device_id,
        "attempt": "a" * 32,
    }
    await hass.async_add_executor_job(m._write_dispatch_marker, directory, "synthetic-identity", "activate", fence)
    await m.async_restore_dispatch_fences(hass)
    assert m.spotify_room_uncertain(hass, "synthetic-room", 7)
    assert not m.spotify_room_uncertain(hass, "unrelated-native-room", 8)
