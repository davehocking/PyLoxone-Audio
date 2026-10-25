"""Offline optional audio coordinator behaviour; no live connections."""

from __future__ import annotations

# Assert/magic fixture IDs, private lifecycle checks and stub exceptions are intentional.
# ruff: noqa: S101, INP001, SLF001, TRY003, EM101

import pytest

from custom_components.loxone.audio import AudioMetadataCoordinator


@pytest.mark.parametrize(
    ("cover", "expected"),
    [
        (None, None),
        ("", None),
        ("/covers/a.jpg", "http://audio.example.invalid:7091/covers/a.jpg"),
        ("covers/a.jpg", "http://audio.example.invalid:7091/covers/a.jpg"),
        ("https://images.example.invalid/a.jpg", "https://images.example.invalid/a.jpg"),
        ("javascript:alert(1)", None),
        ("file:///etc/passwd", None),
        ("data:image/png;base64,synthetic", None),
        ("http://user:password@images.example.invalid/a.jpg", None),
        ("http://[broken/cover.jpg", None),
        ("http://images.example.invalid:bad/cover.jpg", None),
    ],
)
def test_artwork_only_accepts_valid_credential_free_http_urls(cover: str | None, expected: str | None) -> None:
    """Do not expose non-HTTP or credential-bearing artwork to HA."""
    audio = AudioMetadataCoordinator("audio.example.invalid")
    assert audio.artwork_url(cover) == expected


def test_bad_entity_callback_does_not_interrupt_other_zones(caplog: pytest.LogCaptureFixture) -> None:
    """An entity failure cannot terminate the shared event receiver."""
    audio = AudioMetadataCoordinator("audio.example.invalid")
    good_calls = []

    def bad() -> None:
        raise RuntimeError("synthetic observer failure")

    audio.async_add_listener(7, bad)
    audio.async_add_listener(8, lambda: good_calls.append(True))
    audio._on_update(())
    assert good_calls == [True]
    assert "Audioserver metadata subscriber failed" in caplog.text
