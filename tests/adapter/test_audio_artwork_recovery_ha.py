"""Per-entity native artwork recovery; synthetic HA and artwork only."""
# Assertions, synthetic counts, imported fixture shadowing and private checks are intentional.
# ruff: noqa: S101, SLF001, F811, PLR2004, INP001

from __future__ import annotations

import asyncio
import copy
from datetime import timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.loxone import media_player
from test_audio_artwork_ha import cover_bytes, publish
import test_audioserver_ha as fixture_module
from test_audioserver_ha import audio_setup, zone_entity_id  # noqa: F401

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import datetime
    from types import SimpleNamespace

    from aiohttp.test_utils import TestClient
    from homeassistant.core import HomeAssistant


def fire_retry(hass: HomeAssistant) -> None:
    """Run actual HA timer callbacks without sleeping or performing network I/O."""
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))


async def test_failed_cover_publishes_fresh_native_url_without_metadata_change(
    hass: HomeAssistant,
    audio_setup: SimpleNamespace,
    hass_client: Callable[[], Awaitable[TestClient]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cached placeholder must not hide a recovered same-track endpoint."""
    await audio_setup.setup()
    await publish(hass, audio_setup, 7, "Recovering same track", "/same.jpg")
    entity_id = zone_entity_id(hass, 7)
    entity = hass.data["media_player"].get_entity(entity_id)
    good = cover_bytes("blue")
    fetch = AsyncMock(return_value=(None, None))
    monkeypatch.setattr(entity, "_async_fetch_image", fetch)
    client = await hass_client()
    original_url = hass.states.get(entity_id).attributes["entity_picture"]
    failed = await client.get(original_url)
    assert failed.status == 200
    assert await failed.read() != good
    assert failed.headers["Cache-Control"] == "max-age=3600"
    fetch.return_value = (good, "image/png")

    fire_retry(hass)
    await hass.async_block_till_done()
    recovered_url = hass.states.get(entity_id).attributes["entity_picture"]
    assert recovered_url != original_url
    assert fetch.await_count == 1, "The retry publishes a URL, not background network I/O"
    recovered = await client.get(recovered_url)
    assert await recovered.read() == good
    assert fetch.await_count == 2


async def test_failed_requests_share_one_30_second_demand_triggered_retry(
    hass: HomeAssistant, audio_setup: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No unbounded timer list, periodic network poll or progress-event reset."""
    await audio_setup.setup()
    await publish(hass, audio_setup, 7, "Same", "/broken.jpg")
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    fetch = AsyncMock(return_value=(None, None))
    monkeypatch.setattr(entity, "_async_fetch_image", fetch)
    schedule = []
    real_schedule = media_player.async_call_later

    def record(hass: HomeAssistant, delay: int, action: Callable[[datetime], None]) -> Callable[[], None]:
        schedule.append(delay)
        return real_schedule(hass, delay, action)

    monkeypatch.setattr(media_player, "async_call_later", record)
    original = entity.entity_picture
    await asyncio.gather(*(entity.async_get_media_image() for _ in range(5)))
    assert schedule == [30]
    pending = entity._cover_retry_cancel
    await publish(hass, audio_setup, 7, "Same", "/broken.jpg")
    assert entity.entity_picture == original
    assert entity._cover_retry_cancel is pending
    fire_retry(hass)
    await hass.async_block_till_done()
    changed = entity.entity_picture
    assert changed != original
    assert entity._cover_retry_cancel is None
    fire_retry(hass)
    await hass.async_block_till_done()
    assert entity.entity_picture == changed
    assert fetch.await_count == 5
    assert schedule == [30]
    await entity.async_get_media_image()
    assert schedule == [30, 30], "A further failed client demand can arm one more retry"


async def test_early_recovery_notifies_other_cached_clients_and_keeps_valid_cache(
    hass: HomeAssistant,
    audio_setup: SimpleNamespace,
    hass_client: Callable[[], Awaitable[TestClient]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A direct client retry must also release other browsers' cached fallback."""
    await audio_setup.setup()
    await publish(hass, audio_setup, 7, "Same", "/same.jpg")
    entity_id = zone_entity_id(hass, 7)
    entity = hass.data["media_player"].get_entity(entity_id)
    good = cover_bytes("blue")
    fetch = AsyncMock(side_effect=[(None, None), (good, "image/png")])
    monkeypatch.setattr(entity, "_async_fetch_image", fetch)
    client = await hass_client()
    original = entity.entity_picture
    failed = await client.get(original)
    assert await failed.read() != good
    recovered = await client.get(original)
    assert await recovered.read() == good
    await hass.async_block_till_done()
    changed = hass.states.get(entity_id).attributes["entity_picture"]
    assert changed != original
    assert entity._cover_retry_cancel is None
    cached = await client.get(changed)
    assert await cached.read() == good
    fire_retry(hass)
    await hass.async_block_till_done()
    assert entity.entity_picture == changed
    assert fetch.await_count == 2


@pytest.mark.parametrize("cover", [None, "", "/valid.jpg"])
async def test_absent_and_valid_covers_never_arm_retries(
    hass: HomeAssistant, audio_setup: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, cover: str | None,
) -> None:
    """Missing metadata needs metadata feedback, not polling a nonexistent URL."""
    await audio_setup.setup()
    await publish(hass, audio_setup, 7, "Stable cover", cover)
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    good = cover_bytes("blue")
    fetch = AsyncMock(return_value=(good, "image/png"))
    monkeypatch.setattr(entity, "_async_fetch_image", fetch)
    original = entity.entity_picture
    first, mime = await entity.async_get_media_image()
    second, _ = await entity.async_get_media_image()
    assert mime == "image/png"
    assert first == second
    assert (first == good) is bool(cover)
    assert fetch.await_count == (1 if cover else 0)
    assert entity._cover_retry_cancel is None
    fire_retry(hass)
    await hass.async_block_till_done()
    assert entity.entity_picture == original


@pytest.mark.parametrize("player", range(1, 13))
async def test_retry_policy_is_player_local_across_all_twelve_rooms(
    hass: HomeAssistant, audio_setup: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, player: int,
) -> None:
    """The shared recovery path must not revise any peer's cover or controls."""
    structure = copy.deepcopy(fixture_module.STRUCTURE)
    prototype = next(iter(structure["controls"].values()))
    structure["controls"] = {}
    for pid in range(1, 13):
        control = copy.deepcopy(prototype)
        control.update(
            uuidAction=f"synthetic-zone-{pid}", details={"playerid": pid},
            states={"volume": f"volume-{pid}", "playState": f"play-{pid}"},
        )
        structure["controls"][control["uuidAction"]] = control
    monkeypatch.setattr(fixture_module, "STRUCTURE", structure)
    await audio_setup.setup()
    for pid in range(1, 13):
        await publish(hass, audio_setup, pid, f"Room {pid}", "/same.jpg")
    entities = {pid: hass.data["media_player"].get_entity(zone_entity_id(hass, pid)) for pid in range(1, 13)}
    before = {pid: entity.entity_picture for pid, entity in entities.items()}
    states = {pid: dict(hass.states.get(entity.entity_id).attributes) for pid, entity in entities.items()}
    selected = entities[player]
    monkeypatch.setattr(selected, "_async_fetch_image", AsyncMock(return_value=(None, None)))
    await selected.async_get_media_image()
    fire_retry(hass)
    await hass.async_block_till_done()
    assert selected.entity_picture != before[player]
    for pid, entity in entities.items():
        current = dict(hass.states.get(entity.entity_id).attributes)
        if pid == player:
            assert current.pop("entity_picture") != states[pid]["entity_picture"]
            expected = {k: v for k, v in states[pid].items() if k != "entity_picture"}
            assert current == expected
        else:
            assert entity.entity_picture == before[pid]
            assert current == states[pid]
            assert entity._cover_retry_cancel is None
    audio_setup.apis[0].send_websocket_command.assert_not_awaited()


async def test_track_change_cancels_retry_and_old_generation_cannot_return(
    hass: HomeAssistant, audio_setup: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Source/track reuse must not restore an older browser placeholder key."""
    await audio_setup.setup()
    await publish(hass, audio_setup, 7, "Old", "/same.jpg")
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    fetch = AsyncMock(return_value=(None, None))
    monkeypatch.setattr(entity, "_async_fetch_image", fetch)
    original = entity.entity_picture
    await entity.async_get_media_image()
    assert entity._cover_retry_cancel is not None
    await publish(hass, audio_setup, 7, "New", "/same.jpg")
    new_track = entity.entity_picture
    assert new_track != original
    assert entity._cover_retry_cancel is None
    fire_retry(hass)
    await hass.async_block_till_done()
    assert entity.entity_picture == new_track
    await publish(hass, audio_setup, 7, "Old", "/same.jpg")
    assert entity.entity_picture not in (original, new_track)
    assert fetch.await_count == 1


async def test_entity_remove_readd_cancels_retry_and_fences_late_callback(
    hass: HomeAssistant, audio_setup: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Registry rename removes/readds the same instance; no stale timer writes."""
    await audio_setup.setup()
    await publish(hass, audio_setup, 7, "Same", "/same.jpg")
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    monkeypatch.setattr(entity, "_async_fetch_image", AsyncMock(return_value=(None, None)))
    actions = []
    real_schedule = media_player.async_call_later

    def record(hass: HomeAssistant, delay: int, action: Callable[[datetime], None]) -> Callable[[], None]:
        actions.append(action)
        return real_schedule(hass, delay, action)

    monkeypatch.setattr(media_player, "async_call_later", record)
    original_hash = entity.media_image_hash
    await entity.async_get_media_image()
    er.async_get(hass).async_update_entity(entity.entity_id, new_entity_id="media_player.renamed_synthetic")
    await hass.async_block_till_done()
    assert hass.data["media_player"].get_entity("media_player.renamed_synthetic") is entity
    assert not entity._audio_removed
    assert entity._cover_retry_cancel is None
    assert entity.media_image_hash != original_hash
    current = entity.entity_picture
    await entity.async_get_media_image()
    newer_retry = entity._cover_retry_cancel
    assert newer_retry is not None
    actions[0](dt_util.utcnow())
    await hass.async_block_till_done()
    assert entity.entity_picture == current
    assert entity._cover_retry_cancel is newer_retry


@pytest.mark.parametrize("old_content", [None, cover_bytes("red")])
async def test_late_fetch_after_track_change_cannot_cache_or_arm_old_retry(
    hass: HomeAssistant, audio_setup: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, old_content: bytes | None,
) -> None:
    """Both a stale success and a stale failure belong only to the old track."""
    await audio_setup.setup()
    await publish(hass, audio_setup, 7, "Old", "/old.jpg")
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(_url: str) -> tuple[bytes | None, str]:
        entered.set()
        await release.wait()
        return old_content, "image/png"

    monkeypatch.setattr(entity, "_async_fetch_image", delayed)
    task = asyncio.create_task(entity.async_get_media_image())
    await entered.wait()
    await publish(hass, audio_setup, 7, "New", "")
    current = entity.entity_picture
    release.set()
    result, mime = await task
    assert result != old_content
    assert mime == "image/png"
    assert entity.entity_picture == current
    assert entity._cover_cache is None
    assert entity._cover_retry_cancel is None
