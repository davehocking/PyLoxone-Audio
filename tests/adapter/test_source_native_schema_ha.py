"""Synthetic schema controls based on bounded read-only native shapes only."""

# Assertions, fixture shadowing and synthetic counts are intentional.
# ruff: noqa: S101, F811, INP001, SLF001
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from test_audioserver_ha import audio_setup  # noqa: F401
from test_native_source_return_ha import PARENT, TRACK, install_sources, library_row
from custom_components.loxone.pyloxone_api import audioserver as wire

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


@pytest.mark.asyncio
@pytest.mark.parametrize("index", [0, 12])
async def test_library_id_only_thirteen_row_schema_keeps_exact_retained_track(
    hass: HomeAssistant,
    audio_setup: Any,
    monkeypatch: pytest.MonkeyPatch,
    index: int,
) -> None:
    """Observed type1/id-only pages do not establish a Library preparation bug."""
    entity, emit, calls = await install_sources(hass, audio_setup, monkeypatch)
    paths = [f"library:local:track:synthetic-{n}" for n in range(13)]
    paths[index] = TRACK
    original_folder = wire.AudioServerCommands.async_media_folder

    async def folder(_self: Any, service: str, _account: str, path: str, offset: int) -> list[dict]:
        if service != "library":
            return await original_folder(_self, service, _account, path, offset)
        return [
            {
                "id": path,
                "name": "Synthetic parent",
                "type": 1,
                "start": offset,
                "totalitems": len(paths),
                "items": [
                    {
                        "type": 2,
                        "id": value,
                        "name": "Synthetic track",
                        "duration": 240,
                        "configerror": False,
                        "external": False,
                        "hasCover": False,
                        "nas": True,
                    }
                    for value in paths
                ],
            }
        ]

    monkeypatch.setattr(wire.AudioServerCommands, "async_media_folder", folder)
    await emit(library_row())
    await emit(
        {
            "playerid": 7,
            "mode": "play",
            "eventype": 0,
            "audiopath": "spotify:track:synthetic",
            "parent": {"id": "spotify:track:synthetic"},
            "sourceName": "Synthetic owner",
        }
    )
    await hass.services.async_call(
        "media_player",
        "select_source",
        {
            "entity_id": entity.entity_id,
            "source": "Local Library",
        },
        blocking=True,
    )

    assert calls[0].endswith(f"/parentpath/library%3Alocal%3Afolder%3Aalbum/{index}")
    assert calls[1] == "audio/7/position/45.0"
    assert entity._audio_metadata.get(7).audio_path == TRACK
    assert entity._audio_metadata.get(7).parent_id == PARENT
