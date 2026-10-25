"""Distinguish live dispatch eligibility from terminal no-replay reconciliation."""
# Literal player IDs and evidence assertions belong in this synthetic lifecycle test.
# ruff: noqa: S101, INP001, SLF001, PLR2004
from __future__ import annotations

import asyncio
from collections.abc import Callable
from types import SimpleNamespace

import pytest
from test_audio_sources import Metadata

from custom_components.loxone import audio_sources
from custom_components.loxone.pyloxone_api.audioserver import AudioCommandError


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["cancel", "transport"])
async def test_terminal_feedback_can_settle_but_never_resurrect_a_stale_waiter(outcome: str) -> None:
    """Preterminal matching frames stay ineligible; only new terminal proof releases."""
    metadata = Metadata()
    commands = SimpleNamespace(source_fences={}, announcement_fences={})
    entered = asyncio.Event()
    result = asyncio.get_running_loop().create_future()
    available = True
    sends = []

    async def send(guard: Callable[[], bool], on_send: Callable[[], None]) -> None:
        assert guard()
        on_send()
        sends.append("source")
        entered.set()
        await result

    task = asyncio.create_task(audio_sources._async_observed_change(
        commands, metadata, 7, send,
        lambda sample: sample.audio_path == "tunein:station:synthetic",
        is_available=lambda: available,
    ))
    try:
        await asyncio.wait_for(entered.wait(), 0.5)
        available = False
        metadata.set({"audiopath": "tunein:station:synthetic", "mode": "play"})
        assert 7 in commands.source_fences
        assert not task.done()
        if outcome == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            result.set_exception(AudioCommandError("Synthetic uncertain write"))
            with pytest.raises(AudioCommandError):
                await task
        for callback in tuple(metadata.listeners):
            callback()
        assert 7 in commands.source_fences
        metadata.set({"audiopath": "tunein:station:foreign", "mode": "play"})
        assert 7 in commands.source_fences
        metadata.set({"audiopath": "tunein:station:synthetic", "mode": "play"})
        assert not commands.source_fences
        assert not metadata.listeners
        assert sends == ["source"]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for release in tuple(commands.source_fences.values()):
            release()
