"""Native grouping state and coordination, independent of Home Assistant."""

from __future__ import annotations
from dataclasses import dataclass, field
import asyncio
import json
import re

_UUID = re.compile(
    r"(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-(?:[0-9a-fA-F]{16}|[0-9a-fA-F]{4}-[0-9a-fA-F]{12}))\Z"
)


def uuid_key(value: object) -> str | None:
    """Validate either native spelling before comparing its 128-bit identity."""
    return (
        value.replace("-", "").lower()
        if isinstance(value, str) and _UUID.fullmatch(value)
        else None
    )


def mean_volume_percent(levels):
    """All-member integer-percent mean, nearest whole percent, half up."""
    if not levels or any(type(v) is not int or not 0 <= v <= 100 for v in levels):
        return None
    return (2 * sum(levels) + len(levels)) // (2 * len(levels))


@dataclass(frozen=True, slots=True)
class AudioPlayerIdentity:
    player_id: int
    control_uuid: str
    server_uuid: str
    fixed: bool = False


@dataclass(frozen=True, slots=True)
class AudioGroupMember:
    player_id: int
    control_uuid: str


@dataclass(frozen=True, slots=True)
class AudioGroup:
    group_id: str
    kind: str
    members: tuple[AudioGroupMember, ...]
    master_volume: float = field(default=0, compare=False)

    @property
    def players(self) -> tuple[int, ...]:
        return tuple(member.player_id for member in self.members)


@dataclass(frozen=True, slots=True)
class AudioGroupSnapshot:
    server_uuid: str
    groups: tuple[AudioGroup, ...]


def group_id_segment(value: object) -> bool:
    """Opaque IDs are retained, but may not inject another native path segment."""
    return (
        isinstance(value, str)
        and value != "new"
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value) is not None
    )


def parse_group_snapshot(value, server_uuid, identities):
    """All-or-unknown complete snapshot; never silently discard bad siblings."""
    import math

    server = uuid_key(server_uuid)
    if server is None or server == "0" * 32:
        return None
    by_player, controls = {}, set()
    for identity in identities:
        control = uuid_key(identity.control_uuid)
        if (
            type(identity.player_id) is not int
            or identity.player_id <= 0
            or identity.player_id in by_player
            or control is None
            or control == "0" * 32
            or control in controls
            or uuid_key(identity.server_uuid) != server
        ):
            return None
        by_player[identity.player_id] = identity
        controls.add(control)
    if isinstance(value, str):
        if len(value) > 512 * 1024:
            return None
        try:
            value = json.loads(value)
        except (ValueError, RecursionError):
            return None
    if not isinstance(value, dict) or not isinstance(
        value.get("audio_sync_event"), list
    ):
        return None
    rows = value["audio_sync_event"]
    if len(rows) > 256:
        return None
    groups, group_ids, occupied = [], set(), {"static": set(), "dynamic": set()}
    for row in rows:
        if not isinstance(row, dict):
            return None
        group_id, kind = row.get("group"), row.get("type")
        volume, players = row.get("mastervolume"), row.get("players")
        if (
            not group_id_segment(group_id)
            or group_id in group_ids
            or kind not in ("static", "dynamic")
            or type(volume) not in (int, float)
            or not isinstance(players, list)
            or not 1 <= len(players) <= 256
        ):
            return None
        try:
            if not math.isfinite(volume):
                return None
        except OverflowError:
            # A valid JSON integer can exceed the finite numeric representation.
            # Reject the complete snapshot, allowing observers to drop authority.
            return None
        members, seen = [], set()
        for member in players:
            if not isinstance(member, dict):
                return None
            player, control = member.get("playerid"), member.get("id")
            if (
                type(player) is not int
                or player not in by_player
                or player in seen
                or player in occupied[kind]
                or uuid_key(control) is None
                or uuid_key(control) != uuid_key(by_player[player].control_uuid)
            ):
                return None
            members.append(AudioGroupMember(player, control))
            seen.add(player)
        occupied[kind].update(seen)
        group_ids.add(group_id)
        groups.append(AudioGroup(group_id, kind, tuple(members), volume))
    return AudioGroupSnapshot(server_uuid, tuple(groups))


def project_group_members(groups, entity_ids):
    """Project complete leader-first rows; supervised Qwen body, independently tested."""
    result = {player: (entity_ids[player],) for player in entity_ids}
    ordered = [group for group in groups if group.kind == "static"]
    ordered += [group for group in groups if group.kind == "dynamic"]
    for group in ordered:
        if all(player in entity_ids for player in group.players):
            membership = tuple(entity_ids[player] for player in group.players)
        else:
            membership = None
        for player in group.players:
            if player in result:
                result[player] = membership
    return result


@dataclass(frozen=True, slots=True)
class GroupUpdate:
    group_id: str | None
    members: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class GroupPlan:
    updates: tuple[GroupUpdate, ...]
    scope: frozenset[int]


def _plan_scope(snapshot, scope, eligible):
    if snapshot is None or not scope <= eligible:
        raise ValueError(
            "Every affected native group member must be available and supported"
        )
    if any(
        group.kind == "static" and scope.intersection(group.players)
        for group in snapshot.groups
    ):
        raise ValueError(
            "Configured fixed audio groups are indivisible and unsupported for mutation"
        )
    return frozenset(scope)


def plan_join(snapshot, target, members, eligible):
    """HA join is additive, not a replacement of its selected target's group."""
    if (
        type(target) is not int
        or not isinstance(members, (tuple, list))
        or any(type(player) is not int or player <= 0 for player in members)
    ):
        raise ValueError("Exact numeric audio players required")
    destination = next(
        (
            group
            for group in snapshot.groups
            if group.kind == "dynamic" and target in group.players
        ),
        None,
    )
    ordered = list(destination.players if destination is not None else (target,))
    for player in members:
        if player not in ordered:
            ordered.append(player)
    scope = set(ordered)
    sources = [
        group
        for group in snapshot.groups
        if group.kind == "dynamic"
        and group is not destination
        and set(members).intersection(group.players)
    ]
    for group in sources:
        scope.update(group.players)
    scope = _plan_scope(snapshot, scope, eligible)
    updates = []
    for group in sources:
        remainder = tuple(player for player in group.players if player not in members)
        updates.append(
            GroupUpdate(group.group_id, remainder if len(remainder) > 1 else ())
        )
    if len(ordered) > 1 and (
        destination is None or tuple(ordered) != destination.players
    ):
        updates.append(
            GroupUpdate(destination.group_id if destination else None, tuple(ordered))
        )
    return GroupPlan(tuple(updates), scope)


def plan_unjoin(snapshot, target, eligible):
    """Detach only this logical player; dissolve an exact pair without replay."""
    if type(target) is not int or target <= 0:
        raise ValueError("Exact numeric audio player required")
    group = next(
        (
            group
            for group in snapshot.groups
            if group.kind == "dynamic" and target in group.players
        ),
        None,
    )
    scope = _plan_scope(snapshot, set(group.players if group else (target,)), eligible)
    if group is None:
        return GroupPlan((), scope)
    remainder = tuple(player for player in group.players if player != target)
    return GroupPlan(
        (GroupUpdate(group.group_id, remainder if len(remainder) > 1 else ()),), scope
    )


class GroupMembershipConflict(ValueError):
    """A valid selection needs explicit permission to leave occupied groups."""


def _plan_exact_create(snapshot, target, members, eligible, override):
    wanted = (target, *members)
    chosen = set(wanted)
    touched = [group for group in snapshot.groups if chosen.intersection(group.players)]
    scope = chosen.union(*(set(group.players) for group in touched))
    scope = _plan_scope(snapshot, scope, eligible)
    if any(group.kind != "dynamic" for group in touched):
        raise ValueError("Only confirmed dynamic groups support transfer")
    if len(touched) == 1 and touched[0].players[0] == target and set(touched[0].players) == chosen:
        return GroupPlan((), scope)
    if touched and not override:
        raise GroupMembershipConflict("Creation requires free rooms unless transfer is explicit")
    updates = []
    for group in touched:
        remainder = tuple(player for player in group.players if player not in chosen)
        updates.append(GroupUpdate(group.group_id, remainder if len(remainder) > 1 else ()))
    updates.append(GroupUpdate(None, wanted))
    return GroupPlan(tuple(updates), scope)


def plan_manage(snapshot, action, target, members, group_id, eligible, *, override_existing_membership=False):
    """Management transfers require explicit intent; ordinary Create/Add refuse."""
    if type(override_existing_membership) is not bool or (override_existing_membership and action not in {"create", "add"}):
        raise ValueError("Membership override is a boolean Create/Add option")
    if snapshot is None or type(target) is not int or not isinstance(members, (list, tuple)) or len(members) > 255 or any(type(p) is not int for p in members):
        raise ValueError("Confirmed registered players required")
    if len(set(members)) != len(members) or target in members:
        raise ValueError("Distinct target and members required")
    group = next((g for g in snapshot.groups if target in g.players and g.kind == "dynamic"), None)
    occupied = {p for g in snapshot.groups for p in g.players}
    if action == "create":
        if group_id is not None or not members:
            raise ValueError("Creation requires at least two free rooms")
        return _plan_exact_create(snapshot, target, members, eligible, override_existing_membership)
    if action == "add":
        if group is None or group.group_id != group_id or not members:
            raise ValueError("Only free rooms may be added to the exact group")
        if override_existing_membership:
            return plan_join(snapshot, target, members, eligible)
        if set(members) & occupied:
            raise GroupMembershipConflict("Only free rooms may be added to the exact group")
        scope = _plan_scope(snapshot, {*group.players, *members}, eligible)
        return GroupPlan((GroupUpdate(group.group_id, (*group.players, *members)),), scope)
    if action == "remove":
        if group is None or group.group_id != group_id or members:
            raise ValueError("Exact member removal required")
        return plan_unjoin(snapshot, target, eligible)
    if action == "destroy":
        if group is None or group.group_id != group_id or members:
            raise ValueError("Exact current group required")
        scope = _plan_scope(snapshot, set(group.players), eligible)
        return GroupPlan((GroupUpdate(group.group_id, ()),), scope)
    raise ValueError("Unsupported management action")


def _group_signature(snapshot):
    return (
        None
        if snapshot is None
        else {group.group_id: (group.kind, group.players) for group in snapshot.groups}
    )


def _matches_transition(before, after, update):
    if after is None:
        return False
    expected = dict(before)
    if update.group_id is not None:
        expected.pop(update.group_id, None)
        if update.members:
            expected[update.group_id] = ("dynamic", update.members)
        return after == expected
    new_ids = set(after) - set(before)
    if len(new_ids) != 1:
        return False
    expected[next(iter(new_ids))] = ("dynamic", update.members)
    return after == expected


class AudioGroupCoordinator:
    """Entry-owned native group state and serial mutation owner."""

    def __init__(
        self, server_uuid, identities, commands, *, eligible, context, timeout=8
    ):
        self.server_uuid, self.identities, self.commands = (
            server_uuid,
            tuple(identities),
            commands,
        )
        self.eligible, self.context, self.timeout = eligible, context, timeout
        self.snapshot = None
        self._changed = asyncio.Event()
        self.uncertain = False
        self._lock = asyncio.Lock()
        self._closed = False
        self._tasks = set()
        self._step = None
        self._conflict = False
        self._scope = frozenset()
        self._context = None
        self._generation = 0
        self._transport_before = None
        self._requests = set()
        self.revision = 0

    def _watch_request(self, scope):
        """Latch published revocation before the first (including lock) await."""
        generation, context = self._generation, self.context()
        valid = True

        def current():
            nonlocal valid
            valid = bool(
                valid and not self._closed and self.snapshot is not None
                and generation == self._generation and context == self.context()
                and scope <= self.eligible()
            )
            return valid

        self._requests.add(current)
        return current

    def observe_current(self):
        """Observe published auth/eligibility without inventing group state.

        Restoration cannot revive queued or active work. Observation remains
        installed until the native operation, including socket cleanup, returns.
        """
        for current in tuple(self._requests):
            current()
        if self._step is not None or self._transport_before is not None:
            self._current()
        self._changed.set()

    def invalidate(self):
        """Drop confirmation at an entry connection/token/identity boundary."""
        self._generation += 1
        self.observe(None)

    def observe(self, value):
        if self._closed:
            return
        snapshot = parse_group_snapshot(value, self.server_uuid, self.identities)
        if _group_signature(snapshot) != _group_signature(self.snapshot):
            self.revision += 1
        self.snapshot = snapshot
        self.uncertain = False
        step = self._step
        if self._transport_before is not None and _group_signature(self.snapshot) != self._transport_before:
            self._conflict = True
        if step is not None:
            signature = _group_signature(self.snapshot)
            if signature != step["before"]:
                if step["sent"] and _matches_transition(
                    step["before"], signature, step["update"]
                ):
                    if step["confirmed"] is not None and step["confirmed"] != signature:
                        self._conflict = True
                    step["confirmed"] = signature
                else:
                    self._conflict = True
            elif step["confirmed"] is not None:
                self._conflict = True
        self.observe_current()

    def _current(self):
        self._conflict = bool(
            self._conflict
            or self.snapshot is None
            or self.context() != self._context
            or not self._scope <= self.eligible()
        )
        return not self._conflict

    def _sent(self):
        self._step["sent"] = True
        self._changed.clear()

    async def async_unjoin(self, target):
        await self._async_operation(
            lambda: plan_unjoin(self.snapshot, target, self.eligible())
        )

    async def async_transport(self, target, action, reserve, *, prepare=None):
        """Serialize transport with mutations; reserve all participants until cleanup."""
        await self._async_transport(target, action, reserve, room_only=False, prepare=prepare)

    async def async_room_transport(self, target, action, reserve):
        """Serialize an exact room with group operations, reserving only that room."""
        await self._async_transport(target, action, reserve, room_only=True)

    async def _async_transport(self, target, action, reserve, *, room_only, prepare=None):
        from .native import AudioCommandError

        if action not in ("play", "pause") or type(target) is not int or not 0 < target <= 2**31 - 1:
            raise ValueError("Transport requires an exact player and play/pause action")
        task = asyncio.current_task()
        generation, context = self._generation, self.context()
        before = _group_signature(self.snapshot)
        initial_group = next(
            (g for g in self.snapshot.groups if target in g.players and g.kind == "dynamic"),
            None,
        ) if self.snapshot is not None else None
        request_current = self._watch_request(
            frozenset(initial_group.players if initial_group and not room_only else (target,))
        )
        self._tasks.add(task)
        cleanup = None
        sent = completed = acquired = False
        def on_send():
            nonlocal sent
            sent = True
        try:
            async with asyncio.timeout(self.timeout) as deadline, self._lock:
                if (
                    not request_current() or self._closed or self.snapshot is None or self.uncertain
                    or generation != self._generation or context != self.context()
                    or before != _group_signature(self.snapshot)
                ):
                    raise AudioCommandError("Native grouping state is unknown or superseded")
                group = next((g for g in self.snapshot.groups if target in g.players and g.kind == "dynamic"), None)
                if room_only:
                    players = (target,)
                elif group is None or len(group.players) < 2:
                    raise AudioCommandError("Confirmed supported dynamic group required")
                else:
                    players = group.players
                scope = _plan_scope(self.snapshot, set(players), self.eligible())
                self._conflict, self._scope, self._context = False, scope, context
                acquired = True
                self._transport_before = before
                current, cleanup = reserve(players)
                def applicable():
                    return request_current() and self._current() and current() and generation == self._generation
                if not applicable():
                    raise AudioCommandError("Grouped transport is unavailable")
                if prepare is not None:
                    # Keep the original lock-wait bound. Serial qualification
                    # gets one bounded request (including cleanup) per member,
                    # then transmission gets its own original bound. A party
                    # must not spend its command budget closing status sockets.
                    if action == "play":
                        deadline.reschedule(asyncio.get_running_loop().time() + self.timeout * len(players))
                    await prepare(players, applicable)
                    if not applicable():
                        raise AudioCommandError("Grouped pre-command qualification was superseded")
                    if action == "play":
                        deadline.reschedule(asyncio.get_running_loop().time() + self.timeout)
                if room_only:
                    await self.commands.async_execute(target, action, is_current=applicable, on_send=on_send, guard_cleanup=True)
                else:
                    await self.commands.async_group_transport(players, action, is_current=applicable, on_send=on_send)
                if not applicable():
                    raise AudioCommandError("Grouped transport was superseded")
                completed = True
        except TimeoutError:
            raise AudioCommandError("Grouped transport expired without retry") from None
        finally:
            if sent and not completed:
                # Playback cannot change membership. Revoke captured/queued
                # work, but retain the authoritative topology after an honest
                # playback failure. Never clear genuine topology uncertainty.
                self._generation += 1
            if cleanup is not None:
                cleanup()
            if acquired:
                self._transport_before = None
                self._scope = frozenset()
            self._requests.discard(request_current)
            self._tasks.discard(task)

    async def async_volume(self, target, percent, read, send, *, room_only=False, qualified=lambda: True):
        """Serialize Miniserver volume sends; only actual room feedback confirms."""
        from .native import AudioCommandError

        if type(percent) is not int or not 0 <= percent <= 100:
            raise ValueError("Integer volume percentage required")
        before = _group_signature(self.snapshot)
        group = next((g for g in self.snapshot.groups if g.kind == "dynamic" and target in g.players), None) if self.snapshot else None
        players = group.players if group is not None and not room_only else (target,)
        initial = {p: read(p) for p in players}
        mean = mean_volume_percent(list(initial.values()))
        if mean is None:
            raise AudioCommandError("Every member needs current room volume feedback")
        delta = percent - mean
        targets = {p: max(0, min(100, v + delta)) for p, v in initial.items()}
        request_current = self._watch_request(frozenset(players))
        task = asyncio.current_task()
        self._tasks.add(task)
        sent_targets, confirmed = {}, set()
        valid, sent, completed, acquired = True, False, False, False

        def current():
            nonlocal valid
            valid = bool(valid and request_current() and qualified()
                         and not self.uncertain and before == _group_signature(self.snapshot)
                         and all(read(p) in ({targets[p]} if p in confirmed else {initial[p], sent_targets.get(p, initial[p])}) for p in players))
            return valid

        self._requests.add(current)
        try:
            async with asyncio.timeout(self.timeout) as deadline, self._lock:
                if not current():
                    raise AudioCommandError("Volume request superseded")
                self._scope, self._context, self._conflict = frozenset(players), self.context(), False
                self._transport_before = before
                acquired = True
                for player in players:
                    if not current() or not self._current():
                        raise AudioCommandError("Partial volume request superseded; no rollback")
                    if targets[player] == initial[player]:
                        continue
                    # Each serial send/feedback pair retains the original8s
                    # bound. Unrelated feedback cannot renew a stalled member.
                    if not room_only:
                        deadline.reschedule(asyncio.get_running_loop().time() + self.timeout)
                    sent_targets[player] = targets[player]
                    sent = True
                    send(player, targets[player])
                    while True:
                        if not current() or not self._current():
                            raise AudioCommandError("Partial volume request superseded; no rollback")
                        if read(player) == targets[player]:
                            confirmed.add(player)
                            break
                        self._changed.clear()
                        await self._changed.wait()
                completed = True
        except TimeoutError:
            raise AudioCommandError("Volume feedback unconfirmed; partial sends not retried or undone") from None
        finally:
            if sent and not completed:
                # A volume write cannot change membership. Keep its failure
                # truthful and revoke already-captured work, but do not poison
                # authoritative topology (or invent room-volume feedback).
                # Genuine topology/transport uncertainty is never cleared here.
                self._generation += 1
            if acquired:
                self._scope = frozenset()
                self._transport_before = None
            self._requests.discard(current)
            self._requests.discard(request_current)
            self._tasks.discard(task)

    async def async_join(self, target, members):
        await self._async_operation(
            lambda: plan_join(self.snapshot, target, members, self.eligible())
        )

    async def _async_operation(self, planner):
        from .native import AudioCommandError

        task = asyncio.current_task()
        generation, context = self._generation, self.context()
        # Still replan under the lock; retain initial affected eligibility while
        # queued, then let _current fence the complete replanned active scope.
        scope = planner().scope if self.snapshot is not None else frozenset()
        request_current = self._watch_request(scope)
        self._tasks.add(task)
        try:
            async with asyncio.timeout(self.timeout), self._lock:
                if (
                    not request_current()
                    or self._closed
                    or self.snapshot is None
                    or self.uncertain
                    or generation != self._generation
                    or context != self.context()
                ):
                    raise AudioCommandError("Native grouping state is unknown")
                await self._async_apply(planner())
        except TimeoutError:
            raise AudioCommandError(
                "Native group operation expired without automatic retry"
            ) from None
        finally:
            self._requests.discard(request_current)
            self._tasks.discard(task)

    async def _async_apply(self, plan):
        from .native import AudioCommandError

        self._conflict, self._scope, self._context = False, plan.scope, self.context()
        completed = False
        try:
            async with asyncio.timeout(self.timeout):
                for update in plan.updates:
                    if not self._current():
                        raise AudioCommandError(
                            "Native grouping was superseded; no automatic rollback was sent"
                        )
                    before = _group_signature(self.snapshot)
                    self._step = {
                        "before": before,
                        "update": update,
                        "sent": False,
                        "confirmed": None,
                    }
                    reply = await self.commands.async_update_group(
                        update.group_id,
                        update.members,
                        is_current=self._current,
                        on_send=self._sent,
                    )
                    expected = dict(before)
                    if update.group_id is not None:
                        expected.pop(update.group_id, None)
                    if update.members:
                        expected[reply] = ("dynamic", update.members)
                    while True:
                        if not self._current():
                            raise AudioCommandError(
                                "Native grouping was superseded; no automatic rollback was sent"
                            )
                        if self._step["confirmed"] == expected:
                            break
                        self._changed.clear()
                        await self._changed.wait()
                completed = True
        except TimeoutError:
            raise AudioCommandError(
                "Native group update is unconfirmed; no retry or replay was sent"
            ) from None
        finally:
            if not completed and self._step is not None and self._step["sent"]:
                self.uncertain = True
                self._generation += 1
            self._step = None
            self._scope = frozenset()

    async def async_close(self):
        self._closed = True
        self.snapshot = None
        self._conflict = True
        self._changed.set()
        tasks = [task for task in self._tasks if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
