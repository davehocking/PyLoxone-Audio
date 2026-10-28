"""Native-only 0.1.1 contracts; synthetic inputs, no household configuration."""
import pytest
import voluptuous as vol
from custom_components.loxone import config_flow, media_player, spotify_continuity, audio_sources  # owning import guard
from test_audioserver_ha import audio_setup, zone_entity_id
from test_spotify_continuity import CONFIG


@pytest.mark.asyncio
async def test_saved_legacy_room_binding_is_ignored_by_real_entry_reload(hass, audio_setup):
    entry = await audio_setup.setup(playback=True)
    hass.config_entries.async_update_entry(entry, options={**entry.options, 'audioserver_spotify_return': {'synthetic-zone-7': CONFIG}})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    entity = hass.data['media_player'].get_entity(zone_entity_id(hass, 7))
    assert getattr(entity, '_spotify_return', None) is None, 'Saved legacy options must not construct an OAuth/session bridge'
    assert entity._can_announce()



@pytest.mark.asyncio
async def test_setup_and_options_do_not_offer_or_accept_provider_room_bindings():
    """Normal schema submission cannot enable the retired provider bridge."""
    for schema in (config_flow.DATA_SCHEMA_SETUP, config_flow.DATA_SCHEMA_OPTIONS):
        assert 'audioserver_spotify_return' not in {key.schema for key in schema.schema}
        with pytest.raises(vol.Invalid):
            schema({'audioserver_spotify_return': {}})


@pytest.mark.parametrize("language", ["en", "de", "cs", "fr", "it", "es", "nl", "pt", "pt-PT", "pt-BR"])
@pytest.mark.usefixtures("enable_custom_integrations")
async def test_real_ha_translations_do_not_offer_retired_bindings(hass, language):
    from homeassistant.helpers.translation import async_get_translations
    for category in ("config", "options", "exceptions"):
        resources = await async_get_translations(hass, language, category, {"loxone"})
        assert not any("audioserver_spotify_return" in key or "invalid_spotify_return" in key for key in resources)
