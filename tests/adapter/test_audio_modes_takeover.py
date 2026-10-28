"""Mode listeners must cover takeover and leave no subscription on failure."""

# ruff: noqa: F811
import asyncio

import pytest
from test_audio_modes_ha import mode_harness, request
from test_audioserver_ha import audio_setup  # noqa: F401
from test_audioserver_playback import rsa_key  # noqa: F401


@pytest.mark.parametrize("operation,value", [("shuffle", True), ("repeat", "one")])
@pytest.mark.parametrize("outcome", ["failure", "cancel"])
async def test_original_validity_listener_covers_takeover_and_cleans_up(
    hass, audio_setup, monkeypatch, rsa_key, operation, value, outcome
):
    h = await mode_harness(hass, audio_setup, monkeypatch, rsa_key)
    entity = h.entities[7]
    before = set(h.metadata._listeners[7])
    entered, release = asyncio.Event(), asyncio.Event()
    during = set()

    async def failed_takeover(self):
        during.update(h.metadata._listeners[7])
        entered.set()
        await release.wait()
        raise RuntimeError("synthetic takeover failure")

    # A failure/cancellation of the real ownership entrypoint is injected here;
    # actual overlapping HA/native socket cleanup is covered by the unchanged
    # independent review94 regressions in test_audio_modes_lifecycle.py.
    monkeypatch.setattr(type(entity), "_async_begin_source_action", failed_takeover)
    task = asyncio.create_task(request(hass, h, 7, operation, value))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        if outcome == "cancel":
            task.cancel()
        else:
            release.set()
        result = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 2)
        expected = asyncio.CancelledError if outcome == "cancel" else RuntimeError
        assert isinstance(result[0], expected)
        assert h.writes == [] and h.sockets == []
        assert set(h.metadata._listeners[7]) == before
        assert before < during, (
            "Original validity must be observed before takeover awaits"
        )
        assert len(during - before) == 1
        assert entity._source_task is None
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
