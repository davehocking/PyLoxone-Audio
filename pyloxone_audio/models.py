"""Neutral catalogue DTOs; HA serialization and enums belong to the host."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MediaKind(StrEnum):
    """Kinds actually emitted by the existing native catalogues."""

    ALBUM = 'album'
    ARTIST = 'artist'
    CHANNEL = 'channel'
    DIRECTORY = 'directory'
    EPISODE = 'episode'
    PLAYLIST = 'playlist'
    PODCAST = 'podcast'
    TRACK = 'track'


@dataclass(kw_only=True)
class MediaNode:
    """Bounded discovered navigation/play item, not an HA UI object.

    Mutable while the catalogue assembles provider-specific capabilities. Opaque
    IDs remain room-local; a node is not permission to issue arbitrary commands.
    """

    media_class: MediaKind | str
    media_content_id: str
    media_content_type: str
    title: str
    can_play: bool
    can_expand: bool
    children: list[MediaNode] | None = None
    children_media_class: MediaKind | str | None = None
    thumbnail: str | None = None
    not_shown: int = 0
    can_search: bool = False
    search_media_classes: list[MediaKind] | None = None


@dataclass(kw_only=True, frozen=True)
class SearchResult:
    """Neutral search results; no HA schema, token/session or UI dependency."""

    result: list[MediaNode]
    version: int = 1
