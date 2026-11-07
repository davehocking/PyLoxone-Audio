"""The supported report must state limits of native HA facilities and replies."""
from custom_components.loxone.diagnostics import async_get_config_entry_diagnostics
from test_audioserver_ha import audio_setup

LIMITS = (
    "A native reply is not final HA service acceptance",
    "HA Action history records calls and context, not internal audio transmission or sound",
    "Native HA logs and Action history are separate raw data, not included or sanitised here",
    "Debug console is optional administrator-only Python execution; input is logged",
)


async def test_export_qualifies_native_reply_action_log_and_console_evidence(
    hass, audio_setup, tmp_path
):
    hass.config.config_dir = str(tmp_path)
    entry = await audio_setup.setup(playback=True)
    report = await async_get_config_entry_diagnostics(hass, entry)
    for limit in LIMITS:
        assert limit in report["evidence_limits"]
