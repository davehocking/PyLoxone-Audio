"""Native HA radio browsing over the existing opt-in Audio Server client."""

# ruff: noqa: TRY004 - malformed discovery has one ValueError boundary

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import re
from typing import TYPE_CHECKING
from uuid import uuid4

from .models import MediaNode as BrowseMedia, SearchResult as SearchMedia, MediaKind as MediaClass

from .sources import AudioFavourite, parse_room_favourites

if TYPE_CHECKING:
    from .native import AudioServerCommands

RADIO_MEDIA_TYPE = "pyloxone_radio"
_ROOT = "pyloxone-radio:root"
_FAVOURITES = "pyloxone-radio:favourites"
_PAGE_SIZE = 50
_MAX_ENTRIES = 2048
_MAX_TOTAL = 1_000_000
_MAX_SERVICES = 16
_MAX_SEARCH_RESULTS = 100
_CONTROL_BOUNDARY = 32


def _text(value: object, limit: int = 2048) -> str:
    """Keep observed identifiers literal and reject empty/control-bearing data."""
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > limit
        or any(ord(c) < _CONTROL_BOUNDARY for c in value)
    ):
        message = "Radio catalogue contains an invalid identifier or label"
        raise ValueError(message)
    return value


@dataclass(frozen=True)
class RadioTarget:
    """Only a discovered target can be expanded or selected through HA."""

    kind: str
    label: str
    service: str = ""
    folder: str = ""
    offset: int = 0
    audio_path: str = ""
    favourite: AudioFavourite | None = None


class RadioCatalogue:
    """Retain bounded per-entity identities, not commands supplied by the UI."""

    def __init__(self, commands: AudioServerCommands, player_id: int) -> None:
        """Bind browsing to the same configured client and exact audio zone."""
        self.commands = commands
        self.player_id = player_id
        self.favourites: tuple[AudioFavourite, ...] | None = None
        self._entries: OrderedDict[str, RadioTarget] = OrderedDict()

    def resolve(self, content_id: str) -> RadioTarget:
        """Reject unknown, expired, cross-entity or hand-crafted media IDs."""
        if not isinstance(content_id, str) or content_id not in self._entries:
            message = "Radio selection expired or was not discovered; browse or search again"
            raise ValueError(message)
        self._entries.move_to_end(content_id)
        return self._entries[content_id]

    def _item(self, target: RadioTarget) -> BrowseMedia:
        """Register one discovery result and expose its opaque native HA ID."""
        content_id = "pyloxone-radio:" + uuid4().hex
        self._entries[content_id] = target
        while len(self._entries) > _MAX_ENTRIES:
            self._entries.popitem(last=False)
        playable = target.kind in ("station", "favourite")
        return BrowseMedia(
            media_class=MediaClass.CHANNEL if playable else MediaClass.DIRECTORY,
            media_content_id=content_id,
            media_content_type=RADIO_MEDIA_TYPE,
            title=target.label,
            can_play=playable,
            can_expand=not playable,
            can_search=not playable,
            search_media_classes=[MediaClass.CHANNEL] if not playable else None,
        )

    @staticmethod
    def _directory(content_id: str, title: str, children: list[BrowseMedia]) -> BrowseMedia:
        """Use the standard Home Assistant media-browser contract."""
        return BrowseMedia(
            media_class=MediaClass.DIRECTORY,
            media_content_id=content_id,
            media_content_type=RADIO_MEDIA_TYPE,
            title=title,
            can_play=False,
            can_expand=True,
            can_search=True,
            search_media_classes=[MediaClass.CHANNEL],
            children=children,
        )

    async def async_browse(self, content_id: str | None = None) -> BrowseMedia:
        """Read one provider or one catalogue page; browsing never plays media."""
        if content_id == _FAVOURITES:
            self.favourites = parse_room_favourites(
                await self.commands.async_room_favourites(self.player_id), self.player_id
            )
            children = [self._item(RadioTarget("favourite", item.label, favourite=item)) for item in self.favourites]
            return self._directory(_FAVOURITES, "Room favourites", children)
        if content_id in (None, "", _ROOT):
            services = await self.commands.async_radio_services()
            if services is None:
                services = []
            if not isinstance(services, list) or len(services) > _MAX_SERVICES:
                message = "Radio service discovery is invalid or exceeds its bound"
                raise ValueError(message)
            children = [self._directory(_FAVOURITES, "Room favourites", [])]
            seen = set()
            for service in services:
                if not isinstance(service, dict):
                    message = "Radio service discovery contains an invalid entry"
                    raise ValueError(message)
                command = _text(service.get("cmd"), 32)
                if not re.fullmatch(r"[A-Za-z0-9_-]+", command) or command in seen:
                    message = "Radio service discovery contains an invalid or duplicate service"
                    raise ValueError(message)
                seen.add(command)
                target = RadioTarget("folder", _text(service.get("name"), 256), command, _text(service.get("root")))
                children.append(self._item(target))
            return self._directory(_ROOT, "Radio stations", children)
        target = self.resolve(content_id)
        if target.kind != "folder":
            message = "A radio station cannot be expanded as a folder"
            raise ValueError(message)
        payload = await self.commands.async_radio_folder(target.service, target.folder, target.offset)
        if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
            message = "Radio browsing requires one bounded native page"
            raise ValueError(message)
        page = payload[0]
        items, total = page.get("items"), page.get("totalitems")
        if (
            type(page.get("start")) is not int
            or page["start"] != target.offset
            or type(total) is not int
            or not target.offset <= total <= _MAX_TOTAL
            or not isinstance(items, list)
            or len(items) > _PAGE_SIZE
            or target.offset + len(items) > total
            or (not items and target.offset < total)
        ):
            message = "Radio page changed or is incomplete; browse again"
            raise ValueError(message)
        children = [self._item(item) for row in items if (item := self._parse_item(row, target.service)) is not None]
        offset = target.offset + len(items)
        if offset < total:
            children.append(self._item(RadioTarget("folder", "More stations…", target.service, target.folder, offset)))
        return self._directory(content_id, target.label, children)

    async def async_search(self, query: str) -> SearchMedia:
        """Search native radio stations/custom URLs without external directories."""
        payload = await self.commands.async_radio_search(query)
        if not isinstance(payload, dict) or payload.get("error"):
            message = "Radio search returned an invalid result"
            raise ValueError(message)
        result = payload.get("result", payload)
        if not isinstance(result, dict):
            message = "Radio search returned an invalid result"
            raise ValueError(message)
        children = []
        seen = set()
        for category, service in (("station", "world"), ("custom", "custom")):
            if category not in result:
                continue
            group = result[category]
            if (
                not isinstance(group, dict)
                or not isinstance(group.get("items"), list)
                or len(group["items"]) > _MAX_SEARCH_RESULTS
            ):
                message = "Radio search exceeded its bounded category or returned invalid items"
                raise ValueError(message)
            for row in group["items"]:
                target = self._parse_item(row, service)
                if target is not None and target.kind == "station" and (service, target.audio_path) not in seen:
                    seen.add((service, target.audio_path))
                    children.append(self._item(target))
        return SearchMedia(result=children)

    @staticmethod
    def _parse_item(row: object, service: str) -> RadioTarget | None:
        """Separate actual folders from playable native radio paths."""
        if not isinstance(row, dict) or type(row.get("type")) is not int:
            message = "Radio catalogue contains an invalid item"
            raise ValueError(message)
        kind = row["type"]
        if kind not in (1, 2) or row.get("unplayable", False):
            return None
        label = _text(row.get("name"), 256)
        if kind == 1:
            return RadioTarget("folder", label, service, _text(row.get("id")))
        path = _text(row.get("audiopath"))
        if not path.startswith(("tunein:", "loxoneradio:")) or not path.partition(":")[2].strip():
            message = "Radio catalogue item has no supported native station path"
            raise ValueError(message)
        return RadioTarget("station", label, service, audio_path=path)
