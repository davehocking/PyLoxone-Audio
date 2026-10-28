"""Release cutoff through the actual owning HA entity and native transport."""
from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest
from homeassistant.exceptions import HomeAssistantError
from test_audioserver_ha import audio_setup as audio_setup
from test_source_return_simplification_ha import rsa_key as rsa_key
from test_source_return_simplification_ha import select, simplified_harness

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from Crypto.PublicKey.RSA import RsaKey
    from homeassistant.core import HomeAssistant


@pytest.mark.asyncio
async def test_source_failure_preserves_error_without_development_trace_state(
    hass: HomeAssistant,
    audio_setup: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
    rsa_key: RsaKey,
) -> None:
    """Retain a real rejected source action, its error and task cleanup."""
    entity, controls, sockets, _emit = await simplified_harness(
        hass, audio_setup, monkeypatch, rsa_key,
    )
    controls["source_reply"] = "reject"
    with pytest.raises(HomeAssistantError):
        await select(hass, entity)
    assert sockets
    assert not hasattr(entity, "_audio_last_source_failure")
    assert "audio_last_source_failure" not in entity.extra_state_attributes
    assert "pyloxone_audio.diagnostics" not in sys.modules
    # Approved0.1.1 opt-in diagnostics supersedes ONLY the blanket module ban.
    # A default-off entry must still collect no events after this real failure.
    collectors = [getattr(value, "audio_diagnostics", None)
                  for value in hass.data["loxone"].values()]
    assert any(collector is not None for collector in collectors)
    assert all(not collector.enabled and collector.queue.empty()
               for collector in collectors if collector is not None)
    assert entity._source_task is None
