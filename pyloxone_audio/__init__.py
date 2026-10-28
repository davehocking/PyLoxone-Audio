"""
Concrete PyLoxone-Audio API, independent of Home Assistant.

Apache-2.0. Version 0.1.1 is a local development candidate, not a published release.
The historical fake-backed facade contract is outside this distribution.
"""
from .announcement import async_send_prepared_announcement
from .catalogue import AudioCatalogue, CatalogueTarget, ConfiguredSource
from .metadata import AudioMetadataCoordinator

from .models import MediaKind, MediaNode, SearchResult
from .native import (
    AudioCommandError,
    AudioEventReceiver,
    AudioRepeatMode,
    AudioServerCommands,
    AudioServerListener,
    AudioZoneMetadata,
    audio_mode_supported,
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

    SourceContentRequiredError,
    SourceRoute,
    async_source_route,

    confirmed_library_session,
    manual_seek_position,
    manual_seek_supported,
    native_track_identity,
)


__all__ = [
    "AudioCatalogue",
    "AudioCommandError",
    "AudioEventReceiver",
    "AudioFavourite",
    "AudioMetadataCoordinator",
    "AudioRepeatMode",
    "AudioServerCommands",
    "AudioServerListener",
    "AudioZoneMetadata",
    "CatalogueTarget",
    "ConfiguredSource",
    "ManualSeekQualification",
    "MediaKind",
    "MediaNode",

    "SearchResult",
    "SourceContentRequiredError",

    "SourceEnvironment",
    "SourceRoute",

    "async_native_catalogue_noop",

    "async_seek_track",
    "async_select_catalogue",
    "async_select_favourite",
    "async_select_radio_station",
    "async_send_prepared_announcement",
    "async_source_route",
    "audio_mode_supported",
    "audioserver_uri",
    "confirmed_library_session",

    "manual_seek_position",
    "manual_seek_supported",
    "native_track_identity",
    "parse_audio_events",
    "passive_history_eligible",
]
