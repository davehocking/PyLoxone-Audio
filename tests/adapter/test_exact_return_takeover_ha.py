"""Exact-return qualification across real HA action takeover; synthetic I/O only.

The first regression preserves reviewer99's functional assertions and real
concurrent service schedule; it is not a settled retry or a generation bump.
"""

# ruff: noqa: F401, F811
import asyncio

import pytest
from homeassistant.exceptions import HomeAssistantError
from test_audioserver_ha import audio_setup
from test_audioserver_playback import rsa_key
from test_exact_track_return_ha import exact_harness
from test_seek_readiness_ha import select


@pytest.mark.parametrize(
    "overlap", [False, True], ids=["settled-control", "actual-overlap"]
)
async def test_new_explicit_return_does_not_accept_older_wrong_track(
    hass, audio_setup, monkeypatch, rsa_key, overlap
):
    h = await exact_harness(hass, audio_setup, monkeypatch, rsa_key)
    correct = h.target.copy()
    h.target.update(audiopath="spotify:track:wrong-four", time=0.005)
    old = asyncio.create_task(select(hass, h))
    newer = None
    try:
        await asyncio.wait_for(h.started.wait(), 1)
        assert h.metadata.get(7).audio_path == "spotify:track:wrong-four"
        assert h.entity._radio_catalogue.source_session("Spotify") == h.bookmark
        if not overlap:
            with pytest.raises(HomeAssistantError):
                await asyncio.wait_for(old, 1)
        else:
            assert not old.done(), (
                "Old exact-return waiter must still own the first visit"
            )
        h.target.update(correct)
        newer = asyncio.create_task(select(hass, h))
        await asyncio.wait_for(newer, 1)
        old_result = await asyncio.gather(old, return_exceptions=True)
        if overlap:
            assert isinstance(old_result[0], asyncio.CancelledError)
        assert len(h.writes) == 3, (
            "Newest explicit return must request retained A, not accept wrong B as a native no-op"
        )
        assert h.writes[1].endswith(
            "/parentpath/spotify%3Aplaylist%3Aoriginal/13/noshuffle"
        )
        assert h.writes[2] == "audio/7/position/30.021"
        assert (
            h.entity._radio_catalogue.source_session("Spotify").audio_path
            == h.saved["audiopath"]
        )
        assert h.metadata.get(7).audio_path == h.saved["audiopath"]
        assert not h.commands.source_fences
        assert all(s.closed for s in h.sockets)
    finally:
        for task in (old, newer):
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(t for t in (old, newer) if t is not None), return_exceptions=True
        )
        await h.commands.async_close()


async def wait_generation(entity, generation):
    """Wait for the actual owning service, not an artificial generation bump."""
    async with asyncio.timeout(1):
        while entity._source_generation < generation:
            await asyncio.sleep(0)


@pytest.mark.parametrize(
    "action", ["return", "third-return", "cancel", "unload", "browse"]
)
async def test_unresolved_return_survives_awaited_old_socket_cleanup(
    hass, audio_setup, monkeypatch, rsa_key, action
):
    from pyloxone_audio.catalogue import CatalogueTarget
    from pyloxone_audio.radio import RADIO_MEDIA_TYPE

    h = await exact_harness(hass, audio_setup, monkeypatch, rsa_key)
    correct = h.target.copy()
    h.target.update(audiopath="spotify:track:wrong-four", time=0.005)
    from test_audioserver_playback import SyntheticAudioSocket

    closing, release = asyncio.Event(), asyncio.Event()
    socket = None
    original_exit = SyntheticAudioSocket.__aexit__

    async def blocked_exit(self, *args):
        if self is socket:
            closing.set()
            await asyncio.wait_for(release.wait(), 1)
        await original_exit(self, *args)

    # Async with caches __aexit__ on entry; patch before opening the socket.
    monkeypatch.setattr(SyntheticAudioSocket, "__aexit__", blocked_exit)
    old = asyncio.create_task(select(hass, h))
    newer = third = None
    try:
        await asyncio.wait_for(h.started.wait(), 1)
        socket = h.sockets[-1]
        newer = asyncio.create_task(select(hass, h))
        await asyncio.wait_for(closing.wait(), 1)
        # The old owner is invalid already, but cleanup is not finished. Neither
        # more wrong feedback nor a third action may erase the saved obligation.
        assert not old.done() and not newer.done()
        assert h.entity._source_return_rejection is not None
        assert h.entity._source_return_rejection[0] == h.bookmark
        for position in (1, 2):
            await h.emit({**h.target, "time": position})
        assert h.entity._radio_catalogue.source_session("Spotify") == h.bookmark
        assert len(h.writes) == 1
        generation = h.entity._source_generation
        if action == "third-return":
            third = asyncio.create_task(select(hass, h))
            await wait_generation(h.entity, generation + 1)
        elif action == "cancel":
            newer.cancel()
        elif action == "unload":
            entry = hass.config_entries.async_entries("loxone")[0]
            third = asyncio.create_task(
                hass.config_entries.async_unload(entry.entry_id)
            )
            async with asyncio.timeout(1):
                while not h.entity._audio_removed:
                    await asyncio.sleep(0)
        elif action == "browse":
            item = h.entity._radio_catalogue._item(
                CatalogueTarget(
                    "item",
                    "Synthetic explicit choice",
                    "spotify",
                    account="synthetic-account",
                    folder="spotify:track:wrong-four",
                    audio_path="spotify:track:wrong-four",
                )
            )
            third = asyncio.create_task(
                hass.services.async_call(
                    "media_player",
                    "play_media",
                    {
                        "entity_id": h.entity.entity_id,
                        "media_content_type": RADIO_MEDIA_TYPE,
                        "media_content_id": item.media_content_id,
                    },
                    blocking=True,
                )
            )
            await wait_generation(h.entity, generation + 1)
        if action != "browse":
            h.target.update(correct)
        assert len(h.writes) == 1
        release.set()
        results = await asyncio.wait_for(
            asyncio.gather(
                *(t for t in (old, newer, third) if t is not None),
                return_exceptions=True,
            ),
            1,
        )
        assert isinstance(results[0], asyncio.CancelledError)
        if action in ("third-return", "unload", "browse", "cancel"):
            assert isinstance(results[1], asyncio.CancelledError)
        else:
            assert results[1] is None
        if action == "unload":
            assert results[2] is True
            assert len(h.writes) == 1 and h.entity._audio_removed
            assert h.entity._radio_catalogue.source_session("Spotify") == h.bookmark
            assert not h.metadata._listeners
        elif action == "browse":
            assert results[2] is None
            # Explicitly choosing the exact already-playing item is a valid
            # content-qualified no-op, unlike the provider-only Source return.
            assert len(h.writes) == 1 and not any("/position/" in w for w in h.writes)
            assert h.entity._source_return_rejection is None
            assert (
                h.entity._radio_catalogue.source_session("Spotify").audio_path
                == "spotify:track:wrong-four"
            )
            # Superseded finally blocks cannot reinstall the old rejection.
            for position in (3, 4):
                await h.emit({**h.target, "time": position})
            assert h.entity._source_return_rejection is None
        else:
            if action == "cancel":
                assert len(h.writes) == 1
                assert h.entity._radio_catalogue.source_session("Spotify") == h.bookmark
                await select(hass, h)
            elif third is not None:
                assert results[2] is None
            assert len(h.writes) == 3
            assert h.writes[-1] == "audio/7/position/30.021"
            assert (
                h.entity._radio_catalogue.source_session("Spotify").audio_path
                == h.saved["audiopath"]
            )
            assert h.entity._source_return_rejection is None
        assert not h.commands.source_fences
        assert all(s.closed for s in h.sockets)
        assert h.entity._source_task is None
    finally:
        release.set()
        for task in (old, newer, third):
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(t for t in (old, newer, third) if t is not None), return_exceptions=True
        )
        await h.commands.async_close()


async def test_failed_newer_return_retains_bookmark_until_independent_playback(
    hass, audio_setup, monkeypatch, rsa_key
):
    h = await exact_harness(hass, audio_setup, monkeypatch, rsa_key)
    h.target.update(audiopath="spotify:track:wrong-four", time=0.005)
    old = asyncio.create_task(select(hass, h))
    try:
        await asyncio.wait_for(h.started.wait(), 1)
        with pytest.raises(HomeAssistantError):
            await select(hass, h)
        result = await asyncio.gather(old, return_exceptions=True)
        assert isinstance(result[0], asyncio.CancelledError)
        assert len(h.writes) == 2 and not any("/position/" in w for w in h.writes)
        assert h.entity._radio_catalogue.source_session("Spotify") == h.bookmark
        for position in (1, 2):
            await h.emit({**h.target, "time": position})
        assert h.entity._radio_catalogue.source_session("Spotify") == h.bookmark
        for position in (3, 4):
            await h.emit(
                {**h.target, "audiopath": "spotify:track:independent", "time": position}
            )
        assert (
            h.entity._radio_catalogue.source_session("Spotify").audio_path
            == "spotify:track:independent"
        )
        assert h.entity._source_return_rejection is None
        # Wrong-track timeout deliberately retains its uncertainty observer;
        # independent history qualification must not silently release it.
        assert 7 in h.commands.source_fences
        await select(hass, h)
        assert len(h.writes) == 2, "New explicit current-session choice is not a replay"
        assert not h.commands.source_fences and all(s.closed for s in h.sockets)
    finally:
        old.cancel()
        await asyncio.gather(old, return_exceptions=True)
        await h.commands.async_close()


async def test_auth_failure_during_takeover_does_not_legitimise_wrong_track(
    hass, audio_setup, monkeypatch, rsa_key
):
    h = await exact_harness(hass, audio_setup, monkeypatch, rsa_key)
    correct = h.target.copy()
    h.target.update(audiopath="spotify:track:wrong-four", time=0.005)
    old = asyncio.create_task(select(hass, h))
    try:
        await asyncio.wait_for(h.started.wait(), 1)
        credentials = h.commands._credentials
        h.commands._credentials = lambda: ("", "")
        with pytest.raises(HomeAssistantError):
            await select(hass, h)
        result = await asyncio.gather(old, return_exceptions=True)
        assert isinstance(result[0], asyncio.CancelledError)
        assert len(h.writes) == 1
        assert h.entity._radio_catalogue.source_session("Spotify") == h.bookmark
        assert h.metadata.get(7).audio_path == "spotify:track:wrong-four"
        h.commands._credentials = credentials
        h.target.update(correct)
        await select(hass, h)
        assert len(h.writes) == 3 and h.writes[-1] == "audio/7/position/30.021"
        assert (
            h.entity._radio_catalogue.source_session("Spotify").audio_path
            == h.saved["audiopath"]
        )
        assert h.entity._source_return_rejection is None
        assert not h.commands.source_fences and all(s.closed for s in h.sockets)
    finally:
        old.cancel()
        await asyncio.gather(old, return_exceptions=True)
        await h.commands.async_close()


async def test_confirmed_matching_overlap_keeps_native_session_noop(
    hass, audio_setup, monkeypatch, rsa_key
):
    h = await exact_harness(hass, audio_setup, monkeypatch, rsa_key)
    h.target["pbr"] = 0
    old = asyncio.create_task(select(hass, h))
    newer = None
    try:
        await asyncio.wait_for(h.started.wait(), 1)
        async with asyncio.timeout(1):
            while not any(e["stage"] == "source_confirmed" for e in h.events):
                await asyncio.sleep(0)
        assert not old.done(), "Confirmed source is still awaiting optional capability"
        assert not h.commands.source_fences
        newer = asyncio.create_task(select(hass, h))
        await asyncio.wait_for(newer, 1)
        result = await asyncio.gather(old, return_exceptions=True)
        assert isinstance(result[0], asyncio.CancelledError)
        assert len(h.writes) == 1, "Legitimate confirmed active session stays a no-op"
        assert h.entity._source_return_rejection is None
        assert (
            h.entity._radio_catalogue.source_session("Spotify").audio_path
            == h.saved["audiopath"]
        )
        assert not h.commands.source_fences and all(s.closed for s in h.sockets)
    finally:
        for task in (old, newer):
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(t for t in (old, newer) if t is not None), return_exceptions=True
        )
        await h.commands.async_close()
