"""Full actual HA + synthetic authenticated transport diagnostics journeys."""

import json
import pytest
from test_audioserver_ha import audio_setup
from test_source_return_simplification_ha import (
    rsa_key,
    simplified_harness,
    select,
    sent_commands,
)
from custom_components.loxone.const import DOMAIN


@pytest.mark.parametrize("spotify", [False, True])
@pytest.mark.parametrize("enabled", [False, True])
async def test_full_native_source_and_seek_journey_is_unchanged(
    hass, audio_setup, monkeypatch, rsa_key, spotify, enabled, tmp_path
):
    hass.config.config_dir = str(tmp_path)
    entity, controls, sockets, emit = await simplified_harness(
        hass, audio_setup, monkeypatch, rsa_key, spotify=spotify
    )
    collector = (
        hass.data[DOMAIN][entity._config_entry.entry_id].audio_diagnostics
        if hasattr(entity, "_config_entry")
        else next(iter(hass.data[DOMAIN].values())).audio_diagnostics
    )
    if enabled:
        await collector.async_set_enabled(True)
    await select(hass, entity, spotify=spotify)
    commands = sent_commands(sockets)
    assert commands == (
        [
            "audio/7/serviceplay/spotify/synthetic-account/spotify%3Atrack%3Aoriginal/parentpath/spotify%3Aplaylist%3Aoriginal/0/noshuffle"
            if spotify
            else "audio/7/library/play/library%3Alocal%3Atrack%3Afive/parentpath/library%3Alocal%3Afolder%3Aalbum/4",
            "audio/7/position/45.0",
        ]
    )
    assert all(s.closed for s in sockets)
    assert entity._source_task is None
    report = await collector.async_export()
    rows = report["events"]
    if not enabled:
        assert rows == []
    else:
        assert len([r for r in rows if r["stage"] == "send_attempt"]) == 2
        assert len([r for r in rows if r["stage"] == "send_completed"]) == 2
        assert any(
            r["stage"] == "source_confirmed" and r["transport"] == "source"
            for r in rows
        )
        assert any(
            r["stage"] == "restore_decision"
            and r["phase"] == "post_auth"
            and r["reason"] == "eligible"
            for r in rows
        )
        assert any(
            r["stage"] == "restore_echo" and r["echo_position"] == 45 for r in rows
        )
        assert all("route" in r for r in rows if r["stage"] == "send_attempt")
        assert "synthetic-active-token" not in json.dumps(report)
        assert "Synthetic owner" not in json.dumps(report)


@pytest.mark.parametrize(
    "reason,changes",
    [
        ("track_mismatch", {"audiopath": "library:local:track:new"}),
        ("source_mismatch", {"audiopath": "tunein:station:changed"}),
        ("not_playing", {"mode": "pause"}),
        ("event_active", {"eventype": 1}),
        ("duration_missing", {"duration": None}),
        ("seek_unsupported", {"pbr": 0}),
        ("account_mismatch", {"sourceName": "Other synthetic owner"}),
    ],
)
async def test_post_auth_restore_refusal_does_not_fail_confirmed_source(
    hass, audio_setup, monkeypatch, rsa_key, reason, changes, tmp_path
):
    hass.config.config_dir = str(tmp_path)
    entity, controls, sockets, emit = await simplified_harness(
        hass, audio_setup, monkeypatch, rsa_key
    )
    collector = next(iter(hass.data[DOMAIN].values())).audio_diagnostics
    await collector.async_set_enabled(True)

    async def changed(_entity, emit, target):
        await emit({**target, **changes})

    controls["during_seek"] = changed
    await select(hass, entity)
    assert len(sent_commands(sockets)) == 1
    assert all(s.closed for s in sockets)
    report = await collector.async_export()
    assert any(
        r["stage"] == "restore_decision"
        and r["phase"] == "post_auth"
        and r["reason"] == reason
        for r in report["events"]
    )
    assert any(r["stage"] == "restore_failed" for r in report["events"])
    assert entity._source_task is None
