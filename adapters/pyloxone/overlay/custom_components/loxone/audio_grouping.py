"""Existing-entry adapter for shared native group state (no transport ownership)."""

from pyloxone_audio.grouping import (
    AudioGroupCoordinator,
    GroupMembershipConflict,
    AudioPlayerIdentity,
    parse_group_snapshot,
    project_group_members,
    uuid_key,
    mean_volume_percent,
    plan_manage,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from pyloxone_audio.native import AudioCommandError
from .const import DOMAIN, SENDDOMAIN
import asyncio


def grouping_binding(structure):
    """A single modern server and an unambiguous existing-room inventory only."""
    if not isinstance(structure, dict) or not isinstance(
        structure.get("controls"), dict
    ):
        return None
    servers = structure.get("mediaServer")
    if not isinstance(servers, dict) or len(servers) != 1:
        return None
    server, details = next(iter(servers.items()))
    if (
        not isinstance(details, dict)
        or type(details.get("type")) is not int
        or details["type"] != 2
    ):
        return None
    states = details.get("states")
    if not isinstance(states, dict):
        return None
    state = states.get("grouping")
    if (
        uuid_key(state) in (None, "0" * 32)
        or uuid_key(server) in (None, "0" * 32)
        or uuid_key(state) == uuid_key(server)
        or uuid_key(details.get("uuidAction", server)) != uuid_key(server)
    ):
        return None
    identities = []
    for key, control in structure["controls"].items():
        if not isinstance(control, dict) or not isinstance(control.get("type"), str):
            return None
        if control["type"] != "AudioZoneV2":
            continue
        if uuid_key(key) != uuid_key(control.get("uuidAction")) or uuid_key(
            key
        ) == uuid_key(state):
            return None
        values = control.get("details")
        if not isinstance(values, dict) or uuid_key(values.get("server")) != uuid_key(
            server
        ):
            return None
        fixed = bool(values.get("groupObjects")) or values.get("playerGroup") not in (
            None,
            "00000000-0000-0000-0000000000000000",
            "00000000-0000-0000-0000-000000000000",
        )
        identities.append(
            AudioPlayerIdentity(
                values.get("playerid"), control.get("uuidAction"), server, fixed
            )
        )
    identities = tuple(identities)
    if (
        not identities
        or parse_group_snapshot({"audio_sync_event": []}, server, identities) is None
    ):
        return None
    return server, state, identities


class AudioGroupingOwner:
    """One owner per existing entry; entities register actual HA identities."""

    def __init__(self, coordinator, binding, commands):
        self.host = coordinator
        self.binding = binding
        self.disabled = False
        self.entities = {}
        self._membership = {}
        self._registry_generation = 0
        self._transport_task = None
        self.native = AudioGroupCoordinator(
            binding[0],
            binding[2],
            commands,
            eligible=self.eligible,
            context=self.context,
        )

    def context(self):
        """Fence queued/authenticating work against token, topology and registration."""
        return (
            self.host.api.get_token_dict().get("token"),
            self._registry_generation,
            grouping_binding(
                getattr(
                    self.host.api,
                    "structure_file",
                    self.host.miniserver.lox_config.json,
                )
            ),
            tuple(
                (
                    p,
                    e.entity_id,
                    (r.platform, r.config_entry_id, r.unique_id, r.disabled_by)
                    if r
                    else None,
                )
                for p, e in self.entities.items()
                for r in (er.async_get(self.host.hass).async_get(e.entity_id),)
            ),
        )

    @classmethod
    def create(cls, coordinator, structure, commands):
        binding = grouping_binding(structure)
        return (
            cls(coordinator, binding, commands)
            if commands is not None and binding is not None
            else None
        )

    def register(self, entity):
        self._registry_generation += 1
        self.entities[entity._audio_player_id] = entity
        self.notify()

    def unregister(self, entity):
        if self.entities.get(entity._audio_player_id) is entity:
            self._registry_generation += 1
            self.entities.pop(entity._audio_player_id)
        self.notify()

    def eligible(self, *, pause_target=None):
        if self.disabled or self.native.snapshot is None or self.native.uncertain or grouping_binding(getattr(self.host.api, "structure_file", self.host.miniserver.lox_config.json)) != self.binding:
            return frozenset()
        fixed = {identity.player_id for identity in self.binding[2] if identity.fixed}
        fixed.update(
            player
            for group in self.native.snapshot.groups
            if group.kind == "static"
            for player in group.players
        )
        identities = {identity.player_id: identity for identity in self.binding[2]}
        registry = er.async_get(self.host.hass)
        return frozenset(
            player
            for player, entity in self.entities.items()
            for record in (registry.async_get(entity.entity_id),)
            if player not in fixed
            and entity.available
            and not entity._audio_removed
            and record is not None
            and record.platform == DOMAIN
            and record.config_entry_id == self.host.config_entry.entry_id
            and record.unique_id == entity.unique_id
            and record.disabled_by is None
            and player in identities
            and uuid_key(entity.uuidAction) == uuid_key(identities[player].control_uuid)
            and entity._audio_commands is self.native.commands
            and entity._audio_commands_enabled
            and (entity._source_task is None or player == pause_target)
            and entity._announcement_task is None
            and (player == pause_target or not (entity._transport_tasks - {self._transport_task}))
            and (
                player not in self.native.commands.source_fences
                or (
                    player == pause_target
                    and entity._source_task is not None
                    and not entity._source_task.done()
                    and self.native.commands.source_fence_owners.get(player)
                    == (self.native.commands.source_fences[player], entity._source_task)
                )
            )
            and player not in self.native.commands.announcement_fences
        )

    def members(self, player):
        if player not in self.eligible():
            return None
        ids = {
            p: entity.entity_id
            for p, entity in self.entities.items()
            if p in self.eligible()
        }
        return project_group_members(self.native.snapshot.groups, ids).get(player)

    def control_descriptor(self, player):
        """Optional UI projection; eligibility is still enforced on every service."""
        from hashlib import sha256
        members = self.members(player)
        if members is None:
            return None
        candidates = [e.entity_id for p, e in self.entities.items() if self.members(p) is not None]
        group = next((g for g in self.native.snapshot.groups if player in g.players and g.kind == "dynamic"), None)
        signature = tuple((g.group_id, g.kind, g.players) for g in self.native.snapshot.groups)
        return {
            "version": 2,
            "owner": sha256(repr((self.host.config_entry.entry_id, self.binding[0])).encode()).hexdigest(),
            "revision": sha256(repr((signature, self.native.revision, self.context(), candidates)).encode()).hexdigest(),
            "members": list(members),
            "candidates": candidates,
            "group_id": group.group_id if group is not None else None,
            "busy": bool(self.native._scope),
        }

    def independent(self, player):
        """Enhanced playback/announcement ownership is only proven for single rooms."""
        return bool(
            not self.disabled
            and self.native.snapshot is not None
            and not self.native.uncertain
            and player not in self.native._scope
            and any(i.player_id == player and not i.fixed for i in self.binding[2])
            and not any(
                player in group.players
                and (group.kind == "static" or len(group.players) > 1)
                for group in self.native.snapshot.groups
            )
        )

    def watch_source_context(self):
        """Latch an initiating source action's auth/registration context, including ABA."""
        before = self.context()
        valid = True
        def current():
            nonlocal valid
            valid = bool(valid and not self.disabled and not self.native._closed and self.context() == before)
            return valid
        self.native._requests.add(current)
        return current, lambda: self.native._requests.discard(current)

    def media_source_leader(self, player):
        """Only an independent player or its confirmed dynamic group's leader."""
        if self.independent(player):
            return True
        if self.disabled or self.native._closed or self.native.snapshot is None or self.native.uncertain:
            return False
        group = next((g for g in self.native.snapshot.groups if player in g.players), None)
        return bool(
            group is not None and group.kind == "dynamic" and group.players[0] == player
            and not (set(group.players) & self.native._scope)
            and set(group.players) <= self.eligible(pause_target=player)
        )

    def mode_target(self, player):
        """Resolve modes only to a confirmed, eligible native playback owner."""
        if self.disabled or self.native._closed or self.native.snapshot is None or self.native.uncertain:
            return None
        group = next((g for g in self.native.snapshot.groups if player in g.players), None)
        if group is not None and group.kind != "dynamic":
            return None
        players = group.players if group is not None else (player,)
        target = players[0]
        if set(players) & self.native._scope or not set(players) <= self.eligible(pause_target=target):
            return None
        return self.entities.get(target)

    def watch_mode_context(self, player):
        """Latch membership, identity and authentication before a mode's first await."""
        target, context = self.mode_target(player), self.context()
        def membership():
            return tuple((g.group_id, g.kind, g.players) for g in self.native.snapshot.groups
                         if player in g.players) if self.native.snapshot is not None else None
        before = membership()
        valid = target is not None
        def current():
            nonlocal valid
            valid = bool(valid and self.mode_target(player) is target
                         and self.context() == context and membership() == before)
            return valid
        self.native._requests.add(current)
        remove_registry = self.host.hass.bus.async_listen(
            er.EVENT_ENTITY_REGISTRY_UPDATED, lambda _event: current(),
        )
        def remove():
            self.native._requests.discard(current)
            remove_registry()
        return current, remove

    def volume_level(self, player):
        """Public grouped player volume is the complete confirmed-room mean."""
        group = next((g for g in self.native.snapshot.groups
                      if g.kind == "dynamic" and player in g.players and len(g.players) > 1), None) if self.native.snapshot else None
        if group is None:
            return self.entities[player]._volume
        if self.members(player) is None:
            return None
        mean = mean_volume_percent([self.entities[p]._room_volume_percent for p in group.players])
        return mean / 100 if mean is not None else None

    def _resolve(self, entity_id, *, room_only=False, pause_takeover=False):
        entity = next(
            (e for e in self.entities.values() if e.entity_id == entity_id), None
        )
        registry = er.async_get(self.host.hass).async_get(entity_id)
        identity = next(
            (
                i
                for i in self.binding[2]
                if entity is not None and i.player_id == entity._audio_player_id
            ),
            None,
        )
        if (
            entity is None
            or registry is None
            or identity is None
            or registry.platform != DOMAIN
            or registry.config_entry_id != self.host.config_entry.entry_id
            or registry.unique_id != entity.unique_id
            or uuid_key(entity.uuidAction) != uuid_key(identity.control_uuid)
            or entity._audio_commands is not self.native.commands
            or not entity._audio_commands_enabled
            or (identity.player_id not in self.eligible(pause_target=identity.player_id if pause_takeover else None) if room_only else self.members(identity.player_id) is None)
        ):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="audioserver_grouping_unavailable",
            )
        return identity.player_id

    async def async_manage(self, entity, action, revision=None, members=(), group_id=None, *, override_existing_membership=False):
        target = self._resolve(entity.entity_id)
        if not isinstance(members, (list, tuple)) or any(not isinstance(m, str) for m in members):
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_grouping_unavailable")
        players = tuple(self._resolve(m) for m in members)
        initial = self.control_descriptor(target)
        if initial is None:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_grouping_unavailable")
        # Capture the ACTUAL current guard before any await; never rebase a
        # queued request or replace a caller's explicit stale literal.
        if revision is None:
            revision = initial["revision"]
        if group_id is None and action != "create":
            group_id = initial["group_id"]
        def planner():
            descriptor = self.control_descriptor(target)
            if descriptor is None or descriptor['revision'] != revision:
                raise ValueError("Stale management revision")
            return plan_manage(self.native.snapshot, action, target, players, group_id, self.eligible(),
                               override_existing_membership=override_existing_membership)
        try:
            await self.native._async_operation(planner)
        except GroupMembershipConflict:
            raise HomeAssistantError(
                "Selected rooms already belong to an audio group. Enable "
                "Override any existing group membership to move them, or choose free rooms."
            ) from None
        except (AudioCommandError, ValueError, TimeoutError):
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_grouping_failed") from None
        finally:
            self.notify()

    async def async_join(self, entity, group_members):
        if not isinstance(group_members, (tuple, list)) or any(
            not isinstance(x, str) for x in group_members
        ):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="audioserver_grouping_unavailable",
            )
        target = self._resolve(entity.entity_id)
        members = tuple(self._resolve(entity_id) for entity_id in group_members)
        try:
            await self.native.async_join(target, members)
        except (AudioCommandError, ValueError, TimeoutError):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="audioserver_grouping_failed"
            ) from None
        finally:
            self.notify()

    async def async_room_pause_takeover(self, entity):
        """Drain only an independent room's previous source/ordinary transport.

        Keep request revocation observed while the established cancellation
        helper awaits socket cleanup. No source start or sibling cancellation.
        """
        target = self._resolve(entity.entity_id, room_only=True, pause_takeover=True)
        if not self.independent(target):
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_playback_unavailable")
        context, generation, before = self.context(), self.native._generation, self.native.snapshot
        commands, task = self.native.commands, asyncio.current_task()
        previous, source_generation = entity._source_task, entity._source_generation
        source_fence = commands.source_fences.get(target)
        source_owner = commands.source_fence_owners.get(target)
        def identity():
            m = entity._audio_metadata.get(target) if entity._audio_metadata else None
            return None if m is None else tuple(getattr(m, f) for f in ("source", "source_name", "audio_path", "parent_id"))
        original, valid = identity(), True
        @callback
        def current(_event=None):
            nonlocal valid
            metadata = entity._audio_metadata.get(target) if entity._audio_metadata else None
            valid = bool(valid and not self.native._closed and not self.disabled
                         and not entity._audio_removed and entity.available
                         and entity._audio_commands_enabled and entity._audio_commands is self.native.commands
                         and entity._announcement_task is None and entity._room_transport_supported("pause")
                         and not self.native.uncertain
                         and entity._source_generation == source_generation
                         and entity._source_task in (previous, task, None)
                         and target not in commands.announcement_fences
                         and (target not in commands.source_fences or (
                             source_fence is not None and commands.source_fences[target] is source_fence
                             and commands.source_fence_owners.get(target) == source_owner))
                         and context == self.context() and generation == self.native._generation
                         and before == self.native.snapshot and identity() == original
                         and (metadata is None or metadata.event_active is not True))
            return valid
        self.native._requests.add(current)
        removers = [self.host.hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, current)]
        if entity._audio_metadata is not None:
            removers.append(entity._audio_metadata.async_add_listener(target, current))
        owner = False
        try:
            if not current():
                raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_playback_unavailable")
            # The established helper increments synchronously before its first
            # cancellation await. Observe this intent across the entire drain.
            source_generation += 1
            _generation, owner = await entity._async_begin_source_action()
            entity._finish_source_action(owner)
            if not current():
                raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_playback_failed")
            await self.async_transport(entity, "pause", room_only=True)
        finally:
            entity._finish_source_action(owner)
            for remove in removers:
                remove()
            self.native._requests.discard(current)

    async def async_transport(self, entity, action, *, room_only=False):
        """Shared host ownership, with explicit target-only or all-member scope."""
        target = self._resolve(entity.entity_id, room_only=room_only)
        task = asyncio.current_task()

        def qualification(entities):
            generations = tuple(e._source_generation for e in entities)
            def identity(e):
                m = e._audio_metadata.get(e._audio_player_id) if e._audio_metadata else None
                return None if m is None else tuple(getattr(m, f) for f in ("source", "source_name", "audio_path", "parent_id"))
            originals = tuple(identity(e) for e in entities)
            qualified = [None] * len(entities)
            observed_qualified = [False] * len(entities)
            valid = True

            def identity_current(index, e, original):
                observed = identity(e)
                if qualified[index] is not None and observed == qualified[index]:
                    observed_qualified[index] = True
                    return True
                # One exact status-qualified enrichment, not a missing-field
                # merge. Once observed, returning to the sparse original is ABA.
                return not observed_qualified[index] and observed == original

            def current():
                nonlocal valid
                valid = bool(valid and all(
                    not e._audio_removed and e._source_generation == generation
                    and (not room_only or e._room_transport_supported(action))
                    and identity_current(index, e, original)
                    and e._source_task is None and e._announcement_task is None
                    and (action != "play" or not e._audio_source_uncertain(ignore_group_reservation=True))
                    and (e._audio_metadata is None or e._audio_metadata.get(e._audio_player_id) is None
                         or e._audio_metadata.get(e._audio_player_id).event_active is not True)
                    for index, (e, generation, original) in enumerate(zip(entities, generations, originals, strict=True))
                ))
                return valid

            async def prepare(is_current):
                for index, (e, original) in enumerate(zip(entities, originals, strict=True)):
                    if (room_only or action != "play" or original is None
                        or original[3] is not None or not all(original[:3])):
                        continue
                    if not is_current():
                        raise AudioCommandError("Grouped status qualification was superseded")
                    status = await self.native.commands.async_player_status(e._audio_player_id, is_current=is_current)
                    observed = tuple(getattr(status, f) for f in ("source", "source_name", "audio_path", "parent_id"))
                    if (not is_current() or status.player_id != e._audio_player_id
                        or status.event_idle is not True or status.event_active is not False
                        or observed[:3] != original[:3]):
                        raise AudioCommandError("Grouped status did not qualify the exact existing content")
                    # A valid exact-content status may truthfully have no parent.
                    # Preserve the original STRICT identity guard in that case;
                    # no enrichment is permitted and no value is fabricated.
                    if observed[3] is not None:
                        qualified[index] = observed

            removers = []
            for e in entities:
                if e._audio_metadata is not None:
                    removers.append(e._audio_metadata.async_add_listener(e._audio_player_id, current))
            return current, removers, prepare

        # Bind EVERY participant's content and intent before the first await,
        # including the group-lock wait. Reservation must not rebind newer
        # metadata after an observed source/account/parent A->B->A.
        group = next((g for g in self.native.snapshot.groups
                      if target in g.players and g.kind == "dynamic"), None)
        initial_players = (target,) if room_only or group is None else group.players
        initial_entities = tuple(self.entities[p] for p in initial_players)
        early_current, early_removers, preparation = qualification(initial_entities)
        self.native._requests.add(early_current)
        @callback
        def registry_changed(_event):
            self.native.observe_current()
        early_removers.append(self.host.hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, registry_changed))

        def reserve(players):
            if players != initial_players or tuple(self.entities[p] for p in players) != initial_entities:
                raise AudioCommandError("Grouped participants changed before reservation")
            entities = initial_entities
            self._transport_task = task
            for e in entities:
                e._transport_tasks.add(task)
            def cleanup():
                for e in entities:
                    e._transport_tasks.discard(task)
                self._transport_task = None
            return early_current, cleanup
        async def prepare(players, is_current):
            await preparation(is_current)
        try:
            if room_only:
                await self.native.async_room_transport(target, action, reserve)
            else:
                await self.native.async_transport(target, action, reserve, prepare=prepare)
        except (AudioCommandError, ValueError, TimeoutError):
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_playback_failed") from None
        finally:
            self.native._requests.discard(early_current)
            for remove in early_removers:
                remove()
            self.notify()
        return True

    async def async_volume(self, entity, percent, *, room_only=False):
        target = self._resolve(entity.entity_id, room_only=room_only)
        group = next((g for g in self.native.snapshot.groups if g.kind == "dynamic" and target in g.players), None)
        players = group.players if group is not None and not room_only else (target,)
        entities = [self.entities[p] for p in players]
        def identity(e):
            m = e._audio_metadata.get(e._audio_player_id) if e._audio_metadata else None
            return None if m is None else tuple(getattr(m, f) for f in ("source", "source_name", "audio_path", "parent_id"))
        originals = [(e._source_generation, identity(e)) for e in entities]
        valid = True
        def qualified():
            nonlocal valid
            valid = bool(valid and all(
                not e._audio_removed and e.available and e._source_generation == generation
                and identity(e) == original and e._source_task is None
                and e._announcement_task is None and not e._transport_tasks
                and (e._audio_metadata is None or e._audio_metadata.get(e._audio_player_id) is None
                     or e._audio_metadata.get(e._audio_player_id).event_active is not True)
                for e, (generation, original) in zip(entities, originals, strict=True)))
            return valid
        removers = [self.host.hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, self._observe_registry)]
        for e in entities:
            if e._audio_metadata is not None:
                removers.append(e._audio_metadata.async_add_listener(e._audio_player_id, self.native.observe_current))
        def send(player, value):
            self.notify()
            self.host.hass.bus.async_fire(SENDDOMAIN, {"uuid": self.entities[player].uuidAction, "value": f"volume/{value}"})
        try:
            await self.native.async_volume(target, percent, lambda p: self.entities[p]._room_volume_percent,
                                           send, room_only=room_only, qualified=qualified)
        except (AudioCommandError, ValueError, TimeoutError):
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_playback_failed") from None
        finally:
            for remove in removers:
                remove()
            self.notify()

    @callback
    def _observe_registry(self, _event):
        self.native.observe_current()

    async def async_unjoin(self, entity):
        target = self._resolve(entity.entity_id)
        try:
            await self.native.async_unjoin(target)
        except (AudioCommandError, ValueError, TimeoutError):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="audioserver_grouping_failed"
            ) from None
        finally:
            self.notify()

    def connection_state(self, state):
        current = getattr(
            self.host.api, "structure_file", self.host.miniserver.lox_config.json
        )
        if grouping_binding(current) != self.binding:
            self.disabled = True
        self.native.invalidate()
        self.notify()

    async def async_close(self):
        self.disabled = True
        await self.native.async_close()
        self.notify()

    def observe(self, message):
        current = getattr(
            self.host.api, "structure_file", self.host.miniserver.lox_config.json
        )
        if grouping_binding(current) != self.binding:
            self.disabled = True
            self.native.invalidate()
            self.notify()
            return
        if (
            not self.disabled
            and isinstance(message, dict)
            and self.binding[1] in message
        ):
            self.native.observe(message[self.binding[1]])
            self.notify()

    def notify(self):
        self.native.observe_current()
        for entity in tuple(self.entities.values()):
            player = entity._audio_player_id
            membership = (
                tuple(
                    (group.group_id, group.kind, group.players)
                    for group in self.native.snapshot.groups
                    if player in group.players
                )
                if self.native.snapshot is not None and not self.disabled
                else None
            )
            if self._membership.get(player) != membership:
                entity._source_generation += 1
                entity._source_feedback = None
                for task in {
                    *entity._transport_tasks,
                    entity._source_task,
                    entity._announcement_task,
                }:
                    if task is not None and task is not asyncio.current_task():
                        task.cancel()
            self._membership[player] = membership
            entity.async_schedule_update_ha_state()
