"""
Audioserver metadata/events and explicitly opt-in exact-player playback.

Event shapes follow the author-reported contract in PyLoxone issue #523.
The parser/receiver sends nothing. The optional connection owner performs only
the WebSocket handshake and receives events; it never authenticates or controls.
AudioServerCommands is a separate lazy connection for explicit actions and
opted-in bounded status reconciliation; recovery never sends a media control.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import IntEnum
from http import HTTPStatus
from inspect import signature
from ipaddress import IPv6Address, ip_address
from math import isfinite
from typing import TYPE_CHECKING, Any
from urllib.parse import quote
from uuid import uuid4

from .diagnostic_events import diagnostic_event, diagnostics_enabled

from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Random import get_random_bytes
from Crypto.Util.Padding import pad
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException
from websockets.typing import Subprotocol


if TYPE_CHECKING:
    from collections.abc import AsyncIterable, Awaitable, Callable

_LOGGER = logging.getLogger(__name__)
_MAX_HOSTNAME_LENGTH = 253
_AIRPLAY_ANNOUNCEMENT = 7
# Event names adapted from SebastianEitzert's Apache-2.0 POC in #523,
# comment 6251138699. See tests/fixtures/audioserver/README.md for provenance.
# That historical attribution is retained; current fixture provenance lives at
# tests/library/fixtures/audioserver/README.md in this repository and source archive.
_EVENT_NAMES = {
    1: "doorbell",
    2: "alarm_clock",
    3: "tts",
    5: "custom_sound",
    7: "announcement",
    100: "alarm",
    101: "fire_alarm",
}
# Adapted from the contributor's measured flapping sequence, not a safety signal.
_DEBOUNCED_EVENTS = frozenset({"alarm", "fire_alarm", "alarm_clock"})
_EVENT_END_DELAY = 1.5
_WAV_HEADER_BYTES = 44
_MAX_ANNOUNCEMENT_VOLUME = 100
_FAVOURITE_PAGE_SIZE = 32
_MAX_ROOM_FAVOURITES = 256
_MAX_RADIO_PATH = 2048
_MAX_RADIO_QUERY = 256
_MAX_RADIO_OFFSET = 1_000_000
_CONTROL_BOUNDARY = 32
_MAX_SEARCH_CATEGORIES = 32
# websockets 15 enables environment proxies by default; 14 has no proxy option.
# Keep the declared >=14,<16 range while connecting directly to the selected host.
_DIRECT_CONNECT: dict[str, Any] = {"proxy": None} if "proxy" in signature(connect).parameters else {}


def audioserver_uri(host: str) -> str:
    """Build a fixed-port event origin from a bare hostname or IP address."""
    message = "Audioserver host must be a hostname or IP address without a port or path"
    if not isinstance(host, str) or not host or "%" in host:
        raise ValueError(message)
    bracketed = host.startswith("[") and host.endswith("]")
    address = host[1:-1] if bracketed else host
    try:
        parsed = ip_address(address)
    except ValueError:
        labels = host.removesuffix(".").split(".")
        if len(host) > _MAX_HOSTNAME_LENGTH or not all(
            re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in labels
        ):
            raise ValueError(message) from None
        authority = host
    else:
        is_ipv6 = isinstance(parsed, IPv6Address)
        if bracketed and not is_ipv6:
            raise ValueError(message)
        authority = f"[{address}]" if is_ipv6 else address
    return f"ws://{authority}:7091/"


class AudioRepeatMode(IntEnum):
    """Native queue repeat values (track is 3, not 2)."""

    OFF = 0
    ALL = 1
    ONE = 3


def _shuffle_switch(greeting: object) -> bool | None:
    """Read only versions from the native greeting; never retain its token."""
    if not isinstance(greeting, str) or len(greeting) > 4096:
        return None
    match = re.fullmatch(
        r"LWSS V ([0-9]{1,5}(?:\.[0-9]{1,5}){3}) \| ~API:([0-9]{1,5}(?:\.[0-9]{1,5}){1,3})~ \| Session-Token: [^\r\n]+",
        greeting,
    )
    if match is None:
        return None
    firmware, api = (tuple(int(part) for part in text.split(".")) for text in match.groups())
    return firmware >= (16, 1, 9, 23) and api >= (1, 6)


def _shuffle(value: object) -> bool | None:
    """Decode only explicit native booleans/0/1, never string truthiness."""
    if type(value) is bool:
        return value
    if type(value) is int and value in (0, 1):
        return value == 1
    if type(value) is str and value in ("0", "1"):
        return value == "1"
    return None


def _repeat(value: object) -> AudioRepeatMode | None:
    """Do not silently turn an unknown enum or a bool into a queue mode."""
    return AudioRepeatMode(value) if type(value) is int and value in (0, 1, 3) else None


@dataclass(frozen=True, slots=True)
class AudioZoneMetadata:
    """Metadata for one exact Audioserver player, not a room display name."""

    player_id: int
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    cover_url: str | None = None
    audio_path: str | None = None
    source: str | None = None
    event: str | None = None
    event_active: bool | None = None
    position: float | None = None
    duration: float | None = None
    position_updated_at: datetime | None = None
    playback_mode: str | None = None
    received_at: datetime | None = None
    playback_restrictions: int | None = None
    event_idle: bool = False
    native_mode: str | None = None
    parent_id: str | None = None
    source_name: str | None = None
    shuffle: bool | None = None
    repeat: AudioRepeatMode | None = None
    shuffle_switch_supported: bool | None = None

    @property
    def has_observation(self) -> bool:
        """Distinguish parsed observations from generated timestamp/default fields."""
        return self.event_active is True or any(value is not None for value in (
            self.audio_path, self.title, self.artist, self.album, self.cover_url,
            self.source, self.source_name, self.parent_id, self.native_mode,
            self.event, self.position, self.duration, self.playback_restrictions,
            self.shuffle, self.repeat,
        ))


def audio_mode_supported(
    row: AudioZoneMetadata | None, operation: str, repeat: AudioRepeatMode | None = None,
) -> bool:
    """Use current native permissions and known state, not provider names.

    HA cycles all three repeat modes. Without a per-mode feature contract its
    button is advertised only when both ALL and ONE are available. The typed
    native setter can still validate an explicitly requested partial mode.
    """
    if row is None or not row.event_idle or not row.audio_path or row.playback_restrictions is None:
        return False
    permissions = row.playback_restrictions
    if operation == "shuffle":
        return bool(row.shuffle_switch_supported is True and row.shuffle is not None
                    and row.native_mode == "play" and permissions & 2048)
    if operation == "repeat" and row.repeat is not None and row.native_mode in ("play", "pause"):
        if repeat is None:
            return permissions & (4096 | 8192) == (4096 | 8192)
        return bool(permissions & {AudioRepeatMode.OFF: 4096 | 8192,
                                   AudioRepeatMode.ALL: 4096, AudioRepeatMode.ONE: 8192}[repeat])
    return False


def _no_event(code: object) -> bool:
    """Only absent/null or an integer zero explicitly denotes no event."""
    return code is None or (type(code) is int and code == 0)


def _event_code(row: dict[str, Any]) -> object:
    """Use native events first, with the narrowly reported AirPlay type7 variant."""
    code = row.get("eventype")
    # #523 comment 5984328342 reports AirPlay announcements with type, not
    # eventype. Other sources also use type, so it is NOT a generic event code.
    if (
        _no_event(code)
        and row.get("audiopath") == "airplay"
        and type(row.get("type")) is int
        and row["type"] == _AIRPLAY_ANNOUNCEMENT
    ):
        return _AIRPLAY_ANNOUNCEMENT
    return code


def _event(row: dict[str, Any]) -> tuple[str | None, bool | None]:
    """Qualify events by actual per-zone playback, not broadcast data alone."""
    code = _event_code(row)
    if _no_event(code):
        return None, False
    if type(code) is not int or code < 0:
        return None, None
    mode = row.get("mode")
    if mode == "play":
        return _EVENT_NAMES.get(code, f"event_{code}"), True
    return None, False if mode in ("pause", "stop") else None


def _source(row: dict[str, Any]) -> str | None:
    """Identify reported sources without treating audio type zero as Spotify."""
    path = _text(row.get("audiopath")) or ""
    if path == "airplay":
        return "AirPlay"
    if path.startswith("library:local:track:") and path.removeprefix("library:local:track:").strip():
        return "Local Library"
    for prefix, label in (
        ("spotify:", "Spotify"),
        ("tunein:", "TuneIn"),
        ("loxoneradio:", "Loxone Radio"),
        ("linein:", "Line-In"),
    ):
        if path.startswith(prefix):
            return label
    if not path and (_text(row.get("sourceName")) or "").casefold() == "spotify":
        return "Spotify"
    return None


def _text(value: object) -> str | None:
    """Retain original non-blank strings; reject malformed optional fields."""
    return value if isinstance(value, str) and value.strip() else None


def audio_player_id(value: object) -> int | None:
    """Accept positive numeric IDs without coercing bools or fractional values."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    if isinstance(value, str) and not (value.isascii() and value.isdecimal()):
        return None
    try:
        result = int(value)
    except ValueError:
        return None
    return result if result > 0 else None


def _seconds(value: object) -> float | None:
    """Keep finite non-negative JSON numbers without bool/string coercion."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = float(value)
    except OverflowError:
        return None
    return result if isfinite(result) and result >= 0 else None


def audio_control_command(player_id: object, action: str) -> tuple[str, str]:
    """Build only reviewed player-scoped commands; continuity needs a live test."""
    target = audio_player_id(player_id)
    if target is None or action not in ("play", "pause"):
        message = "Audio playback requires an exact player ID and play/pause action"
        raise ValueError(message)
    return f"audio/{target}/{action}", f"{action}_result"


def parse_audio_events(payload: object) -> tuple[AudioZoneMetadata, ...]:
    """Extract valid independent zone snapshots, ignoring non-event replies."""
    if not isinstance(payload, dict) or not isinstance(payload.get("audio_event"), list):
        return ()
    updates = []
    for row in payload["audio_event"]:
        if not isinstance(row, dict) or (player_id := audio_player_id(row.get("playerid"))) is None:
            continue
        event, event_active = _event(row)
        is_event = not _no_event(_event_code(row))
        # TTS is broadcast to stopped non-target zones too. Neither its title
        # nor its artwork is evidence of that zone playing the interruption.
        display = row if not is_event or event_active is True else {}
        path = _text(row.get("audiopath")) or ""
        timed_track = (
            not is_event
            and row.get("mode") in ("play", "pause", "stop")
            and any(
                path.startswith(prefix) and path.removeprefix(prefix).strip()
                for prefix in ("spotify:track:", "library:local:track:")
            )
        )
        # Only time/duration seconds have an established contract. Do not
        # mix position_ms/progress_ms/duration_ms into a guessed precedence.
        timing = row if timed_track else {}
        duration = _seconds(timing.get("duration")) or None
        position = _seconds(timing.get("time"))
        if duration is None or (position is not None and position > duration):
            position = None
        received_at = datetime.now(UTC)
        updates.append(
            AudioZoneMetadata(
                player_id=player_id,
                title=_text(display.get("title")),
                artist=_text(display.get("artist")),
                album=_text(display.get("album")),
                cover_url=_text(display.get("coverurl")),
                audio_path=_text(display.get("audiopath")),
                source=None if is_event else _source(row),
                parent_id=_text(row["parent"].get("id"))
                if not is_event and isinstance(row.get("parent"), dict)
                else None,
                source_name=_text(row.get("sourceName")) if not is_event else None,
                event=event,
                event_active=event_active,
                event_idle=(
                    not is_event
                    and row.get("mode") in ("play", "pause", "stop")
                    and (
                        (type(row.get("eventype")) is int and row["eventype"] == 0)
                        # Normal native source frames can omit the event field.
                        # Require positive content evidence, never a bare ID/mode.
                        or (
                            _source(row) in {"Spotify", "Local Library", "TuneIn", "Loxone Radio", "Line-In"}
                            and bool(path.partition(":")[2].strip())
                        )
                    )
                ),
                position=position,
                duration=duration,
                position_updated_at=received_at if position is not None else None,
                native_mode=row["mode"] if row.get("mode") in ("play", "pause", "stop") else None,
                playback_mode=row["mode"] if timed_track else None,
                received_at=received_at,
                playback_restrictions=(row["pbr"] if type(row.get("pbr")) is int and row["pbr"] >= 0 else None),
                shuffle=_shuffle(row.get("plshuffle")) if not is_event else None,
                repeat=_repeat(row.get("plrepeat")) if not is_event else None,
            ),
        )
    return tuple(updates)


class AudioCommandError(Exception):
    """A player command was not positively acknowledged; never implies retry."""


class AudioServerCommands:
    """
    Explicit opt-in commands, separate from the receive-only listener.

    Reuse the integration's *current* Miniserver token, not its password or a
    separately stored credential. Each explicit action gets one short-lived,
    authenticated connection. Do not retry writes or fall back to room play:
    room play can replace the selected source with the default favourite.
    Wire contract follows the installed vendor client and the existing native
    SDK's RSA-PKCS1v15/AES-CBC authentication, using existing dependencies only.
    """

    def __init__(self, host: str, credentials: Callable[[], tuple[str, str]], *, timeout: float = 15.0, diagnostics: Any = None) -> None:
        """Create a lazy, serial command client without connecting or sending."""
        self._uri = audioserver_uri(host)
        self._credentials = credentials
        self._timeout = timeout
        self._lock = asyncio.Lock()
        self._closed = False
        self._socket: Any = None
        self.diagnostics = diagnostics
        self.announcement_fences: dict[int, Callable[[], None]] = {}
        self.source_fences: dict[int, Callable[[], None]] = {}
        self.source_observations: dict[int, asyncio.Future[None]] = {}

    async def async_close(self) -> None:
        """Reject queued/future requests and close an in-flight owned socket."""
        self._closed = True
        for release in (*tuple(self.announcement_fences.values()), *tuple(self.source_fences.values())):
            release()
        if self._socket is not None:
            await self._socket.close()

    async def async_execute(
        self, player_id: object, action: str, *, is_current: Callable[[], bool] | None = None,
    ) -> None:
        """Send one exact-player play/pause and require a literal true reply."""
        command, reply_key = audio_control_command(player_id, action)
        if await self._async_request(command, reply_key, is_current=is_current) is not True:
            message = "Audio playback command was not acknowledged"
            raise AudioCommandError(message)

    async def async_set_shuffle(
        self, player_id: object, shuffle: bool, *, is_current: Callable[[], bool],
    ) -> None:
        """Send one explicit enable/disable; never use the legacy shuffle action."""
        target = audio_player_id(player_id)
        if target is None or type(shuffle) is not bool:
            raise ValueError("Shuffle requires an exact player and boolean")
        reply = await self._async_request(
            f"audio/{target}/shuffle/{'enable' if shuffle else 'disable'}", "shuffle_result",
            is_current=is_current, require_shuffle_switch=True,
        )
        if not isinstance(reply, dict) or type(reply.get("shuffle")) is not bool or reply["shuffle"] is not shuffle:
            raise AudioCommandError("Shuffle was not acknowledged with the requested mode; no retry was sent")

    async def async_set_repeat(
        self, player_id: object, repeat: AudioRepeatMode, *, is_current: Callable[[], bool],
    ) -> None:
        """Send the reviewed 0/1/3 enum once; no silent 2-to-3 conversion."""
        target = audio_player_id(player_id)
        if target is None or not isinstance(repeat, AudioRepeatMode):
            raise ValueError("Repeat requires an exact player and AudioRepeatMode")
        reply = await self._async_request(
            f"audio/{target}/repeat/{int(repeat)}", "repeat_result", is_current=is_current,
        )
        if not isinstance(reply, dict) or type(reply.get("repeat")) is not int or _repeat(reply["repeat"]) != repeat:
            raise AudioCommandError("Repeat was not acknowledged with the requested mode; no retry was sent")

    async def async_upload_announcement(self, session: Any, filename: str, data: bytes) -> None:
        """Upload bounded, owned WAV bytes through the native temporary spool."""
        if (
            self._closed
            or not isinstance(filename, str)
            or not re.fullmatch(r"pyloxone-[a-f0-9]{16,32}\.wav", filename)
            or not isinstance(data, bytes)
            or not _WAV_HEADER_BYTES <= len(data) <= 8 * 1024 * 1024
            or data[:4] != b"RIFF"
            or data[8:12] != b"WAVE"
        ):
            message = "Announcement upload requires an available client and a bounded owned WAV"
            raise ValueError(message)
        url = self._uri.replace("ws://", "http://", 1) + f"audio/cfg/upload/audioupload/add/{filename}"
        async with asyncio.timeout(self._timeout):
            async with session.put(
                url,
                data=data,
                headers={"Content-Type": "audio/wav", "Accept-Encoding": "identity"},
                allow_redirects=False,
                auto_decompress=False,
            ) as reply:
                if (
                    not HTTPStatus.OK <= reply.status < HTTPStatus.MULTIPLE_CHOICES
                    or reply.headers.get("Content-Encoding", "identity").lower() != "identity"
                ):
                    message = "Announcement upload failed; no playback was sent"
                    raise AudioCommandError(message)
                await reply.content.read(1024)

    async def async_announce(
        self,
        player_id: object,
        filename: str,
        volume: object,
        *,
        is_current: Callable[[], bool] | None = None,
        on_send: Callable[[], None] | None = None,
    ) -> None:
        """Play one uploaded WAV as a native temporary announcement, once."""
        target = audio_player_id(player_id)
        if (
            target is None
            or not isinstance(filename, str)
            or not re.fullmatch(r"pyloxone-[a-f0-9]{16,32}\.wav", filename)
        ):
            message = "Announcement requires an exact player and an owned WAV filename"
            raise ValueError(message)
        if type(volume) is not int or not 0 <= volume <= _MAX_ANNOUNCEMENT_VOLUME:
            message = "Announcement volume must be an integer from 0 to 100"
            raise ValueError(message)
        command = f"audio/grouped/playuploadedfile/{filename}/{target}#{volume}"
        if (
            await self._async_request(command, "playuploadedfile_result", is_current=is_current, on_send=on_send)
            is not True
        ):
            message = "Audio announcement was not acknowledged; no replay was sent"
            raise AudioCommandError(message)

    async def async_room_favourites(self, player_id: object) -> Any:
        """Read up to 256 room favourites in bounded native pages, never truncate."""
        target = audio_player_id(player_id)
        if target is None:
            message = "Configured favourites require an exact player"
            raise ValueError(message)
        async with asyncio.timeout(30):
            payload = await self._async_request(f"audio/cfg/getroomfavs/{target}/0/32", "getroomfavs_result")
            # Preserve the single-page discovery contract and validate combined
            # payloads with the same exact-room parser used by source selection.
            if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
                return payload
            first = payload[0]
            total = first.get("totalitems")
            if type(total) is not int or total <= _FAVOURITE_PAGE_SIZE:
                return payload
            message = "Configured favourites changed, are incomplete or exceed the 256-item bound"
            if total > _MAX_ROOM_FAVOURITES:
                raise AudioCommandError(message)
            items = []
            observed_pages = []
            seen = set()
            page = first
            while True:
                rows = page.get("items")
                if (
                    type(page.get("id")) is not int
                    or page["id"] != target
                    or type(page.get("start")) is not int
                    or page["start"] != len(items)
                    or type(page.get("totalitems")) is not int
                    or page["totalitems"] != total
                    or not isinstance(rows, list)
                    or not 0 < len(rows) <= _FAVOURITE_PAGE_SIZE
                    or len(items) + len(rows) > total
                ):
                    raise AudioCommandError(message)
                for row in rows:
                    if (
                        not isinstance(row, dict)
                        or type(row.get("id")) is not int
                        or row["id"] <= 0
                        or row["id"] in seen
                    ):
                        raise AudioCommandError(message)
                    seen.add(row["id"])
                observed_pages.append(page)
                items.extend(rows)
                if len(items) == total:
                    # No native snapshot revision is available in this schema.
                    # Require two matching bounded reads of every large-list
                    # page, rather than accepting a mixed first pass. This is
                    # optimistic validation, not an atomic server snapshot.
                    for previous in observed_pages:
                        check = await self._async_request(
                            f"audio/cfg/getroomfavs/{target}/{previous['start']}/32", "getroomfavs_result"
                        )
                        if check != [previous]:
                            raise AudioCommandError(message)
                    return [{**first, "items": items}]
                payload = await self._async_request(
                    f"audio/cfg/getroomfavs/{target}/{len(items)}/32", "getroomfavs_result"
                )
                if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
                    raise AudioCommandError(message)
                page = payload[0]

    async def async_source_inputs(self) -> Any:
        """Discover exact available Line-In identities, without selecting one."""
        return await self._async_request("audio/cfg/getinputs", "getinputs_result")

    async def async_player_status(
        self, player_id: object, *, is_current: Callable[[], bool],
    ) -> AudioZoneMetadata:
        """Read one exact native player; classify with the existing event rules."""
        target = audio_player_id(player_id)
        if target is None:
            message = "Player status requires an exact player"
            raise ValueError(message)
        credentials = self._credentials()
        payload = await self._async_request(f"audio/{target}/status", "status_result", is_current=is_current)
        if not is_current() or self._credentials() != credentials:
            raise AudioCommandError("Native player status authentication or intent changed")
        rows = [payload] if isinstance(payload, dict) else payload
        if (
            not isinstance(rows, list) or len(rows) != 1
            or not isinstance(rows[0], dict)
            or audio_player_id(rows[0].get("playerid")) != target
        ):
            message = "Native player status is missing or ambiguous"
            raise AudioCommandError(message)
        return parse_audio_events({"audio_event": rows})[0]

    async def async_recent_sources(self, player_id: object) -> Any:
        """Read native room-local recent selections; never create guessed history."""
        target = audio_player_id(player_id)
        if target is None:
            message = "Recent sources require an exact player"
            raise ValueError(message)
        return await self._async_request(f"audio/{target}/recent", "recent_result")

    async def async_search_capabilities(self) -> Any:
        """Read supported native indexed search providers/categories."""
        return await self._async_request("audio/cfg/globalsearch/describe", "globalsearch_result")

    @staticmethod
    def _catalogue_identifier(value: object, limit: int = 2048) -> str:
        """Reject malformed IDs; encode them only when building native paths."""
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > limit
            or any(ord(c) < _CONTROL_BOUNDARY for c in value)
        ):
            msg = "An exact bounded catalogue identifier is required"
            raise ValueError(msg)
        return value

    async def async_media_folder(
        self, service: str, account: str, folder: str, offset: int = 0
    ) -> Any:
        """Read one native indexed-library or account-specific service page."""
        folder = self._catalogue_identifier(folder)
        if type(offset) is not int or not 0 <= offset <= _MAX_RADIO_OFFSET:
            msg = "A bounded catalogue offset is required"
            raise ValueError(msg)
        if service == "library" and account == "nouser":
            command = f"audio/cfg/getmediafolder/{quote(folder, safe='')}/{offset}/50"
            key = "getmediafolder_result"
        elif (
            service == "spotify" and isinstance(account, str) and re.fullmatch(r"[A-Za-z0-9_.@+-]{1,128}", account)
        ) or (service == "loxoneradio" and account == "noUser"):
            command = f"audio/cfg/getservicefolder/{service}/{account}/{quote(folder, safe='')}/{offset}/50"
            key = "getservicefolder_result"
        else:
            msg = "A discovered supported service account is required"
            raise ValueError(msg)
        return await self._async_request(command, key)

    async def async_play_catalogue(  # noqa: PLR0913 - exact native playback route
        self,
        player_id: object,
        service: str,
        account: str,
        item_id: str,
        *,
        parent_path: str | None = None,
        parent_index: int | None = None,
        is_current: Callable[[], bool] | None = None,
        on_send: Callable[[], None] | None = None,
    ) -> None:
        """Select one exact discovered source item; never an empty session import."""
        target = audio_player_id(player_id)
        item = quote(self._catalogue_identifier(item_id), safe="")
        if target is None:
            msg = "An exact player is required"
            raise ValueError(msg)
        if service in ("linein", "library", "playlist") and account == "nouser":
            route = f"linein/{item}" if service == "linein" else f"{service}/play/{item}"
        elif service == "spotify" and isinstance(account, str) and re.fullmatch(r"[A-Za-z0-9_.@+-]{1,128}", account):
            route = f"serviceplay/spotify/{account}/{item}"
        else:
            msg = "A discovered supported source is required"
            raise ValueError(msg)
        if parent_path is not None or parent_index is not None:
            if service not in ("library", "playlist", "spotify") or type(parent_index) is not int or parent_index < 0:
                raise ValueError("Parent context requires an exact supported source cursor")
            parent = quote(self._catalogue_identifier(parent_path), safe="")
            route += f"/parentpath/{parent}/{parent_index}"
        if service == "spotify" and re.match(r"spotify(?:@[^:]+)?:(?:track|episode):", item_id):
            # Native playItem excludes individual items from shuffled starts;
            # ServicePlayScheme places this per-start argument after the cursor.
            route += "/noshuffle"
        await self._async_request(f"audio/{target}/{route}", None, is_current=is_current, on_send=on_send)

    async def async_global_search(
        self, query: str, scopes: dict[str, tuple[str, ...]], *, spotify_account: str | None = None
    ) -> Any:
        """Collect every requested provider for one correlated native ticket."""
        query = self._catalogue_identifier(query, _MAX_RADIO_QUERY)
        allowed = {
            "local": {"track", "album", "artist", "playlist", "folder"},
            "spotify": {"track", "album", "artist", "playlist", "episode", "show"},
            "tunein": {"station", "custom"},
        }
        if not isinstance(scopes, dict) or not scopes or set(scopes) - allowed.keys():
            msg = "Search requires supported discovered scopes"
            raise ValueError(msg)
        parts = []
        for scope, categories in scopes.items():
            if (
                not isinstance(categories, tuple)
                or not categories
                or len(categories) > _MAX_SEARCH_CATEGORIES
                or any(c not in allowed[scope] for c in categories)
                or len(set(categories)) != len(categories)
            ):
                msg = "Search categories must be supported and bounded"
                raise ValueError(msg)
            provider = scope
            if scope == "spotify":
                if not isinstance(spotify_account, str) or not re.fullmatch(
                    r"[A-Za-z0-9_.@+-]{1,128}", spotify_account
                ):
                    msg = "Spotify search requires an exact linked account"
                    raise ValueError(msg)
                provider += "@" + spotify_account
            parts.append(provider + ":" + ",".join(c + "#50" for c in categories))
        return await self._async_request(
            "audio/cfg/globalsearch/" + "|".join(parts) + "/" + quote(query, safe=""),
            "globalsearch_result",
            search_scopes=tuple(scopes),
            spotify_account=spotify_account,
        )

    @staticmethod
    async def _global_search_reply(socket: Any, scopes: tuple[str, ...], account: str | None) -> Any:
        """Do not mistake the ticket, a wrong account or partial scopes for results."""
        ticket = None
        results = {}
        while len(results) < len(scopes):
            await asyncio.sleep(0)
            frame = await socket.recv()
            if not isinstance(frame, str):
                continue
            try:
                reply = json.loads(frame)
            except (TypeError, ValueError):  # fmt: skip
                continue
            if not isinstance(reply, dict) or not isinstance(reply.get("globalsearch_result"), dict):
                continue
            result = reply["globalsearch_result"]
            if ticket is None:
                if reply.get("error") or result.get("error"):
                    msg = "Native search rejected the query"
                    raise AudioCommandError(msg)
                unique = result.get("unique")
                if isinstance(unique, str) and 0 < len(unique) <= _MAX_RADIO_QUERY:
                    ticket = unique
                continue
            scope = reply.get("type")
            if reply.get("unique") != ticket or scope not in scopes or scope in results:
                continue
            content = result.get("result", result)
            if not isinstance(content, dict):
                msg = "Native search returned malformed results"
                raise AudioCommandError(msg)
            if scope == "spotify" and "user" in content and content["user"] != account:
                continue
            if reply.get("error") or result.get("error"):
                msg = "A native search provider failed; no empty success was returned"
                raise AudioCommandError(msg)
            if scope == "spotify" and content.get("user") != account:
                continue
            results[scope] = content
        return results

    async def async_radio_services(self) -> Any:
        """Discover the native radio catalogue roots, without playing content."""
        return await self._async_request("audio/cfg/getradios", "getradios_result")

    async def async_radio_folder(self, service: str, folder: str, offset: int = 0) -> Any:
        """Read one 50-item provider page using literal, encoded identifiers."""
        if (
            not isinstance(service, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", service)
            or not isinstance(folder, str)
            or not folder.strip()
            or len(folder) > _MAX_RADIO_PATH
            or any(ord(c) < _CONTROL_BOUNDARY for c in folder)
            or type(offset) is not int
            or not 0 <= offset <= _MAX_RADIO_OFFSET
        ):
            message = "Radio browsing requires an exact provider, folder and bounded offset"
            raise ValueError(message)
        return await self._async_request(
            f"audio/cfg/getservicefolder/{service}/{service}/{quote(folder, safe='')}/{offset}/50",
            "getservicefolder_result",
        )

    async def async_radio_search(self, query: str) -> Any:
        """Read radio-only global-search results, not the initial ticket ACK."""
        if (
            not isinstance(query, str)
            or not query.strip()
            or len(query) > _MAX_RADIO_QUERY
            or any(ord(c) < _CONTROL_BOUNDARY for c in query)
        ):
            message = "Radio search requires a nonempty bounded query"
            raise ValueError(message)
        return await self._async_request(
            f"audio/cfg/globalsearch/tunein:station#100,custom#100/{quote(query, safe='')}",
            "globalsearch_result",
        )

    @staticmethod
    async def _radio_search_reply(socket: Any) -> Any:
        """Correlate the delayed radio result with the acknowledged native ticket."""
        ticket = None
        while True:
            await asyncio.sleep(0)
            frame = await socket.recv()
            if not isinstance(frame, str):
                continue
            try:
                reply = json.loads(frame)
            except (ValueError, TypeError):  # fmt: skip
                continue
            if not isinstance(reply, dict) or not isinstance(reply.get("globalsearch_result"), dict):
                continue
            result = reply["globalsearch_result"]
            if ticket is None:
                value = result.get("unique")
                if isinstance(value, str) and value and len(value) <= _MAX_RADIO_QUERY:
                    ticket = value
                continue
            if reply.get("unique") == ticket and reply.get("type") == "tunein":
                if result.get("error"):
                    message = "Radio search was rejected"
                    raise AudioCommandError(message)
                return result

    async def async_play_radio_station(
        self,
        player_id: object,
        service: str,
        audio_path: str,
        *,
        is_current: Callable[[], bool] | None = None,
        on_send: Callable[[], None] | None = None,
    ) -> None:
        """Send one discovered radio station through the native radio service."""
        target = audio_player_id(player_id)
        if (
            target is None
            or not isinstance(service, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", service)
            or not isinstance(audio_path, str)
            or len(audio_path) > _MAX_RADIO_PATH
            or not audio_path.startswith(("tunein:", "loxoneradio:"))
            or not audio_path.partition(":")[2].strip()
            or any(ord(c) < _CONTROL_BOUNDARY for c in audio_path)
        ):
            message = "Radio playback requires an exact player and discovered native station"
            raise ValueError(message)
        account = "nouser" if service == "loxoneradio" else service
        await self._async_request(
            f"audio/{target}/serviceplay/radio/{account}/{quote(audio_path, safe='')}",
            None,
            is_current=is_current,
            on_send=on_send,
        )

    async def async_service_accounts(self) -> Any:
        """Read configured service accounts without browsing their content."""
        return await self._async_request("audio/cfg/getservices", "getservices_result")

    async def async_play_room_favourite(
        self,
        player_id: object,
        favourite_id: object,
        *,
        is_current: Callable[[], bool] | None = None,
        on_send: Callable[[], None] | None = None,
    ) -> None:
        """Send one exact configured favourite; completion comes from fresh events."""
        target, favourite = audio_player_id(player_id), audio_player_id(favourite_id)
        if target is None or favourite is None:
            message = "Favourite selection requires exact player and favourite IDs"
            raise ValueError(message)
        await self._async_request(
            f"audio/{target}/roomfav/play/{favourite}", None, is_current=is_current, on_send=on_send
        )

    async def async_spotify_handoff(
        self,
        player_id: object,
        account_id: object,
        *,
        is_current: Callable[[], bool] | None = None,
        on_send: Callable[[], None] | None = None,
    ) -> None:
        """Import one linked Spotify session, retaining the empty final path."""
        target = audio_player_id(player_id)
        if (
            target is None
            or not isinstance(account_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_.@+-]{1,128}", account_id)
        ):
            message = "Spotify takeover requires an exact player and configured account ID"
            raise ValueError(message)
        await self._async_request(
            f"audio/{target}/serviceplay/spotify/{account_id}/", None, is_current=is_current, on_send=on_send
        )

    async def async_seek(
        self,
        player_id: object,
        seconds: object,
        *,
        is_current: Callable[[], bool] | None = None,
        on_send: Callable[[], None] | None = None,
    ) -> float:
        """Send one position request; its numeric reply is an echo, not success."""
        target = audio_player_id(player_id)
        position = _seconds(seconds)
        if target is None or position is None:
            message = "Audio seeking requires an exact player and nonnegative seconds"
            raise ValueError(message)
        reply = await self._async_request(
            f"audio/{target}/position/{position}",
            "position_result",
            is_current=is_current,
            on_send=on_send,
        )
        if isinstance(reply, list) and reply and isinstance(reply[0], dict):
            confirmed = _seconds(reply[0].get("position"))
            if confirmed is not None:
                if diagnostics_enabled(self.diagnostics):
                    diagnostic_event(self.diagnostics, "restore_echo", transport="audio_server", player=target,
                                     position=position, echo_position=confirmed)
                return confirmed
        message = "Audio seeking was not acknowledged with a valid position"
        if diagnostics_enabled(self.diagnostics):
            diagnostic_event(self.diagnostics, "error", transport="audio_server", player=target, reason="invalid_reply")
        raise AudioCommandError(message)

    async def _async_request(  # noqa: PLR0913 - shared native request/correlation ownership
        self,
        command: str,
        reply_key: str | None,
        *,
        is_current: Callable[[], bool] | None = None,
        on_send: Callable[[], None] | None = None,
        search_scopes: tuple[str, ...] | None = None,
        spotify_account: str | None = None,
        require_shuffle_switch: bool = False,
    ) -> Any:
        """Share the existing single-send authentication and ownership boundary."""
        owned_socket = None
        observer = self.diagnostics
        diagnostic_id = uuid4().hex if diagnostics_enabled(observer) else None

        def record(stage: str, **fields: Any) -> None:
            if diagnostics_enabled(observer):
                diagnostic_event(observer, stage, transport="audio_server", route=command,
                                 request_id=diagnostic_id, **fields)

        if diagnostics_enabled(observer):
            record("request")
        try:
            # Status reconciliation must not cross authentication changes while
            # waiting for the existing shared lock or handshake. Other native
            # routes retain their established transport/ownership behaviour.
            status_credentials = self._credentials() if reply_key == "status_result" else None
            async with asyncio.timeout(self._timeout), self._lock:

                if self._closed:
                    message = "Audio playback connection is closed"
                    raise AudioCommandError(message)
                username, token = self._credentials()
                if not isinstance(username, str) or not username.strip() or not isinstance(token, str) or not token:
                    message = "Audio playback credentials are unavailable"
                    raise AudioCommandError(message)
                async with connect(
                    self._uri,
                    subprotocols=[Subprotocol("remotecontrol")],
                    open_timeout=self._timeout,
                    close_timeout=2,
                    ping_interval=None,
                    max_size=1024 * 1024,
                    **_DIRECT_CONNECT,
                ) as socket:
                    owned_socket = self._socket = socket
                    if self._closed:
                        message = "Audio playback connection is closed"
                        raise AudioCommandError(message)
                    shuffle_switch = await self._authenticate(socket, username, token)
                    if diagnostics_enabled(observer):
                        record("authenticated")

                    if self._closed:
                        message = "Audio playback connection is closed"
                        raise AudioCommandError(message)
                    if require_shuffle_switch and shuffle_switch is not True:
                        raise AudioCommandError("Explicit shuffle requires Audio Server API1.6/firmware16.1.09.23")
                    if status_credentials is not None and self._credentials() != status_credentials:
                        raise AudioCommandError("Native player status authentication changed before dispatch")
                    if is_current is not None and not is_current():
                        message = "Audio seek is no longer applicable to the current track"
                        raise AudioCommandError(message)
                    if on_send is not None:
                        on_send()
                    if diagnostics_enabled(observer):
                        record("send_attempt")
                    await socket.send(command)
                    if diagnostics_enabled(observer):
                        record("send_completed")

                    if search_scopes is not None:
                        result = await self._global_search_reply(socket, search_scopes, spotify_account)
                    elif reply_key == "globalsearch_result" and not command.endswith("/describe"):
                        result = await self._radio_search_reply(socket)
                    elif reply_key is not None:
                        result = await self._reply(socket, reply_key)
                    else:
                        result = None
                    # Native source results are optional, not the BaseResponse
                    # command echo. Keep this socket until that exact echo, so
                    # an immediate close cannot discard an unresolved command.
                    if reply_key is None and search_scopes is None:
                        player = audio_player_id(command.split("/")[1])
                        proof = await self._command_echo(socket, command, self.source_observations.get(player))
                        if diagnostics_enabled(observer):
                            record("reply" if proof == "echo" else "source_confirmed")
                    elif diagnostics_enabled(observer):
                        record("reply")
                    return result
        except asyncio.CancelledError:
            if diagnostics_enabled(observer):
                record("cancelled")
            raise
        except AudioCommandError:
            if diagnostics_enabled(observer):
                record("error", reason="rejected")
            raise
        except (OSError, WebSocketException, TimeoutError, ValueError, TypeError, KeyError, IndexError) as err:  # fmt: skip
            if diagnostics_enabled(observer):
                record("timeout" if isinstance(err, TimeoutError) else "error", reason="transport_failed")
            # Neither native errors nor authentication envelopes may reach logs.
            message = "Audio playback failed; no fallback or automatic retry was sent"
            raise AudioCommandError(message) from None
        finally:
            if self._socket is owned_socket:
                self._socket = None

    async def _authenticate(self, socket: Any, username: str, token: str) -> bool | None:
        """Authenticate the owned socket without sending a player command."""
        # Native event broadcasts can arrive before this socket's greeting.
        # Skip only known unsolicited event envelopes, under _async_request's
        # existing deadline; never retry authentication or a player command.
        while True:
            await asyncio.sleep(0)
            greeting = await socket.recv()
            if isinstance(greeting, str):
                try:
                    unsolicited = json.loads(greeting)
                except ValueError:
                    unsolicited = None
                if (
                    isinstance(unsolicited, dict) and not unsolicited.get("error")
                    and any(isinstance(unsolicited.get(field), list) for field in ("audio_event", "audio_sync_event"))
                ):
                    continue
            break
        if not isinstance(greeting, str) or "Session-Token:" not in greeting:
            message = "Audio playback session is unavailable"
            raise AudioCommandError(message)
        session = greeting.split("Session-Token:", 1)[1].splitlines()[0].strip()
        if not session:
            message = "Audio playback session is unavailable"
            raise AudioCommandError(message)
        await socket.send("audio/cfg/getkey/full")
        keys = await self._reply(socket, "getkey_result")
        if not isinstance(keys, list) or not keys or not isinstance(keys[0], dict):
            message = "Audio playback key is unavailable"
            raise AudioCommandError(message)
        key_pem = keys[0].get("pubkey")
        if not isinstance(key_pem, str) or not key_pem:
            message = "Audio playback key is unavailable"
            raise AudioCommandError(message)
        # Native firmware can return a single-line PEM; PyCryptodome's parser
        # requires whitespace after the header and before the footer.
        key_pem = key_pem.replace("-----BEGIN PUBLIC KEY-----", "-----BEGIN PUBLIC KEY-----\n").replace(
            "-----END PUBLIC KEY-----", "\n-----END PUBLIC KEY-----"
        )
        public_key = RSA.import_key(key_pem)
        key, iv = get_random_bytes(32), get_random_bytes(16)
        envelope = f"{key.hex()}:{iv.hex()}:{session}".encode()
        rsa_part = PKCS1_v1_5.new(public_key).encrypt(envelope)
        encrypted = AES.new(key, AES.MODE_CBC, iv).encrypt(pad(token.encode(), AES.block_size))
        encoded = [
            quote(username, safe=""),
            *(quote(base64.b64encode(part).decode(), safe="") for part in (rsa_part, encrypted)),
        ]
        await socket.send("secure/authenticate/" + "/".join(encoded))
        if await self._reply(socket, "authenticate_result") != "authentication successful":
            message = "Audio playback authentication was rejected"
            raise AudioCommandError(message)
        return _shuffle_switch(greeting)

    @staticmethod
    async def _command_echo(
        socket: Any, command: str, observation: asyncio.Future[None] | None = None,
    ) -> str:
        """
        Settle by exact echo or independently qualified post-send source proof.

        Some native serviceplay implementations execute without a response.
        Only the source coordinator supplies exact-player/account playing
        evidence; a completed socket write alone is never confirmation.
        """
        while True:
            await asyncio.sleep(0)
            if observation is None:
                message = await socket.recv()
            else:
                receive = asyncio.create_task(socket.recv())
                try:
                    await asyncio.wait((receive, observation), return_when=asyncio.FIRST_COMPLETED)
                    if receive.done():
                        message = receive.result()
                    else:
                        observation.result()

                        return "source_proof"
                finally:
                    if not receive.done():
                        receive.cancel()
                        with suppress(asyncio.CancelledError):
                            await receive
            try:
                reply = json.loads(message) if isinstance(message, str) else None
            except (ValueError, TypeError):  # fmt: skip
                reply = None
            if isinstance(reply, dict) and reply.get("command") == command:
                error = reply.get("error")
                if error is not None and error != "":
                    message = "Audio source command was rejected; no fallback or retry was sent"
                    raise AudioCommandError(message)

                return "echo"
            # A readable stream can win every wait alongside qualified proof.
            # Inspect the ready frame for an exact rejection first, then honour
            # that proof instead of starving it behind unrelated broadcasts.
            if observation is not None and observation.done():
                observation.result()

                return "source_proof"

    @staticmethod
    async def _reply(socket: Any, key: str) -> Any:
        """Receive under the caller's deadline, tolerating interleaved event frames."""
        while True:
            # recv() can complete immediately from a busy socket's buffer. Yield
            # so cancellation and the command-wide timeout cannot be starved.
            await asyncio.sleep(0)
            message = await socket.recv()
            if not isinstance(message, str):
                continue
            try:
                reply = json.loads(message)
            except (ValueError, TypeError):  # fmt: skip
                continue
            if isinstance(reply, dict) and key in reply:
                if reply.get("error"):
                    msg = "Native audio request was rejected"
                    raise AudioCommandError(msg)
                return reply[key]


class AudioEventReceiver:
    """
    Consume one externally owned text stream without any send capability.

    Empty update tuples invalidate all metadata on disconnect/reconnect. The
    caller owns connection establishment, backoff and HA-tracked task lifetime.
    No initial metadata is invented before an event for that exact player.
    Only flapping event-end attributes are held; zone metadata remains current.
    All pending end timers are cancelled before invalidating a lost stream.
    """

    def __init__(self, on_update: Callable[[tuple[AudioZoneMetadata, ...]], None]) -> None:
        """Create a receiver whose notifications run on its owning event loop."""
        self._on_update = on_update
        self._metadata: dict[int, AudioZoneMetadata] = {}
        self._feedback_revision: dict[int, int] = {}
        self._end_timers: dict[int, asyncio.TimerHandle] = {}
        self._listening = False
        self._stream_generation = 0
        self._shuffle_switch_supported: bool | None = None

    def get(self, player_id: int) -> AudioZoneMetadata | None:
        """Return the latest known snapshot, or unknown after loss of the stream."""
        return self._metadata.get(player_id)

    def _reset(self) -> None:
        """Invalidate stale snapshots rather than presenting them as current."""
        self._stream_generation += 1
        for timer in self._end_timers.values():
            timer.cancel()
        self._end_timers.clear()
        self._metadata.clear()
        self._feedback_revision.clear()
        self._shuffle_switch_supported = None
        self._on_update(())

    async def async_ensure_snapshot(
        self, player_id: int, read: Callable[[], Awaitable[AudioZoneMetadata]], *, is_current: Callable[[], bool],
    ) -> None:
        """Bootstrap only a missing player on the same live passive stream."""
        if self.get(player_id) is not None:
            return
        generation = self._stream_generation
        if not self._listening or not is_current():
            message = "Native event stream is unavailable; no content was sent"
            raise AudioCommandError(message)
        row = await read()
        if (
            not self._listening or generation != self._stream_generation or not is_current()
            or self.get(player_id) is not None or row.player_id != player_id
        ):
            message = "Native status read was superseded; no content was sent"
            raise AudioCommandError(message)
        self._on_update((self._apply(row),))

    async def async_refresh_snapshot(
        self, player_id: int, read: Callable[[], Awaitable[AudioZoneMetadata]], *, is_current: Callable[[], bool],
    ) -> None:
        """Reconcile a silent live stream without overwriting intervening feedback."""
        generation = self._stream_generation
        revision = self._feedback_revision.get(player_id, 0)
        if not self._listening or not is_current():
            raise AudioCommandError("Native metadata recovery is no longer applicable")
        row = await read()
        if (
            not self._listening or generation != self._stream_generation or not is_current()
            or self._feedback_revision.get(player_id, 0) != revision or row.player_id != player_id
            or row.native_mode not in ("play", "pause", "stop")
            or row.event_active is None or not (row.audio_path or row.event_active)
        ):
            raise AudioCommandError("Native metadata recovery was superseded or unusable")
        self._on_update((self._apply(row),))

    def _apply(self, row: AudioZoneMetadata) -> AudioZoneMetadata:
        """Publish metadata promptly, stabilising only known flapping event ends."""
        # Bare parsed rows still replace the raw snapshot, but cannot veto a
        # useful awaited read. Retain a revision across later empty rows so any
        # intervening real observation (including sparse zero/False/account or
        # context fields) remains a supersession fence, even for the same track.
        if row.has_observation:
            self._feedback_revision[row.player_id] = self._feedback_revision.get(row.player_id, 0) + 1
        row = replace(row, shuffle_switch_supported=self._shuffle_switch_supported)
        player_id = row.player_id
        old = self._metadata.get(player_id)
        if row.event_active is False and old is not None and old.event in _DEBOUNCED_EVENTS:
            if player_id not in self._end_timers:
                self._end_timers[player_id] = asyncio.get_running_loop().call_later(
                    _EVENT_END_DELAY, self._finish_event, player_id
                )
            row = replace(row, event=old.event, event_active=True)
        elif timer := self._end_timers.pop(player_id, None):
            # A renewed/replaced event or unknown state invalidates a pending end.
            timer.cancel()
        self._metadata[player_id] = row
        return row

    def _finish_event(self, player_id: int) -> None:
        """End a stable interruption without restoring an older metadata snapshot."""
        self._end_timers.pop(player_id, None)
        row = replace(self._metadata[player_id], event=None, event_active=False)
        self._metadata[player_id] = row
        self._feedback_revision[player_id] = self._feedback_revision.get(player_id, 0) + 1
        self._on_update((row,))

    async def async_listen(self, messages: AsyncIterable[str | bytes]) -> None:
        """Read passive events; cancellation propagates after stale-data cleanup."""
        if self._listening:
            message = "Audio event receiver is already listening"
            raise RuntimeError(message)
        self._listening = True
        try:
            self._reset()
            async for frame in messages:
                if not isinstance(frame, str):
                    continue
                if frame.startswith("LWSS V "):
                    self._shuffle_switch_supported = _shuffle_switch(frame)
                    continue
                try:
                    payload = json.loads(frame)
                except ValueError:
                    # Includes malformed JSON and Python's oversized-integer limit.
                    continue
                if updates := parse_audio_events(payload):
                    updates = tuple(self._apply(row) for row in updates)
                    self._on_update(updates)
        finally:
            self._listening = False
            self._reset()


class AudioServerListener:
    """Own an optional, unauthenticated, receive-only event connection."""

    def __init__(self, host: str, on_update: Callable[[tuple[AudioZoneMetadata, ...]], None]) -> None:
        """Create the connection owner without opening a socket."""
        self._uri = audioserver_uri(host)
        self._on_update = on_update
        self._retry_delay = 1
        self._receiver = AudioEventReceiver(self._receive_update)

    def _receive_update(self, updates: tuple[AudioZoneMetadata, ...]) -> None:
        """Reset backoff only after a valid event, not a flapping handshake."""
        if updates:
            self._retry_delay = 1
        self._on_update(updates)

    def get(self, player_id: int) -> AudioZoneMetadata | None:
        """Return metadata only while its event stream is current."""
        return self._receiver.get(player_id)

    async def async_ensure_snapshot(
        self, player_id: int, read: Callable[[], Awaitable[AudioZoneMetadata]], *, is_current: Callable[[], bool],
    ) -> None:
        """Keep explicit read bootstrap separate from receive-only connection IO."""
        await self._receiver.async_ensure_snapshot(player_id, read, is_current=is_current)

    async def async_refresh_snapshot(
        self, player_id: int, read: Callable[[], Awaitable[AudioZoneMetadata]], *, is_current: Callable[[], bool],
    ) -> None:
        """Publish a fenced read through the existing receiver, not a second cache."""
        await self._receiver.async_refresh_snapshot(player_id, read, is_current=is_current)

    async def async_run(self) -> None:
        """Receive events until the owning HA entry cancels this coroutine."""
        while True:
            try:
                async with connect(
                    self._uri,
                    subprotocols=[Subprotocol("remotecontrol")],
                    ping_interval=None,
                    open_timeout=10,
                    close_timeout=5,
                    max_size=1048576,
                    **_DIRECT_CONNECT,
                ) as socket:
                    await self._receiver.async_listen(socket)
            except (OSError, TimeoutError, WebSocketException) as err:
                # Never log raw frames, server replies or credential-bearing URLs.
                _LOGGER.debug("Audioserver event connection lost (%s)", type(err).__name__)
            await asyncio.sleep(self._retry_delay)
            self._retry_delay = min(self._retry_delay * 2, 30)
