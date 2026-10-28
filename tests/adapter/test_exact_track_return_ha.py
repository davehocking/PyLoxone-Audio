"""Exact saved return through actual HA + native authentication/synthetic I/O.

Invented account/content IDs; saved 30.021 seconds and zero-based index13
reproduce the incident shape, not its firmware cause. Wrong feedback is produced
independently of /noshuffle so wire parity cannot manufacture a passing outcome.
"""

# ruff: noqa: F401, F811
import asyncio

import pytest
from homeassistant.exceptions import HomeAssistantError
from test_audioserver_ha import audio_setup
from test_audioserver_playback import rsa_key
from test_seek_readiness_ha import readiness_harness, select
from custom_components.loxone import audio_sources


@pytest.mark.parametrize("parent", [False, True])
@pytest.mark.parametrize("kind", ["track", "episode"])
def test_per_item_diagnostics_survive_persisted_schema(parent, kind, tmp_path):
    from custom_components.loxone.audio_diagnostics import RollingJournal, _safe_event
    from pyloxone_audio.diagnostic_events import DiagnosticEmitter

    rows = []
    emitter = DiagnosticEmitter(b"synthetic-key", rows.append)
    emitter.enabled = True
    route = f"audio/7/serviceplay/spotify/synthetic/spotify%3A{kind}%3Asynthetic"
    if parent:
        route += "/parentpath/spotify%3Aalbum%3Asynthetic/13"
    emitter.emit("send_attempt", route=route + "/noshuffle")
    assert _safe_event(rows[0])
    journal = RollingJournal(tmp_path / "journal")
    journal.maintain(rows)
    recovered = RollingJournal(tmp_path / "journal").export()
    assert recovered["events"] == rows
    assert recovered["invalid_records"] == 0
    aliased = rows[0]["route"]
    for bad in (
        aliased + "/extra",
        aliased + "/noshuffle",
        aliased.replace("/spotify/", "/tunein/"),
        aliased.replace("/noshuffle", "/synthetic-private"),
    ):
        assert not _safe_event({**rows[0], "route": bad})


async def exact_harness(hass, audio_setup, monkeypatch, rsa_key, *, shuffle=False):
    h = await readiness_harness(
        hass, audio_setup, monkeypatch, rsa_key, spotify=True, startup=32
    )
    saved = {**h.saved, "time": 30.021, "plshuffle": shuffle}
    await h.emit(saved)
    await h.emit(
        {
            "playerid": 7,
            "mode": "play",
            "eventype": 0,
            "audiopath": "tunein:station:synthetic",
        }
    )
    h.saved = saved
    h.target.update(plshuffle=shuffle)

    async def folder(_self, service, account, path, offset):
        paths = [f"spotify:track:synthetic-index-{i}" for i in range(24)]
        paths[4], paths[13] = "spotify:track:wrong-four", saved["audiopath"]
        return [
            {
                "start": offset,
                "totalitems": len(paths),
                "audiopath": path,
                "items": [
                    {
                        "type": 2,
                        "id": p.replace("spotify:", "spotify@synthetic-account:", 1),
                        "audiopath": p,
                        "name": "Synthetic",
                    }
                    for p in paths
                ],
            }
        ]

    monkeypatch.setattr(type(h.commands), "async_media_folder", folder)
    real_observe = audio_sources._async_observed_change

    async def bounded(*args, **kwargs):
        kwargs["timeout"] = 0.08
        return await real_observe(*args, **kwargs)

    monkeypatch.setattr(audio_sources, "_async_observed_change", bounded)
    h.bookmark = h.entity._radio_catalogue.source_session("Spotify")
    return h


@pytest.mark.parametrize("shuffle", [False, True])
async def test_wrong_track_return_is_not_success_or_a_new_bookmark(
    hass, audio_setup, monkeypatch, rsa_key, shuffle
):
    h = await exact_harness(hass, audio_setup, monkeypatch, rsa_key, shuffle=shuffle)
    h.target.update(
        audiopath="spotify:track:wrong-four", title="Synthetic wrong track", time=0.005
    )
    try:
        with pytest.raises(HomeAssistantError):
            await select(hass, h)
        assert len(h.writes) == 1 and "/position/" not in h.writes[0]
        assert not any(e["stage"] == "source_confirmed" for e in h.events)
        assert h.entity._radio_catalogue.source_session("Spotify") == h.bookmark
        assert h.metadata.get(7).audio_path == "spotify:track:wrong-four"
        assert h.entity.media_title == "Synthetic wrong track"
        # Continuing the rejected return is not an independent new selection.
        for position in (1.0, 2.0):
            await h.emit({**h.target, "time": position})
        assert h.entity._radio_catalogue.source_session("Spotify") == h.bookmark
        assert all(s.closed for s in h.sockets)
    finally:
        await h.commands.async_close()


async def test_next_explicit_return_retries_retained_track_not_wrong_active_noop(
    hass, audio_setup, monkeypatch, rsa_key
):
    h = await exact_harness(hass, audio_setup, monkeypatch, rsa_key)
    correct = h.target.copy()
    h.target.update(audiopath="spotify:track:wrong-four", time=0.005)
    with pytest.raises(HomeAssistantError):
        await select(hass, h)
    h.target.update(correct)
    await select(hass, h)
    assert len(h.writes) == 3, (
        "Explicit return must not accept the rejected active track as a no-op"
    )
    assert h.writes[1].endswith(
        "/parentpath/spotify%3Aplaylist%3Aoriginal/13/noshuffle"
    )
    assert h.writes[2] == "audio/7/position/30.021"
    assert (
        h.entity._radio_catalogue.source_session("Spotify").audio_path
        == h.saved["audiopath"]
    )
    assert not h.commands.source_fences


async def test_partial_parent_change_cannot_legitimise_rejected_track(
    hass, audio_setup, monkeypatch, rsa_key
):
    h = await exact_harness(hass, audio_setup, monkeypatch, rsa_key)
    h.target.update(audiopath="spotify:track:wrong-four", time=0.005)
    with pytest.raises(HomeAssistantError):
        await select(hass, h)
    for position in (1, 2, 3):
        await h.emit({**h.target, "parent": {}, "time": position})
    assert h.entity._radio_catalogue.source_session("Spotify") == h.bookmark
    await h.commands.async_close()


async def test_one_unrelated_frame_cannot_release_rejected_return_history(
    hass, audio_setup, monkeypatch, rsa_key
):
    h = await exact_harness(hass, audio_setup, monkeypatch, rsa_key)
    h.target.update(audiopath="spotify:track:wrong-four", time=0.005)
    with pytest.raises(HomeAssistantError):
        await select(hass, h)
    await h.emit(
        {**h.target, "audiopath": "spotify:track:unqualified-other", "time": 1}
    )
    for position in (2, 3):
        await h.emit({**h.target, "time": position})
    assert h.entity._radio_catalogue.source_session("Spotify") == h.bookmark
    await h.commands.async_close()


@pytest.mark.parametrize("feedback", ["track", "account", "room"])
@pytest.mark.parametrize("shuffle", [False, True])
async def test_exact_track_waits_past_unrelated_feedback_then_seeks_once(
    hass, audio_setup, monkeypatch, rsa_key, feedback, shuffle
):
    h = await exact_harness(hass, audio_setup, monkeypatch, rsa_key, shuffle=shuffle)
    correct = h.target.copy()
    h.target["time"] = 0.005
    if feedback == "track":
        h.target.update(audiopath="spotify:track:wrong-four")
    elif feedback == "account":
        h.target.update(sourceName="Other synthetic owner")
    else:
        h.target.update(playerid=8)
    pending = asyncio.create_task(select(hass, h))
    try:
        await asyncio.wait_for(h.started.wait(), 1)
        await asyncio.sleep(0.01)
        assert not pending.done()
        assert len(h.writes) == 1
        assert h.entity._radio_catalogue.source_session("Spotify") == h.bookmark
        await h.emit(correct)
        await asyncio.wait_for(pending, 1)
        assert h.writes[0].endswith(
            "/parentpath/spotify%3Aplaylist%3Aoriginal/13/noshuffle"
        )
        assert h.writes[1:] == ["audio/7/position/30.021"]
        assert any(e["stage"] == "source_confirmed" for e in h.events)
        assert h.metadata.get(7).audio_path == h.saved["audiopath"]
        assert not h.commands.source_fences
        assert all(s.closed for s in h.sockets)
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        await h.commands.async_close()


async def test_later_qualified_independent_track_can_replace_failed_return_bookmark(
    hass, audio_setup, monkeypatch, rsa_key
):
    h = await exact_harness(hass, audio_setup, monkeypatch, rsa_key)
    h.target.update(audiopath="spotify:track:wrong-four", time=0.005)
    with pytest.raises(HomeAssistantError):
        await select(hass, h)
    for position in (1, 2):
        await h.emit(
            {**h.target, "audiopath": "spotify:track:new-independent", "time": position}
        )
    assert (
        h.entity._radio_catalogue.source_session("Spotify").audio_path
        == "spotify:track:new-independent"
    )
    assert len(h.writes) == 1
    await h.commands.async_close()


async def test_late_matching_feedback_updates_bookmark_without_replaying_or_seeking(
    hass, audio_setup, monkeypatch, rsa_key
):
    h = await exact_harness(hass, audio_setup, monkeypatch, rsa_key)
    correct = h.target.copy()
    h.target.update(audiopath="spotify:track:wrong-four", time=0.005)
    with pytest.raises(HomeAssistantError):
        await select(hass, h)
    for position in (1, 2):
        await h.emit({**correct, "time": position})
    saved = h.entity._radio_catalogue.source_session("Spotify")
    assert saved.audio_path == h.saved["audiopath"] and saved.position == 2
    assert not h.commands.source_fences
    assert len(h.writes) == 1
    await h.commands.async_close()


async def test_later_explicit_browse_can_select_previously_rejected_item(
    hass, audio_setup, monkeypatch, rsa_key
):
    from pyloxone_audio.catalogue import CatalogueTarget
    from pyloxone_audio.radio import RADIO_MEDIA_TYPE

    h = await exact_harness(hass, audio_setup, monkeypatch, rsa_key)
    h.target.update(audiopath="spotify:track:wrong-four", time=0.005)
    with pytest.raises(HomeAssistantError):
        await select(hass, h)
    item = h.entity._radio_catalogue._item(
        CatalogueTarget(
            "item",
            "Synthetic explicit selection",
            "spotify",
            account="synthetic-account",
            folder="spotify:track:wrong-four",
            audio_path="spotify:track:wrong-four",
        )
    )
    await hass.services.async_call(
        "media_player",
        "play_media",
        {
            "entity_id": h.entity.entity_id,
            "media_content_type": RADIO_MEDIA_TYPE,
            "media_content_id": item.media_content_id,
        },
        blocking=True,
    )
    assert (
        h.entity._radio_catalogue.source_session("Spotify").audio_path
        == "spotify:track:wrong-four"
    )
    assert h.entity._source_return_rejection is None
    assert not h.commands.source_fences
    assert not any("/position/" in w for w in h.writes)
    await h.commands.async_close()
