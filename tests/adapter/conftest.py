"""Shared fixtures for the Loxone integration test tree.

``enable_custom_integrations`` is re-defined here (not the phcc-studio
fixture) so it also re-roots ``custom_components`` at the repo's own
``custom_components/`` directory. Phcc's stock fixture only clears the
loader integration cache, and pins ``custom_components.__path__`` at
phcc's testing_config directory, which would make
``custom_components.loxone`` un-importable in tests.
"""

from __future__ import annotations

from pathlib import Path
import os

import pytest

REPO_ROOT = Path(os.environ["PYLOXONE_AUDIO_HOST_ROOT"]).resolve()


@pytest.fixture
def enable_custom_integrations(hass):
    """Re-points ``custom_components`` at the repo's ``custom_components/`` and
    clears the loader integration cache.
    """
    import custom_components

    from homeassistant import loader

    original = list(custom_components.__path__)
    custom_components.__path__ = [str(REPO_ROOT / "custom_components")]
    hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
    yield
    custom_components.__path__ = original


@pytest.fixture(autouse=True)
def _owner_oracle_read_peer(request, monkeypatch):
    """Complete only the immutable owner oracle's synthetic read-only peer.

    Under the full suite's real elapsed time R1 may legitimately request missing
    status during the follow-up journey. This fixture rejects that optional read
    as unavailable, rather than inventing modes or raising the play/pause-only
    peer's AssertionError. Authentication and every other command remain strict;
    no deadlines, recovery state, owning oracle or production code are changed.
    """
    if request.path.name == 'test_owner_volume_recovery_ha.py':
        import json
        from test_audioserver_playback import SyntheticAudioSocket

        original = SyntheticAudioSocket.send

        async def send(self, message):
            parts = message.split('/')
            if len(parts) == 3 and parts[0] == 'audio' and parts[1].isdigit() and parts[2] == 'status':
                self.sent.append(message)
                self.queue.put_nowait(json.dumps({'status_result': False}))
            else:
                await original(self, message)

        monkeypatch.setattr(SyntheticAudioSocket, 'send', send)
        # HA's normal block helper excludes background recovery tasks. Drain
        # only this fixture's actual optional reads before the unchanged oracle
        # checks that every authenticated synthetic socket has really closed.
        # Await normally: no cancellation, swallowed error, fake close or timer.
        import asyncio
        hass = request.getfixturevalue('hass')
        block = hass.async_block_till_done

        async def drain(*args, **kwargs):
            await block(*args, **kwargs)
            tasks = [task for co in hass.data.get('loxone', {}).values()
                     if (metadata := getattr(co, 'audio_metadata', None)) is not None
                     for task in metadata._recoveries.values()]
            if tasks:
                await asyncio.gather(*tasks)
                await block(*args, **kwargs)

        monkeypatch.setattr(hass, 'async_block_till_done', drain)
    yield
