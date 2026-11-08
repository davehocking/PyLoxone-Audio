"""Serial grouping owner: native feedback is distinct from command acknowledgement."""

import asyncio
import pytest
from pyloxone_audio import grouping as g
from pyloxone_audio.native import AudioCommandError
from test_audio_grouping import SERVER, identities, payload, row


class Sender:
    def __init__(self):
        self.calls = []
        self.owner = None
        self.mode = "confirm"
        self.sent = asyncio.Event()
        self.release = asyncio.Event()

    async def async_update_group(self, group, members, *, is_current, on_send):
        if not is_current():
            raise AudioCommandError("superseded")
        on_send()
        self.calls.append((group, members))
        self.sent.set()
        before = self.owner.snapshot
        if self.mode == "held":
            await self.release.wait()
        if self.mode == "reject":
            raise AudioCommandError("rejected")
        if self.mode in ("confirm", "held"):
            rows = [
                row(x.group_id, x.players, x.kind)
                for x in before.groups
                if x.group_id != group
            ]
            if members:
                rows.append(row(group or "created", members))
            self.owner.observe(payload(*rows))
        return group or "created"


def owner(sender=None, timeout=0.1):
    sender = sender or Sender()
    eligible = {1, 2, 3, 4, 5, 6}
    context = ["session-a"]
    c = g.AudioGroupCoordinator(
        SERVER,
        identities(),
        sender,
        eligible=lambda: frozenset(eligible),
        context=lambda: tuple(context),
        timeout=timeout,
    )
    sender.owner = c
    return c, sender, eligible, context


async def test_unknown_then_explicit_empty_then_join_requires_confirmed_feedback():
    c, s, _, _ = owner()
    assert c.snapshot is None
    with pytest.raises(AudioCommandError):
        await c.async_join(1, (2,))
    assert s.calls == []
    c.observe(payload())
    await c.async_join(1, (2,))
    assert s.calls == [(None, (1, 2))]
    assert c.snapshot.groups[0].players == (1, 2)
    await c.async_join(1, (2,))
    assert len(s.calls) == 1
    await c.async_close()


async def test_ack_only_times_out_without_optimistic_members_or_retry():
    c, s, _, _ = owner()
    c.observe(payload())
    s.mode = "ack"
    with pytest.raises(AudioCommandError):
        await c.async_join(1, (2,))
    assert c.snapshot.groups == ()
    assert s.calls == [(None, (1, 2))]
    # A second service invocation is not a readback of an uncertain write.
    with pytest.raises(AudioCommandError):
        await c.async_join(1, (3,))
    assert s.calls == [(None, (1, 2))]
    await c.async_close()


@pytest.mark.parametrize(
    "conflict", ["malformed", "external", "reverted", "session", "availability"]
)
async def test_intervening_conflict_never_revives_when_expected_frame_arrives(conflict):
    c, s, eligible, context = owner(timeout=0.5)
    c.observe(payload())
    s.mode = "held"
    task = asyncio.create_task(c.async_join(1, (2,)))
    try:
        await asyncio.wait_for(s.sent.wait(), 0.2)
        if conflict == "malformed":
            c.observe("{}")
        elif conflict in ("external", "reverted"):
            c.observe(payload(row("outside", (3, 4))))
            if conflict == "reverted":
                c.observe(payload())
        elif conflict == "session":
            context[0] = "session-b"
        else:
            eligible.remove(2)
        s.release.set()
        with pytest.raises(AudioCommandError):
            await task
        assert s.calls == [(None, (1, 2))]
    finally:
        s.release.set()
        await asyncio.gather(task, return_exceptions=True)
        await c.async_close()


async def test_concurrent_additive_joins_serialize_and_replan_after_confirmation():
    c, s, _, _ = owner(timeout=0.5)
    c.observe(payload())
    s.mode = "held"
    first = asyncio.create_task(c.async_join(1, (2,)))
    second = None
    try:
        await asyncio.wait_for(s.sent.wait(), 0.2)
        second = asyncio.create_task(c.async_join(1, (3,)))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert s.calls == [(None, (1, 2))]
        s.release.set()
        await asyncio.gather(first, second)
        assert s.calls == [(None, (1, 2)), ("created", (1, 2, 3))]
        assert c.snapshot.groups[0].players == (1, 2, 3)
    finally:
        s.release.set()
        await asyncio.gather(
            first, *([second] if second else []), return_exceptions=True
        )
        await c.async_close()


async def test_parallel_dialog_removals_replan_from_confirmed_serial_state():
    c, s, _, _ = owner()
    c.observe(payload(row("old", (1, 2, 3))))
    await asyncio.gather(c.async_unjoin(2), c.async_unjoin(3))
    assert s.calls == [("old", (1, 3)), ("old", ())]
    assert c.snapshot.groups == ()
    await c.async_unjoin(1)
    assert len(s.calls) == 2
    await c.async_close()


async def test_move_confirms_source_before_destination_and_keeps_outside_groups():
    c, s, _, _ = owner()
    c.observe(payload(row("dest", (1, 2)), row("src", (3, 4)), row("outside", (5, 6))))
    await c.async_join(2, (3,))
    assert s.calls == [("src", ()), ("dest", (1, 2, 3))]
    assert {x.group_id: x.players for x in c.snapshot.groups} == {
        "dest": (1, 2, 3),
        "outside": (5, 6),
    }
    await c.async_close()


async def test_close_cancels_owned_work_and_cannot_rearm_from_late_state():
    c, s, _, _ = owner(timeout=0.5)
    c.observe(payload())
    s.mode = "held"
    task = asyncio.create_task(c.async_join(1, (2,)))
    try:
        await asyncio.wait_for(s.sent.wait(), 0.2)
        await c.async_close()
        assert task.done()
        assert c.snapshot is None
        c.observe(payload())
        with pytest.raises(AudioCommandError):
            await c.async_join(1, (3,))
        assert len(s.calls) == 1
    finally:
        s.release.set()
        await asyncio.gather(task, return_exceptions=True)
        await c.async_close()


async def test_queued_operation_cannot_cross_reconnect_even_after_fresh_state():
    c, s, _, _ = owner(timeout=0.5)
    c.observe(payload())
    s.mode = "held"
    first = asyncio.create_task(c.async_join(1, (2,)))
    second = None
    try:
        await asyncio.wait_for(s.sent.wait(), 0.2)
        second = asyncio.create_task(c.async_join(1, (3,)))
        await asyncio.sleep(0)
        c.invalidate()
        c.observe(payload())
        s.release.set()
        results = await asyncio.gather(first, second, return_exceptions=True)
        assert all(isinstance(result, AudioCommandError) for result in results)
        assert s.calls == [(None, (1, 2))]
    finally:
        s.release.set()
        await asyncio.gather(
            first, *([second] if second else []), return_exceptions=True
        )
        await c.async_close()
