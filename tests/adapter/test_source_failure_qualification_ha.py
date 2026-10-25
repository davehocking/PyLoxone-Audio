"""Failure qualification through real HA, entirely synthetic native/provider I/O."""
# ruff: noqa: S101, SLF001, INP001, ANN001, ANN003, ANN202, D103, F811, PLR2004
import logging
import json

import pytest
from homeassistant.exceptions import HomeAssistantError

from test_audioserver_ha import audio_setup  # noqa: F401 - offline fixture
from test_spotify_library_return_ha import library_journey as current_library_journey
from test_spotify_continuity import TRACK, CONTEXT
from test_spotify_continuity_review import entity_boundary

from custom_components.loxone.pyloxone_api.audioserver import AudioCommandError

LOGGER = "custom_components.loxone.audio_diagnostics"


async def direct_capture(entity):
    """Exercise real capture and HA translation, not mandatory departure capture."""
    try:
        await entity._spotify_return.async_capture(lambda: True)
    except AudioCommandError:
        raise HomeAssistantError(translation_domain='loxone',translation_key='audioserver_playback_failed') from None


async def library_journey(*args):
    entity,session,provider,current_source,writes,saved,entry=await current_library_journey(*args)
    async def source(name):
        if name=='Local Library':
            try: await direct_capture(entity)
            finally: await entity.hass.async_block_till_done()
        else: await current_source(name)
    return entity,session,provider,source,writes,saved,entry


@pytest.mark.asyncio
@pytest.mark.parametrize("zero_native", [False, True])
async def test_initial_capture_failure_retains_exact_comparison_without_logging(
    hass, audio_setup, monkeypatch, tmp_path, caplog, zero_native,
):
    entity, session, _provider, source, writes, _saved, entry = await library_journey(
        hass, audio_setup, monkeypatch, tmp_path, "paused",
    )
    await source("Spotify")
    if zero_native:
        audio_setup.queues[-1].put_nowait(json.dumps({"audio_event": [{
            "playerid": 7, "audiopath": TRACK, "parent": {"id": CONTEXT},
            "sourceName": "native-user", "mode": "play", "time": 0,
            "duration": 180, "pbr": 32,
        }]}))
        await hass.async_block_till_done()
    snapshot = entity._audio_metadata.get(7)
    observed_progress = session.current["progress_ms"] if zero_native else 65000
    session.current["progress_ms"] = observed_progress
    start_calls = len(session.calls)
    before = list(writes)
    caplog.clear()
    caplog.set_level(logging.CRITICAL, logger=LOGGER)
    with pytest.raises(HomeAssistantError) as error:
        await source("Local Library")
    assert error.value.translation_key == "audioserver_playback_failed"
    state = hass.states.get(entity.entity_id)
    assert "audio_last_source_failure" not in state.attributes
    assert observed_progress > snapshot.position * 1000
    assert writes == before
    assert [(method, url.rsplit("/", 1)[-1]) for method, url, _ in session.calls[start_calls:]] == [
        ("GET", "me"), ("GET", "player"),
    ]
    assert not entity._spotify_return.uncertain
    assert not entity._audio_commands.source_fences
    assert entity._source_task is None
    assert not [record for record in caplog.records if record.name == LOGGER]
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("conflict", ["position", "shuffle", "repeat", "final-native"])
async def test_later_capture_failure_identifies_actual_input_not_later_snapshot(
    hass, audio_setup, monkeypatch, tmp_path, caplog, conflict,
):
    entity, session, _provider, source, writes, _saved, entry = await library_journey(
        hass, audio_setup, monkeypatch, tmp_path, "paused",
    )
    await source("Spotify")
    snapshot = entity._audio_metadata.get(7)
    progress = session.current["progress_ms"]
    reads = 0

    async def observed(url):
        nonlocal reads
        if not url.endswith("/me/player"):
            return
        reads += 1
        # The fake response has already copied its payload before this callback.
        if reads == 1:
            if conflict == "position":
                session.current["progress_ms"] = 65000
            elif conflict == "shuffle":
                session.current["shuffle_state"] = True
            elif conflict == "repeat":
                session.current["repeat_state"] = "track"
        if reads == 2:
            session.current["progress_ms"] = 77777  # Must NOT be retained as the failed input.
            if conflict == "final-native":
                audio_setup.queues[-1].put_nowait(json.dumps({"audio_event": [{
                    "playerid": 7, "audiopath": TRACK, "parent": {"id": CONTEXT},
                    "sourceName": "native-user", "mode": "play", "time": 0,
                    "duration": 180, "pbr": 32,
                }]}))
                await hass.async_block_till_done()

    session.on_read = observed
    before = list(writes)
    start_calls = len(session.calls)
    caplog.clear()
    caplog.set_level(logging.CRITICAL, logger=LOGGER)
    with pytest.raises(HomeAssistantError):
        await source("Local Library")
    assert "audio_last_source_failure" not in hass.states.get(entity.entity_id).attributes
    assert snapshot.position > 0
    assert writes == before
    assert [(m, url.rsplit("/", 1)[-1]) for m, url, _ in session.calls[start_calls:]] == [
        ("GET", "me"), ("GET", "player"), ("GET", "queue"), ("GET", "player"),
    ]
    assert not entity._spotify_return.uncertain
    assert not entity._audio_commands.source_fences
    assert entity._source_task is None
    assert not [r for r in caplog.records if r.name == LOGGER]
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(("failure", "expected"), [
    ("disabled", "entry_not_ready"), ("metadata", "entry_not_ready"),
    ("catalogue", "entry_catalogue_missing"),
    # Retired busy veto is covered by genuine overlapping source regressions.
    ("choice", "entry_choice_missing"),
    ("announcement", "entry_announcement_active"), ("precedence", "entry_not_ready"),
])
async def test_entry_refusal_retains_only_first_evaluated_predicate(
    hass, caplog, monkeypatch, failure, expected,
):
    entity, session, _snapshots, commands, _provider, _target = entity_boundary(hass)
    if failure in {"disabled", "precedence"}:
        entity._audio_commands_enabled = False
    if failure == "metadata":
        entity._audio_metadata = None
    if failure == "room":
        entity._spotify_return.uncertain = True
    if failure == "catalogue":
        entity._radio_catalogue = None
    if failure == "task":
        entity._source_task = object()
    if failure in {"announcement", "precedence"}:
        entity._announcement_task = object()
    if failure == "precedence":
        # Make earlier catalogue refusal win without evaluating uncertainty.
        monkeypatch.setattr(entity, "_audio_source_uncertain", lambda: False)
        # Never evaluate the later predicate after a prior refusal.
        def forbidden(*_args):
            raise AssertionError("short-circuit precedence changed")
        monkeypatch.setattr("custom_components.loxone.media_player.spotify_room_uncertain", forbidden)
    original_task = entity._source_task
    generation = entity._source_generation
    caplog.set_level(logging.CRITICAL, logger=LOGGER)
    with pytest.raises(HomeAssistantError) as error:
        await entity.async_select_source("SECRET-choice" if failure == "choice" else "Spotify")
    assert error.value.translation_key == "audioserver_playback_unavailable"
    assert not hasattr(entity, "_audio_last_source_failure")
    assert entity._source_task is original_task
    assert entity._source_generation == generation
    assert not session.calls
    commands.async_service_accounts.assert_not_awaited()
    assert not [r for r in caplog.records if r.name == LOGGER]
    assert "SECRET" not in caplog.text
