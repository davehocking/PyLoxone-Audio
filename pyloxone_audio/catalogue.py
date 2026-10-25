"""
Native sources and indexed search on existing opted-in AudioZoneV2 players.

The legacy radio content type/opaque IDs remain accepted. Nothing here starts
playback, scans storage, creates favourites or performs Spotify session import.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from aiohttp import ClientError
from .models import MediaNode as BrowseMedia, SearchResult as SearchMedia, MediaKind as MediaClass

from .radio import _FAVOURITES, _ROOT, RadioCatalogue, RadioTarget, _text
from .sources import parse_spotify_accounts, source_matches

from .native import AudioCommandError

if TYPE_CHECKING:
    from .native import AudioServerCommands, AudioZoneMetadata

_RADIO = "pyloxone-audio:radio"
_INPUTS = "pyloxone-audio:inputs"
_LINE_IN_ARTWORK = "pyloxone-artwork:line-in"
_LIBRARY_ARTWORK = "pyloxone-artwork:library"
BROWSE_ARTWORK = {
    _LINE_IN_ARTWORK: (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 160">'
        b'<rect width="160" height="160" rx="20" fill="#183341"/>'
        b'<g transform="rotate(40 80 80)" fill="#d8f4ff"><rect x="70" y="17" width="20" height="65" rx="6"/>'
        b'<path d="M66 85h28v25a14 14 0 0 1-28 0z"/><path d="M76 115h8v30h-8z"/></g>'
        b'<path d="m99 34 13 11m-22 0 13 11" stroke="#183341" stroke-width="5"/></svg>'
    ),
    _LIBRARY_ARTWORK: (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 160">'
        b'<rect width="160" height="160" rx="20" fill="#183b34"/>'
        b'<path d="M24 45h43l13 14h56v65H24z" fill="#90d5ba"/>'
        b'<path d="M91 72v33a9 9 0 1 1-6-9V78l27-6v26a9 9 0 1 1-6-9V68z" fill="#183b34"/></svg>'
    ),
}
_MAX_INPUTS = 128
_NATIVE_LINE_IN = 6
_NATIVE_PLAYLIST = 11
_MAX_NATIVE_TOTAL = 1_000_000
_PAGE_SIZE = 50
_MAX_RADIO_ITEMS = 256
_MAX_PROVIDERS = 16
_MAX_CAPABILITIES = 32
_MAX_SEARCH_ITEMS = 1000
_MAX_COVER_URL_LENGTH = 4096
_CONTROL_CHAR_BOUNDARY = 32
_MAX_RECENT_ITEMS = 256
_LOGGER = logging.getLogger(__name__)
_CATEGORIES = {
    "local": ("track", "album", "artist", "playlist", "folder"),
    "spotify": ("track", "album", "artist", "playlist", "episode", "show"),
    "tunein": ("station", "custom"),
}


@dataclass(frozen=True)
class CatalogueTarget(RadioTarget):
    """Account and context ownership accompany each opaque discovered item."""

    account: str = "nouser"
    is_context: bool = False
    thumbnail: str | None = None
    playlist_group: str | None = None
    group_items: tuple[RadioTarget, ...] = ()
    parent_path: str | None = None
    parent_index: int | None = None
    return_session: AudioZoneMetadata | None = None


@dataclass(frozen=True)
class ConfiguredSource:
    """Provider/account/input presence, never an implicit content selection."""

    service: str
    account: str = ""
    input_id: str = ""


def _cover_url(row: dict) -> str | None:
    """Keep supplied HTTP artwork, never active/data/credential-bearing URLs."""
    for field in ("thumbnail", "coverurl"):
        value = row.get(field)
        if (
            not isinstance(value, str)
            or not value
            or len(value) > _MAX_COVER_URL_LENGTH
            or any(ord(c) < _CONTROL_CHAR_BOUNDARY for c in value)
        ):
            continue
        try:
            parsed = urlsplit(value)
            if (
                (
                    (parsed.scheme in ("http", "https") and parsed.hostname)
                    or (not parsed.scheme and value.startswith("/"))
                )
                and parsed.username is None
                and parsed.password is None
            ):
                return value
        except ValueError:
            continue
    return None


def parse_line_inputs(payload: object) -> tuple[CatalogueTarget, ...]:
    """Require a complete exact native input ID, never a bare linein command."""
    if not isinstance(payload, list) or len(payload) > _MAX_INPUTS:
        msg = "Native input discovery is invalid or exceeds its bound"
        raise ValueError(msg)
    result, seen = [], set()
    for row in payload:
        if not isinstance(row, dict) or row.get("type") != _NATIVE_LINE_IN:
            msg = "Native input discovery contains an invalid input"
            raise ValueError(msg)
        identifier = _text(row.get("id"), 256)
        if identifier in seen or row.get("cmd") != "linein/" + identifier:
            msg = "Native input identity is ambiguous"
            raise ValueError(msg)
        seen.add(identifier)
        if row.get("valid", True) is False or row.get("power", "on") != "on":
            continue
        if row.get("valid", True) is not True:
            msg = "Native input validity is unknown"
            raise ValueError(msg)
        result.append(
            CatalogueTarget(
                "input", _text(row.get("name"), 256), "linein", identifier, audio_path="linein:" + identifier
            )
        )
    return tuple(result)


class AudioCatalogue(RadioCatalogue):
    """Reuse bounded per-room selections and existing radio discovery."""

    def __init__(self, commands: AudioServerCommands, player_id: int) -> None:
        """Retain the same client, opt-in boundary and room-local ID cache."""
        super().__init__(commands, player_id)
        self.source_choices: dict[str, RadioTarget] = {}
        self.source_descriptors: dict[str, ConfiguredSource] = {}
        self._source_inventory_revision = 0
        self.source_inventory_complete = False
        self._source_refresh_generation = 0
        self._source_content_revision = 0
        self._source_choice_versions: dict[str, int] = {}
        self._source_accounts: list[dict] = []
        self._source_inputs: tuple[CatalogueTarget, ...] = ()
        self.source_sessions: dict[ConfiguredSource, AudioZoneMetadata] = {}
        self._unavailable_source_sessions: set[ConfiguredSource] = set()
        self._session_labels: dict[str, ConfiguredSource] = {}

    def source_session_known(self, source: str) -> bool:
        descriptor = self.source_descriptors.get(source)
        return descriptor in self.source_sessions or descriptor in self._unavailable_source_sessions

    def source_session(self, source: str) -> AudioZoneMetadata | None:
        """Resolve captured sessions by configured identity, never display label."""
        descriptor = self.source_descriptors.get(source)
        return self.source_sessions.get(descriptor) if descriptor is not None else None

    def _source_label(  # noqa: PLR0911 - explicit provider namespaces
        self, target: RadioTarget, *, accounts: list[dict] | None = None,
        inputs: tuple[CatalogueTarget, ...] | None = None,
    ) -> str | None:
        accounts = self._source_accounts if accounts is None else accounts
        inputs = self._source_inputs if inputs is None else inputs
        if target.audio_path.startswith("tunein:"):
            return "TuneIn"
        if target.audio_path.startswith("loxoneradio:"):
            return "Loxone Radio"
        if target.service in ("library", "playlist"):
            return "Local Library"
        if target.service == "linein":
            if not any(item.folder == target.folder for item in inputs):
                return None
            return "Line-In" if len(inputs) == 1 else "Line-In · " + target.label + " · " + target.folder
        if isinstance(target, CatalogueTarget) and target.service == "spotify":
            if target.account not in [account["id"] for account in accounts]:
                return None
            if len(accounts) == 1:
                return "Spotify"
            account = next((a for a in accounts if a["id"] == target.account), None)
            if account:
                return "Spotify · " + _text(account.get("name") or account["id"], 256) + " · " + account["id"]
        return None

    def _recent_target(  # noqa: PLR0911 - reject unknown or unscoped native paths
        self, row: dict, *, accounts: list[dict] | None = None,
        inputs: tuple[CatalogueTarget, ...] | None = None,
    ) -> RadioTarget | None:
        accounts = self._source_accounts if accounts is None else accounts
        inputs = self._source_inputs if inputs is None else inputs
        path = row.get("audiopath")
        if not isinstance(path, str) or not path or row.get("title", row.get("name")) == ".private":
            return None
        path = _text(path)
        label = _text(row.get("title") or row.get("name") or "Last selection", 256)
        if path.startswith(("linein:", "linein/")):
            return next(
                (item for item in inputs if item.audio_path == path.replace("linein/", "linein:", 1)), None
            )
        if path.startswith(("tunein:", "loxoneradio:")):
            if not path.partition(":")[2].strip():
                return None
            service = (
                "loxoneradio"
                if path.startswith("loxoneradio:")
                else "custom"
                if path.startswith("tunein:custom:")
                else "world"
            )
            return RadioTarget("station", label, service, audio_path=path)
        if match := re.fullmatch(r"spotify@([A-Za-z0-9_.@+-]{1,128}):.+", path):
            if match[1] not in [a["id"] for a in accounts]:
                return None
            return self._parse_source_item({**row, "id": path, "name": label}, "spotify", match[1])
        if path.startswith("library:local:"):
            return self._parse_source_item({**row, "id": path, "name": label}, "library")
        return None

    def _source_root_available(self, payload: object, service: str, account: str) -> bool:
        page = self._page(payload, 0, library_root=service == "library")
        rows = [row for row in page["items"] if not isinstance(row, dict) or row.get("name") != ".private"]
        items = [self._parse_source_item(row, service, account) for row in rows]
        if rows and not any(items):
            message = "Source root has no supported visible content"
            raise ValueError(message)
        if service == "loxoneradio" and any(
            item is not None and item.audio_path and not item.audio_path.startswith("loxoneradio:")
            for item in items
        ):
            message = "Loxone Radio root contains another provider"
            raise ValueError(message)
        return any(items)

    async def _async_source_inventory(
        self,
    ) -> tuple[list[dict], tuple[CatalogueTarget, ...], dict[str, ConfiguredSource], bool]:
        """Collect one local inventory without publishing partial shared state."""
        accounts = await self._accounts()
        inputs = parse_line_inputs(await self.commands.async_source_inputs())
        descriptors = {}
        for account in accounts:
            target = CatalogueTarget("folder", "", "spotify", account=account["id"])
            descriptors[self._source_label(target, accounts=accounts, inputs=inputs)] = ConfiguredSource(
                "spotify", account["id"]
            )
        for target in inputs:
            descriptors[self._source_label(target, accounts=accounts, inputs=inputs)] = ConfiguredSource(
                "linein", input_id=target.folder
            )
        complete = True
        # Search categories describe searchability, not configured presence.
        # Reuse the bounded native radio-provider parser and catalogue reads.
        if getattr(self.commands, "async_radio_services", None) is not None:
            try:
                radio = await super().async_browse()
            except (AudioCommandError, ValueError, TimeoutError):
                complete = False
                _LOGGER.debug("Configured source discovery: radio inventory unavailable")
            else:
                if any(
                    self.resolve(item.media_content_id).service in ("local", "music", "world", "custom")
                    for item in radio.children[1:]
                ):
                    descriptors["TuneIn"] = ConfiguredSource("tunein")
        # A non-empty, validated root proves available content, not a selected
        # default. Successful empty roots are distinct from failed discovery.
        folder = getattr(self.commands, "async_media_folder", None)
        if folder is not None:
            for service, account, root, label in (
                ("library", "nouser", "0", "Local Library"),
                ("loxoneradio", "noUser", "start", "Loxone Radio"),
            ):
                try:
                    available = self._source_root_available(await folder(service, account, root, 0), service, account)
                except (AudioCommandError, ValueError, TimeoutError):
                    complete = False
                    _LOGGER.debug("Configured source discovery: %s catalogue unavailable", label)
                else:
                    if available:
                        descriptors[label] = ConfiguredSource(service)
        return accounts, inputs, descriptors, complete

    async def async_refresh_sources(self) -> None:
        """Discover presence independently; history supplies optional content only."""
        self._source_refresh_generation += 1
        generation = self._source_refresh_generation
        content_revision = self._source_content_revision

        accounts, inputs, descriptors, complete = await self._async_source_inventory()
        if generation != self._source_refresh_generation:
            message = "Source inventory refresh was superseded"
            raise AudioCommandError(message)
        # A display label rebound to a replacement account is not a fresh
        # default selection. Require a new qualified sample for that identity.
        known = set(self.source_sessions) | self._unavailable_source_sessions
        self._session_labels.update({
            label: identity for label, identity in self.source_descriptors.items() if identity in known
        })
        # Keep the last known association across an empty/removed inventory.
        for label, old_identity in self._session_labels.items():
            new_identity = descriptors.get(label)
            if old_identity in known and new_identity is not None and new_identity != old_identity:
                self._unavailable_source_sessions.add(new_identity)
        self._source_accounts, self._source_inputs = accounts, inputs
        self.source_inventory_complete = complete
        self.source_descriptors = dict(sorted(
            descriptors.items(), key=lambda item: (item[1].service == "linein", item[0])
        ))
        self.source_choices = {
            label:target for label,target in self.source_choices.items()
            if label in descriptors and self._source_label(target, accounts=accounts, inputs=inputs) == label
        }
        self._source_inventory_revision += 1

        recent = await self.commands.async_recent_sources(self.player_id)

        if generation != self._source_refresh_generation:
            message = "Source history refresh was superseded"
            raise AudioCommandError(message)
        if (
            not isinstance(recent, dict)
            or not isinstance(recent.get("items"), list)
            or len(recent["items"]) > _MAX_RECENT_ITEMS
            or any(not isinstance(row, dict) for row in recent["items"])
        ):
            message = "Native recent sources are unavailable or exceed their bound"
            raise ValueError(message)
        choices = {}
        for row in recent["items"]:
            target = self._recent_target(row, accounts=accounts, inputs=inputs)
            if (
                target is not None
                and (label := self._source_label(target, accounts=accounts, inputs=inputs)) is not None
            ):
                choices.setdefault(label, target)
        for target in inputs:
            choices[self._source_label(target, accounts=accounts, inputs=inputs)] = target
        choices.update({
            label: target for label,target in self.source_choices.items()
            if label in descriptors and label in self._source_choice_versions
        })
        self.source_choices = dict(sorted(choices.items()))

    def remember_source(
        self, snapshot: AudioZoneMetadata | None, *, intent: RadioTarget | None = None, accept: bool = True,
        position_confirmed: bool = False,
    ) -> str | None:
        """Keep last successful playback separately from the current intent."""
        if not accept or snapshot is None or snapshot.source not in (
            "Local Library", "Spotify", "TuneIn", "Loxone Radio", "Line-In",
        ):
            return None
        if snapshot.source in ("Local Library", "Spotify"):
            try:
                path = _text(snapshot.audio_path)
            except ValueError:
                return None
            prefixes = (
                ("spotify:track:", "spotify:episode:")
                if snapshot.source == "Spotify" else ("library:local:track:",)
            )
            if not any(path.startswith(prefix) and path[len(prefix):].strip() for prefix in prefixes):
                return None
        if intent is not None:
            favourite = intent.favourite
            path = favourite.audio_path if favourite is not None else intent.audio_path
            is_context = favourite.is_context if favourite is not None else getattr(intent, "is_context", False)
            # Reuse the same validated path/account parser as other native
            # selections; a favourite carries its account in its exact path.
            qualified = (
                self._recent_target({"audiopath": path, "type": 7 if is_context else 2})
                if favourite is not None and path.startswith("spotify@") else intent
            )
            if qualified is None:
                return None
            users = {row.get("user") for row in self._source_accounts if row.get("id") == getattr(qualified, "account", None)}
            user = next(iter(users)) if len(users) == 1 else None
            if not path or not source_matches(snapshot, path, is_context=is_context, account_user=user):
                return None
            if getattr(intent, "parent_path", None) is not None and snapshot.parent_id != intent.parent_path:
                return None
        if (
            snapshot.player_id == self.player_id and snapshot.event_idle
            and snapshot.event_active is False and snapshot.source in ("Local Library", "Spotify")
            and snapshot.audio_path is not None
            and snapshot.audio_path.startswith(
                ("library:local:track:", "spotify:track:", "spotify:episode:")
            )
        ):
            identity = None
            if snapshot.source == "Local Library":
                identity = ConfiguredSource("library")
            else:
                accounts = [a for a in self._source_accounts if a.get("user") == snapshot.source_name]
                if len(accounts) == 1:
                    identity = ConfiguredSource("spotify", accounts[0]["id"])
            if identity is not None:
                previous = self.source_sessions.get(identity)
                newer = (
                    previous is None or previous.received_at is None
                    or (snapshot.received_at is not None and snapshot.received_at > previous.received_at)
                )
                if not newer:
                    return None
                same_item = (
                    previous is not None
                    and snapshot.audio_path == previous.audio_path
                    and snapshot.source_name == previous.source_name
                    and snapshot.parent_id == previous.parent_id
                )
                paused_enrichment = snapshot.native_mode == "pause" and same_item
                if newer and (snapshot.native_mode == "play" or paused_enrichment):
                    if same_item and (snapshot.position is None or (snapshot.position == 0 and not position_confirmed)):
                        # Missing/zero passive offsets cannot erase a confirmed
                        # clock, even across mixed placeholder sequences. The
                        # actual observed explicit seek may confirm genuine zero.
                        snapshot = replace(
                            snapshot, position=previous.position,
                            position_updated_at=previous.position_updated_at,
                        )
                    self.source_sessions[identity] = snapshot
                    self._unavailable_source_sessions.discard(identity)
        if (
            snapshot is None
            or snapshot.player_id != self.player_id
            or not snapshot.event_idle
            or snapshot.event_active is not False
            or snapshot.native_mode != "play"
        ):
            return None
        path = snapshot.parent_id or snapshot.audio_path
        if not path:
            return None
        if path.startswith("spotify:"):
            accounts = [a for a in self._source_accounts if a.get("user") == snapshot.source_name]
            if len(accounts) != 1:
                return None
            path = "spotify@" + accounts[0]["id"] + ":" + path.removeprefix("spotify:")
        context = bool(snapshot.parent_id) or any(
            mark in path for mark in (":playlist:", ":album:", ":artist:", ":folder:", ":user:collection", ":show:")
        )
        target = self._recent_target(
            {
                "audiopath": path,
                "type": 7 if context else 2,
                "title": snapshot.title or snapshot.source or "Last selection",
                "coverurl": snapshot.cover_url,
            }
        )
        if target is not None and (label := self._source_label(target)) is not None:
            if snapshot.source not in ("Local Library", "Spotify"):
                descriptor = self.source_descriptors.get(label)
                previous = self.source_sessions.get(descriptor)
                if previous is not None and previous.received_at is not None and (
                    snapshot.received_at is None or snapshot.received_at <= previous.received_at
                ):
                    return None
                if descriptor is not None:
                    self.source_sessions[descriptor] = snapshot
            self._source_content_revision += 1
            self._source_choice_versions[label] = self._source_content_revision
            self.source_choices[label] = target
            self.source_choices = dict(sorted(self.source_choices.items()))
            return label
        return None

    async def async_source_selection(self, source: str, *, retained: RadioTarget | None = None) -> str:
        """Refresh an advertised provider's exact last native selection before play."""
        if source not in self.source_choices and source not in self.source_descriptors:
            message = "Source was not discovered; use Browse to select content first"
            raise ValueError(message)
        revision = self._source_inventory_revision
        refresh_generation = self._source_refresh_generation + 1
        advertised = self.source_descriptors.get(source)
        try:
            await self.async_refresh_sources()
        except (AudioCommandError, ValueError, TimeoutError):
            descriptor = self.source_descriptors.get(source)
            if (
                self._source_refresh_generation != refresh_generation
                or self._source_inventory_revision != revision + 1
                or descriptor is None or descriptor.service != "linein"
                or descriptor != advertised
            ):
                raise
            # Fresh input inventory, not stale history or an invented default.
            target = next(item for item in self._source_inputs if item.folder == descriptor.input_id)
            self.source_choices[source] = target
            return self._item(target).media_content_id
        if advertised is not None and self.source_descriptors.get(source) != advertised:
            message = "Configured source identity changed; choose the source again"
            raise ValueError(message)
        if (
            source not in self.source_choices
            and isinstance(retained, CatalogueTarget)
            and retained.service == "spotify"
            and self._source_label(retained) == source
            and retained.account in [account["id"] for account in self._source_accounts]
        ):
            # Only omitted history may use the captured choice; a freshly
            # discovered newer last selection always wins.
            self.source_choices[source] = retained
        if source not in self.source_descriptors or source not in self.source_choices:
            message = "Choose content explicitly in Browse before selecting this source; no content was sent"
            raise ValueError(message)
        return self._item(self.source_choices[source]).media_content_id

    async def async_source_return(self, source: str, *, retained: RadioTarget | None = None) -> str:
        """Keep exact-room playback separately from discovery/history choices."""
        session = self.source_session(source)
        if self.source_descriptors.get(source) in self._unavailable_source_sessions:
            raise AudioCommandError("Latest exact-room source session is unavailable")
        if session is None:
            return (
                await self.async_source_selection(source)
                if retained is None else await self.async_source_selection(source, retained=retained)
            )
        advertised = self.source_descriptors.get(source)
        revision = self._source_inventory_revision
        generation = self._source_refresh_generation + 1
        try:
            await self.async_refresh_sources()
        except (AudioCommandError, ValueError, TimeoutError):
            # A positively revalidated provider plus this room's actual session
            # does not require recent-history content to be readable as well.
            if (
                advertised is None or self.source_descriptors.get(source) != advertised
                or self._source_inventory_revision != revision + 1
                or self._source_refresh_generation != generation
            ):
                raise
        if advertised is None or self.source_descriptors.get(source) != advertised:
            raise AudioCommandError("Configured source identity changed")
        if self.source_session(source) is not session:
            raise AudioCommandError("Source session changed during preparation")
        if session.source not in ("Local Library", "Spotify"):
            target = self._recent_target({
                "audiopath": session.parent_id or session.audio_path,
                "type": 2,
                "title": session.title or source,
            })
            if target is None or self._source_label(target) != source:
                raise AudioCommandError("Prior native source identity is unavailable")
            return self._item(target).media_content_id
        descriptor = self.source_descriptors.get(source)
        service, account = "library", "nouser"
        prefix = "library:local:"
        if session.source == "Spotify":
            if descriptor is None or descriptor.service != "spotify":
                raise AudioCommandError("Prior Spotify account is no longer configured")
            service, account, prefix = "spotify", descriptor.account, "spotify:"
            accounts = [a for a in self._source_accounts if a.get("id") == account and a.get("user") == session.source_name]
            if len(accounts) != 1:
                raise AudioCommandError("Prior Spotify account changed")
        path = session.audio_path
        if not path or not path.startswith((prefix + "track:", prefix + "episode:")):
            raise AudioCommandError("Prior source track identity is unavailable")
        parent, index = session.parent_id, None
        if parent and not parent.startswith(prefix):
            parent = None
        if parent:
            async def read_listing() -> list[str]:
                listing, offset, total = [], 0, None
                while total is None or offset < total:
                    page = self._page(await self.commands.async_media_folder(service, account, parent, offset), offset)
                    if (
                        page["totalitems"] > _MAX_SEARCH_ITEMS
                        or (total is not None and total != page["totalitems"])
                        or (page.get("audiopath") is not None and page["audiopath"] != parent)
                    ):
                        raise AudioCommandError("Prior context changed or exceeds its cursor bound")
                    total = page["totalitems"]
                    for row in page["items"]:
                        item = self._parse_source_item(row, service, account)
                        if (
                            item is None or item.kind != "item" or item.is_context
                            or row.get("type") != 2 or row.get("unplayable", False) is not False
                        ):
                            raise AudioCommandError("Prior context contains a non-playable track row")
                        command_path, observed_path = item.folder, item.audio_path
                        if service == "spotify":
                            account_prefix = "spotify@" + account + ":"
                            command_path = command_path.replace(account_prefix, "spotify:", 1)
                            observed_path = observed_path.replace(account_prefix, "spotify:", 1)
                        if (
                            command_path != observed_path
                            or not observed_path.startswith((prefix + "track:", prefix + "episode:"))
                        ):
                            raise AudioCommandError("Prior context track identities conflict")
                        listing.append(observed_path)
                    offset += len(page["items"])
                    if self.source_session(source) is not session:
                        raise AudioCommandError("Source session changed during cursor lookup")
                return listing

            # Context is optional enrichment, not permission to try this exact
            # last-good item. No send has happened during this bounded lookup.
            try:
                async with asyncio.timeout(10):
                    listing = await read_listing()
                    if listing != await read_listing():
                        raise AudioCommandError("Prior context order changed during cursor lookup")
                if listing.count(path) != 1:
                    raise AudioCommandError("Prior library track cursor is missing or ambiguous")
                index = listing.index(path)
            except (AudioCommandError, ValueError, TimeoutError, ClientError):
                parent = None
        if self.source_session(source) is not session:
            raise AudioCommandError("Source session changed during preparation")
        return self._item(CatalogueTarget(
            "item", session.title or "Last track", service, path, audio_path=path, account=account,
            parent_path=parent, parent_index=index, return_session=session,
        )).media_content_id

    @staticmethod
    def _parse_item(row: object, service: str) -> RadioTarget | None:
        """Preserve supplied radio covers without changing folder dispatch."""
        target = RadioCatalogue._parse_item(row, service)  # noqa: SLF001
        if target is None or target.kind != "station":
            return target
        return CatalogueTarget(
            target.kind,
            target.label,
            target.service,
            target.folder,
            audio_path=target.audio_path,
            thumbnail=_cover_url(row),
        )

    def _item(self, target: RadioTarget) -> BrowseMedia:
        item = super()._item(target)
        if target.kind == "favourite" and target.favourite is not None:
            item.media_class = self._item_class(replace(target, audio_path=target.favourite.audio_path))
        if isinstance(target, CatalogueTarget):
            item.thumbnail = self._artwork(target)
            item.can_play = target.kind in ("station", "item", "input") or target.is_context
            item.can_expand = target.kind in ("folder", "search_group")
            item.can_search = target.kind == "folder"
            if target.service in ("library", "spotify", "playlist"):
                item.media_class = MediaClass.PLAYLIST if target.service == "playlist" else self._item_class(target)
            elif target.kind == "input":
                item.media_class = MediaClass.CHANNEL
            if target.kind == "search_group":
                item.media_class = MediaClass.DIRECTORY
                item.can_play = False
                item.children_media_class = self._item_class(target.group_items[0]) if target.group_items else None
            elif target.service in ("library", "spotify") and item.can_expand:
                item.search_media_classes = [
                    MediaClass.TRACK,
                    MediaClass.ALBUM,
                    MediaClass.ARTIST,
                    MediaClass.PLAYLIST,
                ]
                item.search_media_classes.extend(
                    [MediaClass.PODCAST, MediaClass.EPISODE] if target.service == "spotify" else [MediaClass.DIRECTORY]
                )
        return item

    @staticmethod
    def _artwork(target: CatalogueTarget) -> str | None:
        """Prefer real covers; never invent album art when a folder has none."""
        if target.thumbnail:
            return target.thumbnail
        if target.service == "linein":
            return _LINE_IN_ARTWORK
        if target.service in ("library", "playlist"):
            return _LIBRARY_ARTWORK
        return None

    def artwork(self, content_id: str) -> str | None:
        """Resolve existing room-local media IDs, not caller supplied URLs."""
        if content_id == _INPUTS:
            return _LINE_IN_ARTWORK
        target = self.resolve(content_id)
        return self._artwork(target) if isinstance(target, CatalogueTarget) else None

    @staticmethod
    def _item_class(target: RadioTarget) -> MediaClass:
        if target.audio_path.startswith(("tunein:", "loxoneradio:", "linein:", "linein/")):
            return MediaClass.CHANNEL
        kind = target.audio_path.split(":")[-2] if ":" in target.audio_path else ""
        return {
            "track": MediaClass.TRACK,
            "album": MediaClass.ALBUM,
            "artist": MediaClass.ARTIST,
            "playlist": MediaClass.PLAYLIST,
            "show": MediaClass.PODCAST,
            "episode": MediaClass.EPISODE,
        }.get(kind, MediaClass.DIRECTORY)

    def _group_spotify(self, children: list[BrowseMedia]) -> list[BrowseMedia]:
        groups: dict[str, list[RadioTarget]] = {}
        labels = {
            MediaClass.TRACK: "Tracks",
            MediaClass.ALBUM: "Albums",
            MediaClass.ARTIST: "Artists",
            MediaClass.PLAYLIST: "Other playlists",
            MediaClass.PODCAST: "Podcasts",
            MediaClass.EPISODE: "Episodes",
        }
        for child in children:
            target = self.resolve(child.media_content_id)
            label = (
                target.playlist_group
                if isinstance(target, CatalogueTarget) and target.playlist_group
                else labels.get(child.media_class, "Other results")
            )
            groups.setdefault(label, []).append(target)
        return [
            self._item(
                CatalogueTarget(
                    "search_group",
                    label,
                    group_items=tuple(items),
                    thumbnail=items[0].thumbnail if isinstance(items[0], CatalogueTarget) else None,
                )
            )
            for label, items in groups.items()
        ]

    async def _accounts(self) -> list[dict]:
        rows = await self.commands.async_service_accounts()
        accounts = parse_spotify_accounts(rows)
        return [
            row
            for row in rows
            if row.get("cmd") == "spotify" and row.get("id") in accounts and row.get("configerror") is False
        ]

    async def async_browse(self, content_id: str | None = None) -> BrowseMedia:  # noqa: PLR0911 - native source dispatch
        """Browse native catalogues; all selections remain deliberate play actions."""
        if content_id == _FAVOURITES:
            return await super().async_browse(content_id)
        if content_id in (None, "", _ROOT):
            children = [self._directory(_FAVOURITES, "Room favourites", []), self._directory(_RADIO, "Radio", [])]
            children.extend(
                [
                    self._item(CatalogueTarget("folder", "Loxone Radio", "loxoneradio", "start", account="noUser")),
                    self._item(CatalogueTarget("folder", "Local Library", "library", "0")),
                ]
            )
            for account in await self._accounts():
                label = _text(account.get("name") or account["id"], 256)
                children.append(
                    self._item(
                        CatalogueTarget("folder", "Spotify · " + label, "spotify", "start", account=account["id"])
                    )
                )
            inputs = self._directory(_INPUTS, "Line-In", [])
            inputs.thumbnail = _LINE_IN_ARTWORK
            inputs.can_search = False
            inputs.search_media_classes = None
            children.append(inputs)
            result = self._directory(_ROOT, "Audio sources", children)
            result.search_media_classes = [
                MediaClass.TRACK,
                MediaClass.ALBUM,
                MediaClass.ARTIST,
                MediaClass.PLAYLIST,
                MediaClass.DIRECTORY,
                MediaClass.CHANNEL,
                MediaClass.PODCAST,
                MediaClass.EPISODE,
            ]
            return result
        if content_id == _RADIO:
            root = await super().async_browse()
            return self._directory(_RADIO, "Radio", root.children[1:])
        if content_id == _INPUTS:
            directory = self._directory(
                _INPUTS,
                "Line-In",
                [self._item(item) for item in parse_line_inputs(await self.commands.async_source_inputs())],
            )
            directory.can_search = False
            directory.search_media_classes = None
            return directory
        target = self.resolve(content_id)
        if not isinstance(target, CatalogueTarget):
            return await super().async_browse(content_id)
        if target.kind == "search_group":
            result = self._directory(content_id, target.label, [self._item(item) for item in target.group_items])
            result.can_search = False
            result.search_media_classes = None
            return result
        if target.kind != "folder":
            msg = "Only discovered catalogue folders can be expanded"
            raise ValueError(msg)
        if target.service == "spotify" and target.account not in [a["id"] for a in await self._accounts()]:
            msg = "The linked Spotify account changed; browse again"
            raise ValueError(msg)
        payload = await self.commands.async_media_folder(target.service, target.account, target.folder, target.offset)
        library_root = target.service == "library" and target.folder == "0"
        page = self._page(payload, target.offset, library_root=library_root)
        children = [
            self._item(item)
            for row in page["items"]
            if (item := self._parse_source_item(row, target.service, target.account)) is not None
        ]
        next_offset = target.offset + len(page["items"])
        if target.service == "spotify" and target.folder == "3":
            children = self._group_spotify(children)
        if target.service == "spotify" and target.folder == "start" and target.offset == 0:
            # Installed vendor SpotifyFolder.MyPlaylists is the literal native "3".
            # Saved includes followed playlists; ownership remains separate below.
            children.append(
                self._item(CatalogueTarget("folder", "Saved playlists", "spotify", "3", account=target.account))
            )
        if next_offset < page["totalitems"] or (library_root and len(page["items"]) == _PAGE_SIZE):
            children.append(self._item(replace(target, label="More items…", offset=next_offset, is_context=False)))
        result = self._directory(content_id, target.label, children)
        result.can_play = target.is_context
        result.search_media_classes = self._item(target).search_media_classes
        return result

    @staticmethod
    def _page(payload: object, offset: int, *, library_root: bool = False) -> dict:
        if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
            msg = "Catalogue requires one complete bounded native page"
            raise ValueError(msg)
        page = payload[0]
        rows, total = page.get("items"), page.get("totalitems")
        # This device's Library root returns 21 indexed rows with totalitems=20,
        # including the final row at offset 20. Allow only that observed one-row
        # discrepancy, only at root. Full root pages expose a boundary read so
        # an under-reported total cannot hide their final item. Do not guess
        # which storage object the firmware omitted from its reported count.
        count_margin = int(library_root)
        if (
            type(page.get("start")) is not int
            or page["start"] != offset
            or type(total) is not int
            or not 0 <= total <= _MAX_NATIVE_TOTAL
            or offset > total + count_margin
            or not isinstance(rows, list)
            or len(rows) > _PAGE_SIZE
            or offset + len(rows) > total + count_margin
            or (not rows and offset < total)
        ):
            msg = "Catalogue page changed or is incomplete; browse again"
            raise ValueError(msg)
        return {**page, "totalitems": max(total, offset + len(rows))}

    @staticmethod
    def _parse_source_item(row: object, service: str, account: str = "nouser") -> CatalogueTarget | None:  # noqa: PLR0911, PLR0912
        if not isinstance(row, dict) or type(row.get("type")) is not int:
            msg = "Native catalogue contains an invalid item"
            raise ValueError(msg)
        if row.get("name") == ".private":
            return None
        if service == "loxoneradio":
            result = RadioCatalogue._parse_item(row, service)  # noqa: SLF001 - shared inherited boundary
            if result is None:
                return None
            return CatalogueTarget(
                result.kind,
                result.label,
                service,
                result.folder,
                audio_path=result.audio_path,
                account=account,
                thumbnail=_cover_url(row),
            )
        kind = row["type"]
        if kind not in (1, 2, 3, 7, 11, 12):
            return None
        folder = kind in (1, 3, 7, 11, 12)
        if row.get("unplayable") and not folder:
            return None
        identifier = _text(row.get("id"))
        path = _text(row.get("audiopath") or identifier)
        if service == "spotify":
            prefix = "spotify@" + account + ":"
            identities = (identifier, path)
            if any(not value.startswith((prefix, "spotify:")) for value in identities):
                msg = "Spotify result does not belong to the selected account"
                raise ValueError(msg)
            if identifier.removeprefix(prefix).removeprefix("spotify:") != path.removeprefix(prefix).removeprefix(
                "spotify:"
            ):
                message = "Spotify command and observation identity disagree"
                raise ValueError(message)
            context = folder and row.get("tag") != "category" and not row.get("unplayable", False)
        elif service == "library":
            if kind == _NATIVE_PLAYLIST:
                if not row.get("audiopath") or row.get("unplayable"):
                    return None
                return CatalogueTarget(
                    "item",
                    _text(row.get("name"), 256),
                    "playlist",
                    path,
                    audio_path=path,
                    is_context=True,
                    thumbnail=_cover_url(row),
                )
            if not path.startswith("library:local:"):
                msg = "Library result has no native indexed-library identity"
                raise ValueError(msg)
            context = folder and not row.get("unplayable", False)
        else:
            msg = "Unsupported catalogue provider"
            raise ValueError(msg)
        return CatalogueTarget(
            "folder" if folder else "item",
            _text(row.get("name") or row.get("title"), 256),
            service,
            identifier,
            audio_path=path,
            account=account,
            is_context=context,
            thumbnail=_cover_url(row),
            playlist_group=(
                "Your playlists"
                if row.get("owner_id") == account
                else "Public playlists"
                if row.get("public") is True or row.get("is_public") is True
                else "Other playlists"
            )
            if service == "spotify" and ":playlist:" in path
            else None,
        )

    async def _loxone_radio_search(self, query: str) -> list[BrowseMedia]:
        """Loxone Radio has a bounded native channel list, not a global-search scope."""
        children, offset = [], 0
        while offset < _MAX_RADIO_ITEMS:
            page = self._page(await self.commands.async_media_folder("loxoneradio", "noUser", "start", offset), offset)
            for row in page["items"]:
                item = self._parse_source_item(row, "loxoneradio", "noUser")
                if item and query.casefold() in item.label.casefold():
                    children.append(self._item(replace(item, label="Loxone Radio · " + item.label)))
            offset += len(page["items"])
            if offset == page["totalitems"]:
                return children
        msg = "Loxone Radio search exceeded its bounded native list"
        raise ValueError(msg)

    @staticmethod
    def _search_scopes(capabilities: object, scope: str | None) -> dict[str, tuple[str, ...]]:
        if not isinstance(capabilities, dict) or len(capabilities) > _MAX_PROVIDERS:
            message = "Native search capability discovery failed"
            raise ValueError(message)
        scopes = {}
        for provider, supported in _CATEGORIES.items():
            values = capabilities.get(provider, [])
            if (
                not isinstance(values, list)
                or len(values) > _MAX_CAPABILITIES
                or any(not isinstance(v, str) for v in values)
            ):
                message = "Native search capabilities are malformed"
                raise ValueError(message)
            if scope in (None, provider) and (categories := tuple(c for c in supported if c in values)):
                scopes[provider] = categories
        return scopes

    def _search_items(
        self, results: dict, requested: dict, account: dict | None, *, show_account: bool, show_provider: bool = True
    ) -> list[BrowseMedia]:
        children, seen = [], set()
        account_id = account["id"] if account else None
        for provider, content in results.items():
            if not isinstance(content, dict):
                message = "Malformed native search results"
                raise ValueError(message)  # noqa: TRY004 - normalised untrusted wire validation error
            for category in requested[provider]:
                group = content.get(category + "s", content.get(category))
                if group is None:
                    continue
                if (
                    not isinstance(group, dict)
                    or not isinstance(group.get("items", []), list)
                    or len(group.get("items", [])) > _PAGE_SIZE
                ):
                    message = "Native search category exceeds its bound"
                    raise ValueError(message)
                for row in group.get("items", []):
                    item = (
                        self._parse_item(row, "custom" if category == "custom" else "world")
                        if provider == "tunein"
                        else self._parse_source_item(
                            row,
                            "library" if provider == "local" else "spotify",
                            account_id if provider == "spotify" else "nouser",
                        )
                    )
                    if item is None:
                        continue
                    key = (provider, account_id, item.audio_path or item.folder)
                    if key in seen:
                        continue
                    seen.add(key)
                    label = {"local": "Local Library", "spotify": "Spotify", "tunein": "Radio"}[provider]
                    if provider == "spotify" and show_account:
                        label += " · " + (account.get("name") or account_id)
                    children.append(
                        self._item(replace(item, label=label + " · " + item.label) if show_provider else item)
                    )
        return children

    @staticmethod
    def _bounded_search(items: list[BrowseMedia]) -> list[BrowseMedia]:
        if len(items) > _MAX_SEARCH_ITEMS:
            message = "Native search exceeded its bound; refine the query"
            raise ValueError(message)
        return items

    async def async_search(  # noqa: PLR0912 - explicit native provider and class-filter dispatch
        self,
        query: str,
        content_id: str | None = None,
        *,
        media_filter_classes: list[MediaClass] | None = None,
    ) -> SearchMedia:
        """Root searches all discovered indexed providers; folders restrict provider."""
        query = _text(query, 256)
        if content_id == _INPUTS:
            msg = "Line-In is a direct input, not searchable content"
            raise ValueError(msg)
        if content_id == _FAVOURITES:
            page = await super().async_browse(_FAVOURITES)
            return SearchMedia(
                result=[
                    item
                    for item in page.children
                    if query.casefold() in item.title.casefold()
                    and (not media_filter_classes or item.media_class in media_filter_classes)
                ]
            )
        selected = None if content_id in (None, "", _ROOT, _RADIO) else self.resolve(content_id)
        if selected is not None and selected.kind != "folder":
            msg = "Search must target a discovered provider folder"
            raise ValueError(msg)
        if selected is not None and selected.service == "loxoneradio":
            return SearchMedia(
                result=await self._loxone_radio_search(query)
                if not media_filter_classes or MediaClass.CHANNEL in media_filter_classes
                else []
            )
        capabilities = await self.commands.async_search_capabilities()
        scope = (
            "tunein"
            if content_id == _RADIO
            else {"library": "local", "spotify": "spotify"}.get(selected.service, "tunein")
            if selected
            else None
        )
        scopes = self._search_scopes(capabilities, scope)
        if media_filter_classes:
            category_classes = {
                "track": MediaClass.TRACK,
                "album": MediaClass.ALBUM,
                "artist": MediaClass.ARTIST,
                "playlist": MediaClass.PLAYLIST,
                "folder": MediaClass.DIRECTORY,
                "show": MediaClass.PODCAST,
                "episode": MediaClass.EPISODE,
                "station": MediaClass.CHANNEL,
                "custom": MediaClass.CHANNEL,
            }
            scopes = {
                provider: filtered_categories
                for provider, categories in scopes.items()
                if (
                    filtered_categories := tuple(
                        category for category in categories if category_classes[category] in media_filter_classes
                    )
                )
            }
        selected_spotify = selected is not None and selected.service == "spotify"
        accounts = await self._accounts() if "spotify" in scopes or selected_spotify else []
        if selected and selected.service == "spotify":
            accounts = [a for a in accounts if a["id"] == selected.account]
            if not accounts:
                msg = "Spotify search account is no longer linked"
                raise ValueError(msg)
        if "spotify" not in scopes:
            accounts = []
        if not accounts:
            scopes.pop("spotify", None)
        children = []
        for index, account in enumerate(accounts or [None]):
            requested = scopes if index == 0 else {"spotify": scopes["spotify"]}
            if not requested:
                break
            account_id = account["id"] if account else None
            results = await self.commands.async_global_search(query, requested, spotify_account=account_id)
            if not isinstance(results, dict) or set(results) != set(requested):
                msg = "Native search is incomplete; no partial success returned"
                raise ValueError(msg)
            children.extend(
                self._search_items(
                    results, requested, account, show_account=len(accounts) > 1, show_provider=scope is None
                )
            )
            self._bounded_search(children)
        if scope is None and (not media_filter_classes or MediaClass.CHANNEL in media_filter_classes):
            children.extend(await self._loxone_radio_search(query))
        return SearchMedia(
            result=self._group_spotify(children)
            if scope == "spotify" and not media_filter_classes
            else self._bounded_search(children)
        )
