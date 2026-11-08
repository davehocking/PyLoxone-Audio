# Grouping in automations

Complete [Required setup](README.md#required-setup), then choose **Loxone: Manage an audio group** (`loxone.audio_group_manage`) in Home Assistant's action picker.

Select one target room, an **Action**, and **Additional rooms** where needed. You do not need internal group IDs or revisions.

| Action | Target and result |
|---|---|
| `create` | Target leads the new group; Additional rooms are its other members. Select at least one additional room. The resulting group contains exactly those rooms. |
| `add` | Target belongs to an existing dynamic group. Additional rooms join it; its leader and existing members remain. |
| `remove` | Removes the target room from its group. Leave Additional rooms empty. Fewer than two remaining rooms dissolves the group. |
| `destroy` | Removes the target's whole group. Leave Additional rooms empty. |

## Moving rooms from other groups

**Override any existing group membership** is off by default. Leave it off unless you intend to transfer occupied rooms. For `create` or `add`, enabling it allows selected rooms to leave their existing dynamic groups. Unselected rooms remain together where at least two remain; smaller remainders dissolve. `add` never replaces the destination leader. Do not enable override for `remove` or `destroy`.

Group changes and transfers can interrupt sound. If an action fails after a partial change, inspect the current groups before trying again. Override does not bypass unavailable/stale-state checks or allow fixed/static groups. The action supports Loxone-managed audio rooms on one Audio Server.

## Example

Replace these example entity IDs with your own. This creates a group led by the living-room player without moving occupied rooms:

```yaml
action: loxone.audio_group_manage
target:
  entity_id: media_player.living_room
data:
  action: create
  members:
    - media_player.kitchen
  override_existing_membership: false
```

This action is separate from standard `media_player.join`, which adds to an existing group. The interactive Create/Add picker only offers free rooms; it does not enable transfers automatically.

[User guide](USER-GUIDE.md) · [Report a problem](DIAGNOSTICS.md)
