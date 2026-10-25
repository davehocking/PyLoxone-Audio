"""Synthetic native display-name ambiguity must not invent account ownership."""

# ruff: noqa: S101, INP001, ANN001, D103, SLF001
import pytest
from test_spotify_continuity_review import entity_boundary
from custom_components.loxone.audio_radio import RADIO_MEDIA_TYPE, RadioTarget
from custom_components.loxone.spotify_continuity import SpotifyReturnUnavailable


@pytest.mark.asyncio
@pytest.mark.parametrize("same_name", [True, False])
async def test_optional_capture_requires_unambiguous_native_account_user(hass, same_name):
    entity, session, snapshots, commands, _, _ = entity_boundary(hass)
    accounts = commands.async_service_accounts.return_value
    duplicate = dict(accounts[0], id="synthetic-other-account")
    if not same_name:
        duplicate["user"] = "Synthetic other native user"
    commands.async_service_accounts.return_value = [*accounts, duplicate]
    # Retain helper ambiguity qualification directly, while current entity
    # memory must also refuse to attribute one shared label to two accounts.
    if same_name:
        with pytest.raises(SpotifyReturnUnavailable):
            await entity._spotify_return.async_capture(lambda:True)
    else:
        await entity._spotify_return.async_capture(lambda:True)
    entity._radio_catalogue._source_accounts=commands.async_service_accounts.return_value
    entity._radio_catalogue.remember_source(snapshots[0])
    assert (entity._radio_catalogue.source_session('Spotify') is None)==same_name
    radio = RadioTarget("station", "Radio", "world", audio_path="tunein:station:synthetic")
    item = entity._radio_catalogue._item(radio)
    await entity.async_play_media(RADIO_MEDIA_TYPE, item.media_content_id)
    commands.async_play_radio_station.assert_awaited_once()
    assert all(method == "GET" for method, _, _ in session.calls)
    if same_name:
        assert entity._spotify_return.bookmark is None
    else:
        assert entity._spotify_return.bookmark is not None
