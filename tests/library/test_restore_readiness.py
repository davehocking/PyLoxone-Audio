"""Portable shared readiness policy with synthetic metadata and command I/O."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest
from pyloxone_audio.catalogue import CatalogueTarget
from pyloxone_audio.metadata import AudioMetadataCoordinator
from pyloxone_audio.native import parse_audio_events
from pyloxone_audio.sources import async_select_catalogue


async def fixture(spotify, *, saved_position=45, saved_session=True):
    metadata = AudioMetadataCoordinator("audio.example.invalid")
    receiver = metadata._client._receiver
    writes = []
    source = "spotify" if spotify else "library"
    path = "spotify:track:synthetic" if spotify else "library:local:track:synthetic"
    raw = dict(
        playerid=101,
        mode="play",
        eventype=0,
        audiopath=path,
        sourceName="Synthetic account",
        time=0,
        duration=180,
        pbr=0,
    )

    def emit(**changes):
        row = parse_audio_events({"audio_event": [{**raw, **changes}]})[0]
        receiver._apply(row)
        metadata._on_update((row,))
        return row

    saved = replace(emit(pbr=32), position=saved_position)
    target = CatalogueTarget(
        "item",
        "Synthetic",
        source,
        account="synthetic-account" if spotify else "",
        folder=path,
        audio_path=path,
        return_session=saved if saved_session else None,
    )

    class Commands:
        announcement_fences = {}
        source_fences = {}

        async def async_service_accounts(self):
            return [
                {
                    "cmd": "spotify",
                    "id": "synthetic-account",
                    "user": "Synthetic account",
                    "configerror": False,
                }
            ]

        async def async_play_catalogue(self, *_a, is_current, on_send, **_kw):
            assert is_current()
            on_send()
            writes.append("play")

        async def async_seek(self, player, position, *, is_current):
            assert is_current()
            writes.append(("seek", player, position))

    class Environment:
        async def async_observed_change(
            self, commands, metadata, player, send, matches, **_kw
        ):
            await send(lambda: True, lambda: None)
            observed = emit()
            assert matches(observed)
            return observed

    return SimpleNamespace(
        metadata=metadata,
        receiver=receiver,
        target=target,
        commands=Commands(),
        environment=Environment(),
        writes=writes,
        emit=emit,
    )


@pytest.mark.parametrize("spotify", [False, True])
async def test_portable_late_readiness_without_homeassistant(spotify):
    h = await fixture(spotify)
    task = asyncio.create_task(
        async_select_catalogue(
            h.commands,
            h.metadata,
            101,
            h.target,
            is_available=lambda: True,
            source_return=True,
            environment=h.environment,
        )
    )
    try:
        await asyncio.sleep(0)
        assert len(h.metadata._listeners[101]) == 1
        h.emit(pbr=32)
        await asyncio.wait_for(task, 1)
        assert h.writes == ["play", ("seek", 101, 45)]
        assert not h.metadata._listeners
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("spotify", [False, True])
@pytest.mark.parametrize("position", [None, 0, -1, 179, float("nan"), float("inf")])
async def test_invalid_bookmark_does_not_wait_or_seek(spotify, position):
    h = await fixture(spotify, saved_position=position)
    await asyncio.wait_for(
        async_select_catalogue(
            h.commands,
            h.metadata,
            101,
            h.target,
            is_available=lambda: True,
            source_return=True,
            environment=h.environment,
        ),
        0.1,
    )
    assert h.writes == ["play"]
    assert not h.metadata._listeners


@pytest.mark.parametrize("spotify", [False, True])
async def test_missing_bookmark_does_not_wait_or_seek(spotify):
    h = await fixture(spotify, saved_session=False)
    await asyncio.wait_for(
        async_select_catalogue(
            h.commands,
            h.metadata,
            101,
            h.target,
            is_available=lambda: True,
            source_return=True,
            environment=h.environment,
        ),
        0.1,
    )
    assert h.writes == ["play"]
    assert not h.metadata._listeners


@pytest.mark.parametrize("spotify", [False, True])
@pytest.mark.parametrize("change", ["wrong-player", "unavailable", "missing-snapshot"])
async def test_readiness_loses_current_owner_and_never_rearms(spotify, change):
    h = await fixture(spotify)
    available = True
    task = asyncio.create_task(
        async_select_catalogue(
            h.commands,
            h.metadata,
            101,
            h.target,
            is_available=lambda: available,
            source_return=True,
            environment=h.environment,
        )
    )
    try:
        await asyncio.sleep(0)
        assert h.metadata._listeners
        if change == "wrong-player":
            h.receiver._metadata[101] = replace(
                h.metadata.get(101), player_id=999, playback_restrictions=32
            )
        elif change == "unavailable":
            available = False
        else:
            h.receiver._metadata.pop(101)
        h.metadata._on_update(())
        available = True
        h.emit(pbr=32)
        await asyncio.wait_for(task, 1)
        assert h.writes == ["play"]
        assert not h.metadata._listeners
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
