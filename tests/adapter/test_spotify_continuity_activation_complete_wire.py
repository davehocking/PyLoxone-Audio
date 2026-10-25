"""Unknown post-activation native position vetoes the actual OAuth send middleware."""

# ruff: noqa: S101, INP001, ANN001, ANN202, D103, PLR2004, PLR0915, ASYNC240, PT018
import json
from dataclasses import replace
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

from custom_components.loxone import spotify_continuity as m


@pytest.mark.asyncio
@pytest.mark.parametrize("expired", [False, True])
async def test_actual_oauth_middleware_vetoes_unknown_position_after_final_refresh(hass, monkeypatch, tmp_path, expired):
    pytest_socket.socket_allow_hosts([], allow_unix_socket=True)
    controller, fake, snapshots, commands, entry = setup_boundary(hass)
    await controller.async_capture(lambda: True)
    snapshots[0] = native("tunein:station:synthetic")
    fake.current = None
    hass.config.config_dir = str(tmp_path)
    writes = []
    injected = False
    healthy = None

    async def handler(request):
        if request.method == "PUT":
            writes.append({"path": request.path, "body": await request.read()})
            fake.current = playback()
            fake.current["is_playing"] = request.path.endswith("/play")
            snapshots[0] = native(mode="play" if fake.current["is_playing"] else "stop")
            return web.Response(status=204)
        if request.path == "/v1/me":
            return web.json_response({"id": CONFIG["user_id"]})
        if request.path.endswith("/devices"):
            return web.json_response({"devices": [{"id": CONFIG["device_id"], "is_restricted": False,
                                                   "is_active": fake.current is not None}]})
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
                entry.data = {"token": {"access_token": "synthetic-only", "expires_at": 0 if expired else time.time() + 3600}}
                implementation = SimpleNamespace(async_refresh_token=AsyncMock(return_value={
                    "access_token": "synthetic-refreshed", "expires_at": time.time() + 3600}))

                def update_entry(updated, *, data):
                    assert updated is entry
                    updated.data = data

                monkeypatch.setattr(hass.config_entries, "async_update_entry", update_entry)
                session = oauth.OAuth2Session(hass, entry, implementation)
                entry.runtime_data.session = session
                original_ensure = session.async_ensure_token_valid

                async def ensure():
                    nonlocal injected, healthy
                    await original_ensure()
                    marker_root = Path(hass.config.path(".storage", "pyloxone_spotify_return_dispatch"))
                    if not injected and any(json.loads(p.read_text())["action"] == "play" for p in marker_root.glob("*.json")):
                        injected = True
                        healthy = snapshots[0]
                        snapshots[0] = replace(healthy, position=None)

                monkeypatch.setattr(session, "async_ensure_token_valid", ensure)
                with pytest.raises(m.AudioCommandError):
                    await controller.async_resume(lambda: True)
                assert injected and controller.uncertain
                assert healthy is not None
                snapshots[0] = healthy
                with pytest.raises(m.AudioCommandError):
                    await controller.async_resume(lambda: True)
    finally:
        await runner.cleanup()
    assert [w["path"] for w in writes] == ["/v1/me/player"]
    assert json.loads(writes[0]["body"]) == {"device_ids": [CONFIG["device_id"]], "play": False}
    assert commands.source_fences
