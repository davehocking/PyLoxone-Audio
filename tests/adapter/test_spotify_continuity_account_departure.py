"""Review25: another native account must remain able to depart for radio."""

# ruff: noqa: S101, INP001, ANN001, D103, SLF001
from dataclasses import replace

import pytest
from homeassistant.exceptions import HomeAssistantError
from test_spotify_continuity import NEXT, native
from test_spotify_continuity_conflicts import _saved
from custom_components.loxone.audio_radio import RADIO_MEDIA_TYPE, RadioTarget

CAPTURE_ACCOUNT_READ = 1  # Current source inventory, not removed capture.


@pytest.mark.asyncio
@pytest.mark.parametrize("guard", ["none", "generation", "removed", "native-change"])
async def test_deliberate_other_native_account_can_leave_for_radio_without_using_bound_provider(hass, guard):
    entity, session, snapshots, commands = await _saved(hass)
    last_good=dict(entity._radio_catalogue.source_sessions)
    session.calls.clear()
    commands.async_service_accounts.return_value = [
        *commands.async_service_accounts.return_value,
        {"cmd": "spotify", "id": "native-b", "user": "synthetic-user-b", "configerror": False},
    ]
    path = "spotify@native-b:playlist:" + "D" * 22
    target = replace(
        entity._radio_catalogue.source_choices["Spotify"],
        folder=path,
        audio_path=path,
        account="native-b",
    )

    async def start_b(_player, _service, _account, _path, *, is_current, on_send) -> None:
        assert (_service, _account, _path) == ("spotify", "native-b", path)
        assert is_current()
        on_send()
        snapshots[0] = replace(
            native(),
            audio_path=NEXT,
            source_name="synthetic-user-b",
            parent_id="spotify:playlist:" + "D" * 22,
        )

    commands.async_play_catalogue.side_effect = start_b
    item = entity._radio_catalogue._item(target)
    await entity.async_play_media(RADIO_MEDIA_TYPE, item.media_content_id)
    commands.async_play_catalogue.assert_awaited_once()
    assert entity._spotify_return.bookmark is None
    assert all(entity._radio_catalogue.source_sessions.get(k) is v for k,v in last_good.items())
    commands.async_play_radio_station.reset_mock()
    before = snapshots[0]
    account_reads = 0

    async def read_accounts() -> list[dict]:
        nonlocal account_reads
        account_reads += 1
        # Mutate the actual source-inventory lookup still awaited by departure.
        if account_reads != CAPTURE_ACCOUNT_READ:
            return commands.async_service_accounts.return_value
        if guard == "generation":
            entity._source_generation+=1
        elif guard == "removed":
            entity._audio_removed = True
        elif guard == "native-change":
            snapshots[0] = replace(before, audio_path="spotify:track:" + "E" * 22)
        return commands.async_service_accounts.return_value

    commands.async_service_accounts.side_effect = read_accounts
    radio = RadioTarget("station", "Radio", "world", audio_path="tunein:station:synthetic-radio")
    entity._radio_catalogue.source_choices["TuneIn"] = radio
    commands.async_recent_sources.return_value["items"].append(
        {"audiopath": radio.audio_path, "type": 2, "title": "Radio"}
    )
    if guard == "none":
        await entity.async_select_source("TuneIn")
        commands.async_play_radio_station.assert_awaited_once()
        assert snapshots[0].source == "TuneIn"
    else:
        with pytest.raises(HomeAssistantError):
            await entity.async_select_source("TuneIn")
        commands.async_play_radio_station.assert_not_awaited()
    assert account_reads == CAPTURE_ACCOUNT_READ
    assert not session.calls
    assert entity._spotify_return.bookmark is None
    assert all(entity._radio_catalogue.source_sessions.get(k) is v for k,v in last_good.items())
    assert not commands.source_fences
