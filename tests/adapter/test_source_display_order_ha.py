"""Source presentation order through real HA setup; synthetic discovery only."""
# ruff: noqa: S101, INP001, ANN001, D103, SLF001
from unittest.mock import AsyncMock

import pytest

from test_audioserver_ha import audio_setup as audio_setup, zone_entity_id
from test_configured_sources import configured_commands
from custom_components.loxone.pyloxone_api import audioserver as wire


@pytest.mark.asyncio
@pytest.mark.parametrize("history_unavailable", [False, True])
@pytest.mark.parametrize("multiple_inputs", [False, True])
async def test_line_inputs_follow_other_sources_without_changing_targets(
    hass, audio_setup, monkeypatch, history_unavailable, multiple_inputs
):
    commands = configured_commands()
    if multiple_inputs:
        commands.async_source_inputs.return_value.append({
            "type": 6, "id": "ABCDEF123456#1000002",
            "cmd": "linein/ABCDEF123456#1000002", "name": "Second input",
            "valid": True, "power": "on",
        })
    commands.async_recent_sources.return_value = {'items': [
        {'type': 2, 'audiopath': path, 'title': 'Prior room content'}
        for path in ('library:local:track:one', 'loxoneradio:station:one',
                     'spotify@owner:track:one', 'tunein:station:one')
    ]}
    if history_unavailable:
        commands.async_recent_sources.side_effect = TimeoutError("Synthetic history outage")
    for name, value in vars(commands).items():
        monkeypatch.setattr(wire.AudioServerCommands, name, value)
    play_catalogue = AsyncMock()
    play_radio_station = AsyncMock()
    monkeypatch.setattr(wire.AudioServerCommands, "async_play_catalogue", play_catalogue)
    monkeypatch.setattr(wire.AudioServerCommands, "async_play_radio_station", play_radio_station)
    await audio_setup.setup(playback=True)

    for player in (7, 8):
        entity = hass.data["media_player"].get_entity(zone_entity_id(hass, player))
        descriptors = entity._radio_catalogue.source_descriptors
        expected_inputs = (
            ["Line-In · Record player · ABCDEF123456#1000001",
             "Line-In · Second input · ABCDEF123456#1000002"]
            if multiple_inputs else ["Line-In"]
        )
        assert list(descriptors) == [
            "Local Library", "Loxone Radio", "Spotify", "TuneIn", *expected_inputs
        ]
        assert entity.source_list == (expected_inputs if history_unavailable else list(descriptors))
        for label, expected_id in zip(expected_inputs, [
            "ABCDEF123456#1000001", "ABCDEF123456#1000002"
        ], strict=False):
            assert descriptors[label].service == "linein"
            assert descriptors[label].input_id == expected_id
        assert descriptors["Spotify"].account == "owner"
        assert entity.source is None

        # Refresh via the actual entity path must not restore alphabetical-first inputs.
        await entity._async_refresh_native_sources()
        assert list(descriptors) == [
            "Local Library", "Loxone Radio", "Spotify", "TuneIn", *expected_inputs
        ]
        assert entity.source_list == (expected_inputs if history_unavailable else list(descriptors))
    play_catalogue.assert_not_awaited()
    play_radio_station.assert_not_awaited()
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()
