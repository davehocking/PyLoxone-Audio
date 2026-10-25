"""
Concrete PyLoxone-Audio API, independent of Home Assistant.

Apache-2.0. Version 0.1.0 is a local release candidate, not a published release.
The historical fake-backed facade contract is outside this distribution.
"""
from .announcement import async_send_prepared_announcement
from .catalogue import AudioCatalogue, CatalogueTarget, ConfiguredSource
from .metadata import AudioMetadataCoordinator

from .models import MediaKind, MediaNode, SearchResult
from .native import (
    AudioCommandError,
    AudioEventReceiver,
    AudioServerCommands,
    AudioServerListener,
    AudioZoneMetadata,
    audioserver_uri,
    parse_audio_events,
)
from .sources import (
    AudioFavourite,
    SourceEnvironment,
    async_native_catalogue_noop,
    async_seek_track,
    async_select_catalogue,
    async_select_favourite,
    async_select_radio_station,
    passive_history_eligible,
)
from .selection import (
    ManualSeekQualification,
    NativeResumeOutcome,
    SourceContentRequiredError,
    SourceRoute,
    async_source_route,
    async_optional_native_resume,
    confirmed_library_session,
    manual_seek_position,
    manual_seek_supported,
    native_track_identity,
)
from .spotify import (
    NativeSessionUnavailableError,
    SpotifyNativeSession,
    SpotifySessionBridge,
    async_resume_native_session,
)

__all__ = [
    "AudioCatalogue",
    "AudioCommandError",
    "AudioEventReceiver",
    "AudioFavourite",
    "AudioMetadataCoordinator",
    "AudioServerCommands",
    "AudioServerListener",
    "AudioZoneMetadata",
    "CatalogueTarget",
    "ConfiguredSource",
    "ManualSeekQualification",
    "MediaKind",
    "MediaNode",
    "NativeResumeOutcome",
    "NativeSessionUnavailableError",
    "SearchResult",
    "SourceContentRequiredError",

    "SourceEnvironment",
    "SourceRoute",
    "SpotifyNativeSession",
    "SpotifySessionBridge",
    "async_native_catalogue_noop",
    "async_optional_native_resume",
    "async_resume_native_session",
    "async_seek_track",
    "async_select_catalogue",
    "async_select_favourite",
    "async_select_radio_station",
    "async_send_prepared_announcement",
    "async_source_route",
    "audioserver_uri",
    "confirmed_library_session",

    "manual_seek_position",
    "manual_seek_supported",
    "native_track_identity",
    "parse_audio_events",
    "passive_history_eligible",
]
