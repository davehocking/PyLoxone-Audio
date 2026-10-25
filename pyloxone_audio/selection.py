"""Reusable native source routing and strict manual-track qualification."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING
from aiohttp import ClientError
from .native import AudioCommandError
from .catalogue import CatalogueTarget

from .sources import SourceEnvironment, async_native_catalogue_noop, native_selection_unchanged
from .spotify import NativeSessionUnavailableError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from .catalogue import AudioCatalogue
    from .metadata import AudioMetadataCoordinator
    from .native import AudioServerCommands
    from .radio import RadioTarget
    from .native import AudioZoneMetadata


class NativeResumeOutcome(Enum):
    """Explicit result of the host's existing linked-session bridge."""

    UNAVAILABLE = "unavailable"
    COMPLETE = "complete"


async def async_optional_native_resume(
    commands: AudioServerCommands, metadata: AudioMetadataCoordinator, player_id: int,
    target: RadioTarget, attempt: Callable[[RadioTarget], Awaitable[NativeResumeOutcome]],
    *, is_current: Callable[[], bool],
) -> NativeResumeOutcome:
    """Own optional-attempt pinning and the no-retained-fallback safety decision."""
    original = metadata.get(player_id)

    def retained_allowed() -> bool:
        return bool(
            is_current() and native_selection_unchanged(original, metadata.get(player_id))
            and player_id not in commands.source_fences and player_id not in commands.announcement_fences
        )

    try:
        outcome = await attempt(target)
    except (NativeSessionUnavailableError, TimeoutError, ClientError):
        if not retained_allowed():
            raise
        return NativeResumeOutcome.UNAVAILABLE
    if outcome is NativeResumeOutcome.UNAVAILABLE:
        if not retained_allowed():
            message = "Source return was superseded before native dispatch"
            raise AudioCommandError(message)
    elif outcome is not NativeResumeOutcome.COMPLETE:
        message = "Native session bridge returned an invalid outcome"
        raise AudioCommandError(message)
    return outcome


def manual_seek_supported(snapshot: AudioZoneMetadata | None) -> bool:
    """Require the native track capability, not an inferred source feature."""
    return bool(
        snapshot is not None and snapshot.event_active is False
        and snapshot.source in {"Spotify", "Local Library"}
        and snapshot.position is not None and snapshot.duration is not None
        and snapshot.playback_restrictions is not None and snapshot.playback_restrictions & 32
    )


def confirmed_library_session(snapshot: AudioZoneMetadata | None, saved: AudioZoneMetadata | None) -> bool:
    """Qualify the retained native Library selection independently of host uncertainty."""
    return bool(
        snapshot is not None and saved is not None and snapshot.source == "Local Library"
        and snapshot.event_idle and snapshot.event_active is False
        and snapshot.native_mode in ("play", "pause")
        and all(getattr(snapshot, field) == getattr(saved, field)
                for field in ("player_id", "source", "audio_path", "parent_id"))
    )


def native_track_identity(snapshot: AudioZoneMetadata | None) -> tuple | None:
    """Use the accepted native track generation key, also suitable for UI clocks."""
    return (
        (snapshot.audio_path, snapshot.title, snapshot.artist, snapshot.album, snapshot.duration)
        if snapshot is not None and snapshot.duration is not None else None
    )


def manual_seek_position(position: float, duration: float) -> float:
    """Reject invalid offsets and stop before the queue-advancing track end."""
    if isinstance(position, bool) or not isinstance(position, (int, float)) or not 0 <= position < float("inf"):
        message = "Invalid manual seek position"
        raise ValueError(message)
    return min(position, max(0, duration - 1))


@dataclass(frozen=True)
class ManualSeekQualification:
    """Pin native identity/account and neutral host-observed track revision."""

    original: AudioZoneMetadata
    identity: tuple | None
    revision: int
    duration: float

    def is_current(
        self, snapshot: AudioZoneMetadata | None, *, identity: tuple | None, revision: int,
        duration: float | None, enabled: bool,
    ) -> bool:
        """Leave only lifecycle/request liveness to the host availability callback."""
        return bool(
            enabled and manual_seek_supported(snapshot)
            and identity == self.identity and revision == self.revision and duration == self.duration
            and native_track_identity(snapshot) == self.identity
            and snapshot.player_id == self.original.player_id
            and snapshot.source == self.original.source
            and snapshot.source_name == self.original.source_name
        )


@dataclass(frozen=True)
class SourceRoute:
    """A native completion or retained opaque item qualified for one dispatch."""

    original: AudioZoneMetadata | None
    target: RadioTarget
    media_id: str | None


class SourceContentRequiredError(ValueError):
    """A discovered source has no qualified return content; host may translate."""


async def async_source_route(
    commands: AudioServerCommands, metadata: AudioMetadataCoordinator, catalogue: AudioCatalogue,
    player_id: int, source: str, *, is_current: Callable[[], bool],
    ensure_snapshot: Callable[[], Awaitable[None]],
    resume_native: Callable[[RadioTarget], Awaitable[NativeResumeOutcome]],
    native_is_available: Callable[[], bool], on_target: Callable[[RadioTarget], None],
    environment: SourceEnvironment | None = None,
) -> SourceRoute:
    """Resolve native-session versus retained content without owning HA tasks."""
    original = metadata.get(player_id)

    hint = catalogue.source_choices.get(source) or catalogue.source_descriptors.get(source)

    if (
        getattr(hint, "service", None) != "spotify"
        and (source not in catalogue.source_choices or original is None)
        and not catalogue.source_session_known(source)
    ):
        try:
            await catalogue.async_source_selection(source)
        except ValueError:
            message = "Choose content explicitly in Browse before selecting this source"
            raise SourceContentRequiredError(message) from None
        if not is_current() or not (
            (original is None and metadata.get(player_id) is None)
            or native_selection_unchanged(original, metadata.get(player_id))
        ):
            message = "Source return was superseded before native dispatch"
            raise AudioCommandError(message)
    await ensure_snapshot()
    original = metadata.get(player_id)
    target = catalogue.source_choices.get(source)
    if target is None:
        descriptor = catalogue.source_descriptors.get(source)
        if descriptor is None:
            message = "Source selection is unavailable"
            raise AudioCommandError(message)
        target = CatalogueTarget("item", source, descriptor.service, account=descriptor.account)

    on_target(target)
    outcome = await async_optional_native_resume(
        commands, metadata, player_id, target, resume_native, is_current=is_current,
    )
    native_done = outcome is NativeResumeOutcome.COMPLETE
    if not native_done and isinstance(target, CatalogueTarget) and target.service == "spotify":
        native_done = await async_native_catalogue_noop(
            commands, metadata, player_id, target, is_available=native_is_available, resume_paused=True,
            environment=environment,
        )
    if native_done:
        catalogue.remember_source(metadata.get(player_id))
        return SourceRoute(original, target, None)
    try:
        media_id = await catalogue.async_source_return(source)
    except ValueError:
        message = "Choose content explicitly in Browse before selecting this source"
        raise SourceContentRequiredError(message) from None
    if not is_current() or not native_selection_unchanged(original, metadata.get(player_id)):
        message = "Source return was superseded before native dispatch"
        raise AudioCommandError(message)
    return SourceRoute(original, target, media_id)
