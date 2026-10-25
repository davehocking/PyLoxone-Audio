"""Replay204→transfer→paused→Play using synthetic identities and queue previews."""

# ruff: noqa: S101, INP001, ANN001, ANN003, ANN202, D103, PT018, PLR2004
from copy import deepcopy

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_spotify_continuity import DEVICE, Session, native, playback, setup_boundary


class ActivationSession(Session):
    """Public HA OAuth boundary, retaining a duplicate/custom preview unchanged."""

    def __init__(self, original, journal) -> None:
        """Retain synthetic provider/native observations and a temporary journal."""
        super().__init__(original.snapshot)
        self.journal = journal
        self.current = deepcopy(original.current)
        self.queue = deepcopy(original.queue)
        self.transfer_count = 0
        self.before_transfer = None
        self.after_transfer = None
        self.on_put = self.check_play_marker

    def check_markers(self, action):
        """Require a durable marker before the synthetic request handler."""
        markers = [json.loads(p.read_text()) for p in self.journal.glob("*.json")]
        assert any(m["action"] == action for m in markers), "durable marker must precede actual send"

    async def check_play_marker(self):
        """Require separate Play permission before its handler runs."""
        self.check_markers("play")

    async def async_request(self, method, url, **kwargs):
        """Keep activation and bodyless Play as distinct public requests."""
        if method == "PUT" and url.endswith("/me/player"):
            self.calls.append((method, url, deepcopy(kwargs)))
            assert kwargs["json"] == {"device_ids": [DEVICE], "play": False}
            assert "params" not in kwargs and kwargs["allow_redirects"] is False

            async def send(_request):
                self.check_markers("activate")
                if self.before_transfer:
                    await self.before_transfer()
                self.transfer_count += 1
                self.current = playback()
                self.current["is_playing"] = False
                self.snapshot[0] = native(mode="stop")
                if self.after_transfer:
                    await self.after_transfer()
                return SimpleNamespace(status=204, release=lambda: None)

            return await kwargs["middlewares"][0](None, send)
        return await super().async_request(method, url, **kwargs)


async def detached_boundary(hass, tmp_path):
    controller, old, snapshots, commands, entry = setup_boundary(hass)
    hass.config.config_dir = str(tmp_path)
    session = ActivationSession(old, Path(hass.config.path(".storage", "pyloxone_spotify_return_dispatch")))
    entry.runtime_data.session = session
    await controller.async_capture(lambda: True)
    snapshots[0] = native("tunein:station:synthetic", mode="play")
    session.current = None
    return controller, session, snapshots, commands, entry


@pytest.mark.asyncio
async def test_detached_session_is_activated_matched_then_resumed_once(hass, tmp_path):
    controller, session, snapshots, commands, _ = await detached_boundary(hass, tmp_path)
    saved = controller.bookmark
    await controller.async_resume(lambda: True)
    writes = [c for c in session.calls if c[0] == "PUT"]
    assert [c[1].rsplit("/", 1)[-1] for c in writes] == ["player", "play"]
    assert session.transfer_count == 1
    assert saved.queue == tuple(row["uri"] for row in session.queue["queue"])
    assert snapshots[0].native_mode == "play"
    assert controller.bookmark is None and not controller.uncertain and not commands.source_fences
    assert len(list(session.journal.glob("*.json"))) == 2
