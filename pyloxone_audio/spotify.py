"""Native Spotify session return via an optional host-owned read-only bridge.

Spotify retains session/queue ownership. This module cannot log in, store OAuth
credentials, PUT playback state, copy queues or resolve a different receiver.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from .metadata import AudioMetadataCoordinator
from .native import AudioCommandError, AudioServerCommands, AudioZoneMetadata
from .sources import SourceEnvironment, native_selection_unchanged


@dataclass(frozen=True, slots=True)
class SpotifyNativeSession:
    """Exact identities qualified by the already-linked host session."""

    native_user: str
    account_id: str


class NativeSessionUnavailableError(AudioCommandError):
    """Optional linked-session evidence is unavailable; route owns any fallback."""


class SpotifySessionBridge(Protocol):
    """Host owns token/session validation and the existing shared account lock."""

    def async_native_session(
        self, available: Callable[[], bool],
    ) -> AbstractAsyncContextManager[SpotifyNativeSession | None]:
        """Read/qualify exact account and receiver, holding the lock until exit."""
        ...


async def async_resume_native_session(
    commands: AudioServerCommands,
    metadata: AudioMetadataCoordinator,
    player_id: int,
    bridge: SpotifySessionBridge,
    available: Callable[[], bool],
    *,
    timeout_factory: Callable[[float], AbstractAsyncContextManager[None]] = asyncio.timeout,
    environment: SourceEnvironment | None = None,
) -> bool:
    """Use reviewed native settlement and fresh feedback, not a provider write.

    The host's bridge may return None for an absent optional session. It must
    raise on positive wrong-account/device evidence; absence alone is no veto
    of the caller's valid last-good/native source path.
    """
    original = metadata.get(player_id)
    if original is None or not available():
        message = "Native room observation is unavailable; no session request was sent"
        raise AudioCommandError(message)
    async with timeout_factory(10), bridge.async_native_session(available) as session:
        if not native_selection_unchanged(original, metadata.get(player_id)):
            raise AudioCommandError('Room or Spotify ownership changed; no replay was sent')
        if session is None:
            return False

        def matches(snapshot: AudioZoneMetadata) -> bool:
            return bool(
                snapshot.source == 'Spotify' and snapshot.source_name == session.native_user
                and snapshot.audio_path and snapshot.audio_path.startswith(('spotify:track:', 'spotify:episode:'))
            )

        if original.source == 'Spotify' and original.native_mode in ('play', 'pause'):
            if original.source_name != session.native_user:
                raise AudioCommandError('Native and provider Spotify playback disagree')
            if original.native_mode == 'play' and matches(original):
                return True

        async def send(current: Callable[[], bool], sent: Callable[[], None]) -> None:
            await commands.async_spotify_handoff(
                player_id, session.account_id, is_current=current, on_send=sent,
            )

        await (environment or SourceEnvironment()).async_observed_change(
            commands, metadata, player_id, send, matches,
            is_available=available, expected_native=original,
        )
        return True
