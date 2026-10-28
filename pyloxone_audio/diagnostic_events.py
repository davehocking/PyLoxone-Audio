"""Optional fixed-schema audio diagnostics; no HA, transport or storage ownership.

Only this allowlist crosses a sink boundary. Untrusted errors, raw frames, auth
material, announcement text and arbitrary caller fields are deliberately absent.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import hashlib
import hmac
import math
import re
import time
from typing import Any
from urllib.parse import unquote

STAGES = frozenset(
    {
        "request",
        "authenticated",
        "send_attempt",
        "send_completed",
        "reply",
        "echo_or_source_proof",
        "error",
        "cancelled",
        "timeout",
        "disconnected",
        "feedback",
        "restore_decision",
        "source_confirmed",
        "restore_failed",
        "restore_echo",
        "collection_started",
        "collection_stopped",
        "session_saved",
        "ha_service_request",
    }
)
ENUMS = {
    "operation": {
        "position",
        "play",
        "pause",
        "stop",
        "status",
        "serviceplay",
        "roomfav",
        "library",
        "volume",
        "volUp",
        "volDown",
        "next",
        "prev",
        "volume_set",
        "volume_up",
        "volume_down",
        "media_play",
        "media_pause",
        "media_stop",
        "media_next_track",
        "media_previous_track",
        "media_seek",
        "select_source",
        "play_media",
        "shuffle",
        "repeat",
        "shuffle_set",
        "repeat_set",
        "state",
    },
    "transport": {"audio_server", "miniserver", "source", "ha_service"},
    "source": {"spotify", "library", "tunein", "loxoneradio", "linein", "airplay"},
    "mode": {"play", "pause", "stop"},
    "repeat": {"off", "all", "one"},
    "phase": {"initial", "post_auth", "after_restore"},
    "reason": {
        "eligible",
        "missing_session",
        "no_confirmation",
        "not_return",
        "unavailable",
        "missing_snapshot",
        "player_mismatch",
        "event_active",
        "not_playing",
        "source_mismatch",
        "track_mismatch",
        "account_mismatch",
        "duration_missing",
        "position_missing",
        "position_invalid",
        "seek_unsupported",
        "announcement_fence",
        "source_fence",
        "superseded",
        "rejected",
        "transport_failed",
        "invalid_reply",
    },
}
NUMBERS = frozenset(
    {
        "position",
        "duration",
        "saved_position",
        "saved_duration",
        "echo_position",
        "volume",
        "play_state",
    }
)
BOOLEANS = frozenset(
    {"saved_session", "available", "event_idle", "event_active", "seek_supported", "shuffle"}
)
IDENTITIES = frozenset(
    {"player", "room", "entry", "account", "content", "request_id", "parent"}
)


def diagnostics_enabled(observer: Any) -> bool:
    """An optional broken observer must never interrupt a command."""
    try:
        return observer is not None and observer.enabled is True
    except Exception:
        return False


def diagnostic_event(observer: Any, event: str, **fields: Any) -> None:
    """Isolate even a foreign observer; callers gate expensive field creation."""
    try:
        if diagnostics_enabled(observer):
            observer.emit(event, **fields)
    except Exception:
        pass


class DiagnosticEmitter:
    """Bounded structured, keyed pseudonyms with a synchronous nonblocking sink.

    The host must supply a bounded enqueue-only sink, never file I/O. It owns
    explicit enablement and persistence of the private random pseudonym key.
    """

    def __init__(self, key: bytes, sink: Callable[[dict[str, Any]], None]) -> None:
        self.enabled = False
        self._key = key
        self._sink = sink
        self._sequence = 0
        self.sink_failures = 0

    def alias(self, kind: str, value: object) -> str:
        if kind not in IDENTITIES or type(value) not in (str, int):
            return "unknown"
        # Bound work even for maliciously large incoming identity fields.
        text = str(value)
        data = (kind + ":" + text[:16384] + ":" + str(len(text))).encode(
            "utf-8", errors="replace"
        )
        return kind + "-" + hmac.new(self._key, data, hashlib.sha256).hexdigest()[:20]

    def route(self, command: object) -> str | None:
        if not isinstance(command, str) or len(command) > 16384:
            return None
        parts = command.split("/")
        if len(parts) in (5, 6) and parts[:3] == ["jdev", "sps", "io"]:
            room = self.alias("room", parts[3])
            if (
                parts[4]
                in {"play", "pause", "stop", "volUp", "volDown", "next", "prev"}
                and len(parts) == 5
            ):
                return f"io/{room}/{parts[4]}"
            if (
                parts[4] == "volume"
                and len(parts) == 6
                and re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]+)?", parts[5])
            ):
                if 0 <= float(parts[5]) <= 100:
                    return f"io/{room}/volume/{parts[5]}"
            return None
        if (
            len(parts) < 3
            or parts[0] != "audio"
            or not re.fullmatch(r"[1-9][0-9]{0,9}", parts[1])
        ):
            return None
        player = self.alias("player", int(parts[1]))
        operation = parts[2]
        item_flag = ""
        if (
            operation == "serviceplay" and len(parts) in (7, 10)
            and parts[3] == "spotify" and parts[-1] == "noshuffle"
            and re.match(r"spotify(?:@[^:]+)?:(?:track|episode):", unquote(parts[5]))
        ):
            parts = parts[:-1]
            item_flag = "/noshuffle"
        if len(parts) == 4 and (
            operation == "shuffle" and parts[3] in {"enable", "disable"}
            or operation == "repeat" and parts[3] in {"0", "1", "3"}
        ):
            return f"audio/{player}/{operation}/{parts[3]}"
        if operation == "position" and len(parts) == 4:
            if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", parts[3]):
                return None
            value = float(parts[3])
            return (
                f"audio/{player}/position/{parts[3]}" if math.isfinite(value) else None
            )
        if operation in {"play", "pause", "stop", "status"} and len(parts) == 3:
            return f"audio/{player}/{operation}"
        if (
            operation == "serviceplay"
            and len(parts) in (6, 9)
            and parts[3] in ENUMS["source"]
        ):
            route = f"audio/{player}/serviceplay/{parts[3]}/{self.alias('account', parts[4])}/{self.alias('content', unquote(parts[5]))}"
            tail = parts[6:]
        elif operation == "library" and len(parts) in (5, 8) and parts[3] == "play":
            route = f"audio/{player}/library/play/{self.alias('content', unquote(parts[4]))}"
            tail = parts[5:]
        else:
            route = None
            tail = []
        if route is not None:
            if not tail:
                return route + item_flag
            if tail[0] == "parentpath" and re.fullmatch(r"[0-9]{1,10}", tail[2]):
                return (
                    route
                    + "/parentpath/"
                    + self.alias("parent", unquote(tail[1]))
                    + "/"
                    + tail[2]
                    + item_flag
                )
            return None
        if operation == "roomfav" and len(parts) == 5 and parts[3] == "play":
            return f"audio/{player}/roomfav/play/{self.alias('content', parts[4])}"
        # Spool filenames and other unrecognised operations are never exported.
        return None

    def emit(self, event: str, **fields: Any) -> None:
        if not self.enabled or event not in STAGES:
            return
        try:
            self._sequence += 1
            row: dict[str, Any] = {
                "schema": 1,
                "stage": event,
                "sequence": self._sequence,
                "utc": datetime.now(UTC).isoformat(),
                "monotonic": time.monotonic(),
            }
            for name, value in fields.items():
                if name in IDENTITIES and type(value) in (str, int):
                    row[name] = self.alias(name, value)
                elif name in ENUMS and isinstance(value, str) and value in ENUMS[name]:
                    row[name] = value
                elif (
                    name in NUMBERS
                    and type(value) in (int, float)
                    and math.isfinite(value)
                    and value >= 0
                ):
                    row[name] = value
                elif name in BOOLEANS and type(value) is bool:
                    row[name] = value
                elif name == "route" and (route := self.route(value)) is not None:
                    row[name] = route
                    row["operation"] = route.split("/")[2]
            self._sink(row)
        except Exception:
            self.sink_failures += 1
