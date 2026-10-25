"""Concurrent consumers in the SAME module/interpreter; no process isolation."""
import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pyloxone_audio.clock import utcnow

from pyloxone_audio.sources import SourceEnvironment
from pyloxone_audio.sources import async_select_catalogue
from pyloxone_audio.catalogue import CatalogueTarget
from pyloxone_audio.native import AudioCommandError
from test_boundary_qualification import snapshot


class Observations:
    def __init__(self, value):
        self.value = value
        self.listeners = []

    def get(self, _player):
        return self.value

    def async_add_listener(self, _player, listener):
        self.listeners.append(listener)
        def remove():
            if listener in self.listeners:
                self.listeners.remove(listener)
        return remove

    def publish(self, value):
        self.value = value
        for listener in tuple(self.listeners):
            listener()


def commands():
    return SimpleNamespace(source_fences={}, announcement_fences={}, source_observations={})


@pytest.mark.asyncio
async def test_two_simultaneous_source_clocks_are_isolated_from_each_other_and_default():
    ready = [asyncio.Event() for _ in range(3)]
    observed = []
    before = utcnow()

    async def consumer(index, year):
        now = datetime(year, 1, 1, tzinfo=UTC) if year else utcnow()
        environment = SourceEnvironment(clock=lambda: now) if year else SourceEnvironment()
        metadata = Observations(replace(snapshot(), received_at=now, native_mode='stop'))
        owner = commands()

        async def send(guard, sent):
            nonlocal now
            assert guard()
            sent()
            ready[index].set()
            await asyncio.gather(*(event.wait() for event in ready))
            observed_at = now + timedelta(seconds=1) if year else utcnow()
            metadata.publish(replace(metadata.value, native_mode='play', received_at=observed_at))
            # Advancing this consumer's clock must not rebase the other operation.
            now += timedelta(seconds=2)

        try:
            result = await environment.async_observed_change(
                owner, metadata, 7, send, lambda row: row.audio_path == 'spotify:track:synthetic',
                is_available=lambda: True, allow_noop=False, timeout=0.05,
            )
            observed.append(result)
        finally:
            for release in tuple(owner.source_fences.values()):
                release()
            assert not metadata.listeners and not owner.source_observations

    results = await asyncio.gather(consumer(0, 2020), consumer(1, 2040), consumer(2, None), return_exceptions=True)
    assert results == [None, None, None]
    assert sorted(row.received_at.year for row in observed) == sorted([2020, 2040, before.year])
    assert before <= utcnow() and SourceEnvironment().clock().tzinfo is UTC


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome', ['ack', 'reject', 'cancelled'])
async def test_optional_restore_collects_actual_suboperation_without_progress_gate(outcome):
    saved = replace(snapshot(), source='Local Library', audio_path='library:local:track:synthetic')
    metadata = Observations(replace(saved, source='TuneIn', audio_path='tunein:station:synthetic'))
    owner = commands()
    calls = []
    cancellation = asyncio.CancelledError()

    async def play(player, service, account, folder, *, is_current, on_send):
        assert is_current()
        on_send()
        metadata.publish(replace(saved, position=0, received_at=utcnow()))

    async def seek(player, seconds, *, is_current):
        assert is_current()
        calls.append(seconds)
        if outcome == 'cancelled':
            raise cancellation
        if outcome == 'reject':
            raise AudioCommandError('Synthetic optional position rejection')
        return seconds  # Ordinary echo ONLY: no position/progress frame is supplied.

    owner.async_play_catalogue = play
    owner.async_seek = seek
    target = CatalogueTarget('item', 'Local Library', 'library', folder=saved.audio_path,
                             audio_path=saved.audio_path, return_session=saved)

    async def select():
        await async_select_catalogue(owner, metadata, 7, target, source_return=True, is_available=lambda: True)

    if outcome == 'cancelled':
        with pytest.raises(asyncio.CancelledError) as caught:
            await select()
        assert caught.value is cancellation
    else:
        await select()
    assert calls == [saved.position] and metadata.value.position == 0

    assert not metadata.listeners and not owner.source_fences and not owner.source_observations


@pytest.mark.asyncio
async def test_cancelling_before_send_cleans_only_its_operation_configuration():
    ready = asyncio.Event()
    now = datetime(2040, 1, 1, tzinfo=UTC)
    metadata = Observations(replace(snapshot(), received_at=now))
    owner = commands()


    async def send(guard, sent):
        assert guard()
        ready.set()
        await asyncio.Event().wait()  # No send; cancellation must release the fence.

    async def action():
        await SourceEnvironment(clock=lambda: now).async_observed_change(
            owner, metadata, 7, send, lambda row: True,
            is_available=lambda: True, allow_noop=False,
        )

    task = asyncio.create_task(action())
    await ready.wait()
    task.cancel()
    result = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(result[0], asyncio.CancelledError)
    assert not metadata.listeners and not owner.source_observations and not owner.source_fences

    assert SourceEnvironment().clock().year == utcnow().year



