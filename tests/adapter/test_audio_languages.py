"""Language coverage using HA's real loader; no network or household controls."""

from __future__ import annotations

# Assertions and direct fixture-resource reads are intentional test evidence.
# ruff: noqa: S101, INP001

import json
from pathlib import Path
import re
from typing import TYPE_CHECKING

from homeassistant.helpers.translation import async_get_translations
import pytest

from custom_components import loxone

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


LANGUAGES = ("fr", "it", "es", "nl", "pt", "pt-PT", "pt-BR")


def _flatten(value: dict, prefix: str = "") -> dict[str, str]:
    result = {}
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(child, dict):
            result.update(_flatten(child, path))
        else:
            result[path] = child
    return result


@pytest.mark.parametrize("language", LANGUAGES)
def test_new_integration_language_is_complete(language: str) -> None:
    """New files translate the entire existing UI, not just the audio fields."""
    directory = Path(loxone.__file__).parent / "translations"
    english = _flatten(json.loads((directory / "en.json").read_text()))
    path = directory / f"{language}.json"
    assert path.is_file(), f"Missing translation file for {language}"
    translated = _flatten(json.loads(path.read_text()))
    assert translated.keys() == english.keys()
    for key, text in translated.items():
        assert isinstance(text, str), (language, key)
        assert text.strip(), (language, key)
        assert re.findall(r"\{[^{}]+\}", text) == re.findall(r"\{[^{}]+\}", english[key])
        for literal in ("media_player", "LightControllerV2", "configuration.yaml", "latin-1", "7091"):
            if literal in english[key]:
                assert literal in text, (language, key, literal)


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.usefixtures("enable_custom_integrations")
async def test_new_languages_resolve_in_real_ha(hass: HomeAssistant, language: str) -> None:
    """Exact locale files must be consumed, not silently replaced by English."""
    directory = Path(loxone.__file__).parent / "translations"
    path = directory / f"{language}.json"
    assert path.is_file(), f"Missing translation file for {language}"
    translated = json.loads(path.read_text())
    for category, values in translated.items():
        resources = await async_get_translations(hass, language, category, {"loxone"})
        for key, expected in _flatten(values).items():
            assert resources[f"component.loxone.{category}.{key}"] == expected
    assert translated["config"]["step"]["user"]["title"] != "Set up Loxone"
    assert translated["exceptions"]["audioserver_playback_failed"]["message"] != (
        "Audio Server playback was not confirmed. No fallback or automatic retry was sent."
    )
