"""Export identity reflects loaded adapter metadata, not a stale host-base label."""
from homeassistant.loader import async_get_integration
from custom_components.loxone.diagnostics import async_get_config_entry_diagnostics
from test_audioserver_ha import audio_setup


async def test_export_reports_actual_adapter_manifest_version(hass, audio_setup, tmp_path):
    hass.config.config_dir = str(tmp_path)
    entry = await audio_setup.setup(playback=True)
    actual_integration = await async_get_integration(hass, "loxone")
    report = await async_get_config_entry_diagnostics(hass, entry)
    assert actual_integration.version == "0.1.7"
    assert report["environment"]["pyloxone"] == actual_integration.version, (
        "Export must not label this dev12 adapter as the unmodified 0.10.2 host"
    )
