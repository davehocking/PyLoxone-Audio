"""Real HA OAuth helper and aiohttp over AF_UNIX, using synthetic auth only."""

# ruff: noqa: S101, INP001, ANN001, ANN202, D103, PLC0415

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiohttp
from aiohttp import web
import pytest
import pytest_socket

from homeassistant.helpers import config_entry_oauth2_flow as oauth
from test_spotify_continuity import CONFIG, setup_boundary, native, playback


@pytest.mark.asyncio
@pytest.mark.parametrize("disconnect", [False, True])
@pytest.mark.parametrize("expired", [False, True])
async def test_actual_oauth_http_body_and_no_internal_retry(hass, monkeypatch, disconnect, expired):
    from custom_components.loxone import spotify_continuity as m

    pytest_socket.socket_allow_hosts([], allow_unix_socket=True)
    controller, fake, snapshot, _, entry = setup_boundary(hass)
    await controller.async_capture(lambda: True)
    snapshot[0] = native("tunein:station:synthetic")
    fake.current["is_playing"] = False
    writes = []
    authorizations = []

    async def handler(request):
        authorizations.append(request.headers.get("Authorization"))
        if request.method == "PUT":
            writes.append({"body": await request.read(), "query": dict(request.query), "path": request.path})
            if disconnect:
                request.transport.close()
                return web.Response(status=204)
            snapshot[0] = native()
            fake.current = playback()
            fake.current["progress_ms"] = 14081
            return web.Response(status=204)
        if request.path == "/v1/me":
            return web.json_response({"id": CONFIG["user_id"]})
        if request.path.endswith("/devices"):
            return web.json_response(
                {"devices": [{"id": CONFIG["device_id"], "is_restricted": False, "is_active": False}]}
            )
        if request.path.endswith("/queue"):
            return web.json_response(fake.queue)
        return web.json_response(fake.current) if fake.current else web.Response(status=204)

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    # Keep the socket pathname short enough for AF_UNIX.
    import tempfile

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

            def update_entry(updated, *, data) -> None:
                assert updated is entry
                updated.data = data

            monkeypatch.setattr(hass.config_entries, "async_update_entry", update_entry)
            entry.runtime_data.session = oauth.OAuth2Session(hass, entry, implementation)
            if disconnect:
                with pytest.raises((aiohttp.ClientError, m.AudioCommandError)):
                    await controller.async_resume(lambda: True)
                assert controller.uncertain
            else:
                await controller.async_resume(lambda: True)
        await runner.cleanup()
    assert writes == [{"body": b"", "query": {"device_id": CONFIG["device_id"]}, "path": "/v1/me/player/play"}]
    assert implementation.async_refresh_token.await_count == int(expired)
    expected = "synthetic-refreshed" if expired else "synthetic-only"
    assert set(authorizations) == {"Bearer " + expected}
