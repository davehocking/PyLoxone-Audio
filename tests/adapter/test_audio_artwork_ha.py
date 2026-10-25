"""Native HA image-proxy contracts; all media and responses are synthetic."""
# ruff: noqa: S101, INP001, SLF001, ARG001
from io import BytesIO
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from aiohttp import ClientConnectionError

from PIL import Image
import pytest
from homeassistant.core import HomeAssistant
from custom_components.loxone.const import EVENT
from test_audioserver_ha import audio_setup, zone_entity_id  # noqa: F401


@pytest.mark.asyncio
async def test_native_proxy_returns_decodable_music_cover_on_failed_artwork(
    hass: HomeAssistant, audio_setup: SimpleNamespace, hass_client, monkeypatch,
) -> None:
    """The standard more-info route must not return a broken-image 404."""
    await audio_setup.setup()
    hass.bus.async_fire(EVENT, {"play-7": 2})
    await audio_setup.queues[0].put(
        '{"audio_event":[{"playerid":7,"title":"Synthetic report","coverurl":"/missing.jpg"}]}'
    )
    await hass.async_block_till_done()
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    monkeypatch.setattr(entity, "_async_fetch_image", AsyncMock(return_value=(None, None)))
    client = await hass_client()
    response = await client.get(entity.entity_picture)
    assert response.status == 200
    assert response.headers["Content-Type"] == "image/png"
    with Image.open(BytesIO(await response.read())) as cover:
        cover.load()
        assert cover.size == (256, 256)


def cover_bytes(colour):
    out = BytesIO()
    Image.new("RGB", (24, 24), colour).save(out, format="PNG")
    return out.getvalue()


async def publish(hass, setup, player, title, cover):
    hass.bus.async_fire(EVENT, {f"play-{player}": 2})
    await setup.queues[0].put(json.dumps({"audio_event": [
        {"playerid": player, "title": title, "coverurl": cover},
    ]}))
    await hass.async_block_till_done()


@pytest.mark.asyncio
@pytest.mark.parametrize("cover", [None, ""])
async def test_absent_cover_keeps_native_proxy_and_never_fetches(
    hass, audio_setup, hass_client, monkeypatch, cover,
):
    await audio_setup.setup()
    await publish(hass, audio_setup, 8, "No cover", cover)
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 8))
    fetch = AsyncMock()
    monkeypatch.setattr(entity, "_async_fetch_image", fetch)
    client = await hass_client()
    assert entity.entity_picture.startswith("/api/media_player_proxy/")
    response = await client.get(entity.entity_picture)
    assert response.status == 200
    with Image.open(BytesIO(await response.read())) as cover:
        cover.load()
        assert cover.size == (256, 256)
    fetch.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [b"", b"not an image", cover_bytes("red")[:55], ClientConnectionError(), TimeoutError()])
async def test_failed_decode_or_fetch_recovers_with_later_valid_cover(
    hass, audio_setup, hass_client, monkeypatch, bad,
):
    await audio_setup.setup()
    await publish(hass, audio_setup, 7, "Recovering", "/same.jpg")
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    good = cover_bytes("blue")
    fetch = AsyncMock(side_effect=[bad if isinstance(bad, Exception) else (bad, "image/jpeg"), (good, "image/jpeg")])
    monkeypatch.setattr(entity, "_async_fetch_image", fetch)
    client = await hass_client()
    failed = await client.get(entity.entity_picture)
    assert failed.status == 200
    with Image.open(BytesIO(await failed.read())) as cover:
        cover.load()
        assert cover.size == (256, 256)
    recovered = await client.get(entity.entity_picture)
    assert await recovered.read() == good
    assert recovered.headers["Content-Type"] == "image/png"
    assert fetch.await_count == 2


@pytest.mark.asyncio
async def test_native_proxy_does_not_reuse_old_track_or_other_room_cover(
    hass, audio_setup, hass_client, monkeypatch,
):
    await audio_setup.setup()
    first, second = [hass.data["media_player"].get_entity(zone_entity_id(hass, n)) for n in (7, 8)]
    red, blue, green = [cover_bytes(c) for c in ("red", "blue", "green")]
    monkeypatch.setattr(first, "_async_fetch_image", AsyncMock(side_effect=[(red, "image/png"), (green, "image/png")]))
    monkeypatch.setattr(second, "_async_fetch_image", AsyncMock(return_value=(blue, "image/png")))
    client = await hass_client()
    for entity, player, title, expected in [(first, 7, "First", red), (second, 8, "Other", blue), (first, 7, "Changed", green)]:
        await publish(hass, audio_setup, player, title, "/reused-native-cover.jpg")
        response = await client.get(entity.entity_picture)
        assert await response.read() == expected


@pytest.mark.asyncio
async def test_late_cover_from_previous_source_cannot_replace_new_track(
    hass, audio_setup, monkeypatch,
):
    await audio_setup.setup()
    await publish(hass, audio_setup, 7, "Old", "/old.jpg")
    entity = hass.data["media_player"].get_entity(zone_entity_id(hass, 7))
    entered, release = asyncio.Event(), asyncio.Event()
    red = cover_bytes("red")
    async def delayed(_):
        entered.set()
        await release.wait()
        return red, "image/png"
    monkeypatch.setattr(entity, "_async_fetch_image", delayed)
    task = asyncio.create_task(entity.async_get_media_image())
    await entered.wait()
    await publish(hass, audio_setup, 7, "New", "")
    release.set()
    result, mime = await task
    assert result != red and mime == "image/png"
    assert entity._cover_cache is None
