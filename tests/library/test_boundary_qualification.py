"""Concrete reusable qualification with HA imports actively rejected."""
import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest

from pyloxone_audio import sources
from pyloxone_audio import selection
from pyloxone_audio.catalogue import AudioCatalogue, ConfiguredSource
from pyloxone_audio.native import parse_audio_events


def snapshot(**changes):
    row = parse_audio_events({'audio_event': [{
        'playerid': 7, 'mode': 'play', 'audiopath': 'spotify:track:synthetic',
        'sourceName': 'Synthetic owner', 'time': 20, 'duration': 180, 'pbr': 32,
    }]})[0]
    return replace(row, received_at=datetime(2026, 10, 25, tzinfo=UTC), **changes)


def test_two_ordered_same_native_samples_qualify_passive_history():
    first = snapshot()
    second = replace(first, position=21, received_at=first.received_at + timedelta(seconds=1))
    assert sources.passive_history_eligible(second, first, settled=True, initial_generation=False)


def test_manual_seek_requires_explicit_track_capability():
    assert selection.manual_seek_supported(snapshot())
    assert not selection.manual_seek_supported(snapshot(playback_restrictions=0))


def test_confirmed_library_selection_does_not_inherit_unrelated_provider_uncertainty():
    library = snapshot(source='Local Library', audio_path='library:track:synthetic')
    assert selection.confirmed_library_session(library, library)
    assert not selection.confirmed_library_session(replace(library, event_active=True), library)
    assert not selection.confirmed_library_session(replace(library, audio_path='other'), library)


def test_manual_seek_rechecks_actual_snapshot_not_only_cached_host_identity():
    original = snapshot()
    identity = selection.native_track_identity(original)
    proof = selection.ManualSeekQualification(original, identity, 1, original.duration)
    changed = replace(original, audio_path='spotify:track:different')
    assert not proof.is_current(changed, identity=identity, revision=1, duration=original.duration, enabled=True)






@pytest.mark.asyncio
async def test_native_session_route_avoids_unavailable_optional_history():
    original = snapshot()
    commands = SimpleNamespace(
        source_fences={}, announcement_fences={},
        async_service_accounts=AsyncMock(return_value=[{
            'cmd': 'spotify', 'id': 'owner', 'user': 'Synthetic owner', 'configerror': False,
        }]),
        async_recent_sources=AsyncMock(side_effect=ValueError('Synthetic optional history loss')),
    )
    catalogue = AudioCatalogue(commands, 7)
    catalogue.source_descriptors = {'Spotify': ConfiguredSource('spotify', 'owner')}
    catalogue._source_accounts = commands.async_service_accounts.return_value
    targets = []
    route = await selection.async_source_route(
        commands, SimpleNamespace(get=lambda _: original), catalogue, 7, 'Spotify',
        is_current=lambda: True, ensure_snapshot=AsyncMock(),

        native_is_available=lambda: True, on_target=targets.append,
    )
    assert route.media_id is None and route.original is original
    assert targets == [route.target] and route.target.account == 'owner'
    assert catalogue.source_session('Spotify') is original
    commands.async_recent_sources.assert_not_awaited()
