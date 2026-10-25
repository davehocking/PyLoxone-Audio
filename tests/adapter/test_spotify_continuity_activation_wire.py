"""Real HA OAuth2Session/aiohttp activation then bodylessPlay over AF_UNIX only."""

# ruff: noqa: S101, INP001, ANN001, ANN202, D103, PLC0415, PLR2004, PLR0915, PLR0911, ASYNC240, PT018
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiohttp
from aiohttp import web
import pytest
import pytest_socket
from homeassistant.helpers import config_entry_oauth2_flow as oauth
from test_spotify_continuity import CONFIG, native, playback, setup_boundary


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "activate-disconnect", "play-disconnect", "activate-401", "play-401"])
@pytest.mark.parametrize("expired", [False, True])
async def test_real_oauth_transfer_and_play_have_separate_single_dispatches(
    hass, monkeypatch, tmp_path, failure, expired
):
    from custom_components.loxone import spotify_continuity as m

    pytest_socket.socket_allow_hosts([], allow_unix_socket=True)
    controller, fake, snapshot, _, entry = setup_boundary(hass)
    await controller.async_capture(lambda: True)
    snapshot[0] = native("tunein:station:synthetic")
    fake.current = None
    hass.config.config_dir = str(tmp_path)
    writes = []

    async def handler(request):
        if request.method == "PUT":
            action = "activate" if request.path == "/v1/me/player" else "play"
            marker_root = Path(hass.config.path(".storage", "pyloxone_spotify_return_dispatch"))
            assert any(json.loads(p.read_text())["action"] == action for p in marker_root.glob("*.json"))
            writes.append(
                {"action": action, "body": await request.read(), "query": dict(request.query), "path": request.path}
            )
            if failure == action + "-disconnect":
                request.transport.close()
                return web.Response(status=204)
            if failure == action + "-401":
                return web.Response(status=401)
            fake.current = playback()
            fake.current["is_playing"] = action == "play"
            snapshot[0] = native(mode="play" if action == "play" else "stop")
            return web.Response(status=204)
        if request.path == "/v1/me":
            return web.json_response({"id": CONFIG["user_id"]})
        if request.path.endswith("/devices"):
            return web.json_response(
                {
                    "devices": [
                        {"id": CONFIG["device_id"], "is_restricted": False, "is_active": fake.current is not None}
                    ]
                }
            )
        if request.path.endswith("/queue"):
            return web.json_response(fake.queue)
        return web.json_response(fake.current) if fake.current else web.Response(status=204)

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        with tempfile.TemporaryDirectory() as directory:
            path = directory + "/oauth.sock"
            await web.UnixSite(runner, path).start()
            async with aiohttp.ClientSession(connector=aiohttp.UnixConnector(path=path)) as client:
                monkeypatch.setattr(oauth, "async_get_clientsession", lambda _: client)
                monkeypatch.setattr(m, "_API", "http://spotify.example.invalid/v1/")
                entry.data = {
                    "token": {"access_token": "synthetic-only", "expires_at": 0 if expired else time.time() + 3600}
                }
                refreshed = {"access_token": "synthetic-refreshed", "expires_at": time.time() + 3600}
                implementation = SimpleNamespace(async_refresh_token=AsyncMock(return_value=refreshed))

                def update_entry(updated, *, data):
                    assert updated is entry
                    updated.data = data

                monkeypatch.setattr(hass.config_entries, "async_update_entry", update_entry)
                entry.runtime_data.session = oauth.OAuth2Session(hass, entry, implementation)
                if failure:
                    with pytest.raises((m.AudioCommandError, aiohttp.ClientError)):
                        await controller.async_resume(lambda: True)
                    assert controller.uncertain
                    with pytest.raises(m.AudioCommandError):
                        await controller.async_resume(lambda: True)
                else:
                    await controller.async_resume(lambda: True)
                    assert controller.bookmark is None and not controller.uncertain
    finally:
        await runner.cleanup()
    expected = ["activate"] if failure and failure.startswith("activate") else ["activate", "play"]
    assert [w["action"] for w in writes] == expected
    assert json.loads(writes[0]["body"]) == {"device_ids": [CONFIG["device_id"]], "play": False}
    assert writes[0]["query"] == {}
    if len(writes) == 2:
        assert writes[1]["body"] == b"" and writes[1]["query"] == {"device_id": CONFIG["device_id"]}
