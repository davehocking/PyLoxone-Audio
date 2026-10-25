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
async def test_optional_native_error_after_identity_change_never_permits_retained_fallback():
    original = snapshot()
    metadata = SimpleNamespace(value=original)
    metadata.get = lambda player: metadata.value
    commands = SimpleNamespace(source_fences={}, announcement_fences={})
    failure = selection.NativeSessionUnavailableError('Synthetic optional absence')

    async def attempt(target):
        metadata.value = replace(original, source_name='Different account')
        raise failure

    with pytest.raises(selection.NativeSessionUnavailableError) as caught:
        await selection.async_optional_native_resume(commands, metadata, 7, None, attempt, is_current=lambda: True)
    assert caught.value is failure


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome', ['prewrite-absence', 'uncertain-write', 'cancelled', 'changed-unavailable'])
async def test_optional_native_outcomes_pin_state_and_never_hide_cancellation(outcome):
    original = snapshot()
    metadata = SimpleNamespace(value=original)
    metadata.get = lambda player: metadata.value
    commands = SimpleNamespace(source_fences={}, announcement_fences={})
    failure = selection.NativeSessionUnavailableError('Synthetic optional absence')
    cancellation = asyncio.CancelledError()

    async def attempt(target):
        if outcome == 'cancelled':
            raise cancellation
        if outcome == 'changed-unavailable':
            metadata.value = replace(original, audio_path='spotify:track:external')
            return selection.NativeResumeOutcome.UNAVAILABLE
        if outcome == 'uncertain-write':
            commands.source_fences[7] = object()
        raise failure

    operation = selection.async_optional_native_resume(commands, metadata, 7, None, attempt, is_current=lambda: True)
    if outcome == 'prewrite-absence':
        assert await operation is selection.NativeResumeOutcome.UNAVAILABLE
    else:
        expected = asyncio.CancelledError if outcome == 'cancelled' else selection.AudioCommandError
        with pytest.raises(expected) as caught:
            await operation
        if outcome == 'cancelled':
            assert caught.value is cancellation
        elif outcome == 'uncertain-write':
            assert caught.value is failure


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
        resume_native=AsyncMock(return_value=selection.NativeResumeOutcome.UNAVAILABLE),
        native_is_available=lambda: True, on_target=targets.append,
    )
    assert route.media_id is None and route.original is original
    assert targets == [route.target] and route.target.account == 'owner'
    assert catalogue.source_session('Spotify') is original
    commands.async_recent_sources.assert_not_awaited()
