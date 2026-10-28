"""Supported diagnostics contain fixed fields, never untrusted free text."""

import importlib.util
import json

import pytest


def emitter(sink):
    spec = importlib.util.find_spec("pyloxone_audio.diagnostic_events")
    assert spec is not None, "The optional fixed-schema diagnostics feature is missing"
    from pyloxone_audio.diagnostic_events import DiagnosticEmitter

    return DiagnosticEmitter(b"synthetic-key-not-a-credential-32", sink)


def test_default_off_has_no_sink_or_field_work():
    events = []
    diag = emitter(events.append)

    class Untrusted:
        def __str__(self):
            raise AssertionError("disabled diagnostics inspected input")

    diag.emit("send_attempt", route=Untrusted())
    assert events == []
    assert diag.enabled is False


def test_fixed_schema_pseudonyms_and_exact_seek_route():
    events = []
    diag = emitter(events.append)
    diag.enabled = True
    diag.emit(
        "send_attempt",
        request_id="request1",
        transport="audio_server",
        route="audio/27/position/66.285",
        player=27,
        account="private-account",
        content="spotify:track:SECRET",
        password="SENTINEL",
        exception="SENTINEL",
        source="spotify",
        position=66.285,
        duration=180.5,
        reason="eligible",
    )
    row = events[0]
    assert row["schema"] == 1
    assert row["position"] == 66.285
    assert row["route"].endswith("/position/66.285")
    assert row["route"].split("/")[1] == row["player"]
    assert row["utc"].endswith("+00:00")
    assert row["sequence"] == 1
    assert row["monotonic"] >= 0
    assert "SENTINEL" not in json.dumps(row)
    assert "SECRET" not in json.dumps(row)
    assert "private-account" not in json.dumps(row)
    diag.emit("feedback", player=27, content="spotify:track:SECRET")
    assert events[1]["player"] == row["player"]
    assert events[1]["content"] == row["content"]
    other = emitter(lambda _: None)
    assert other.alias("player", 27) == diag.alias("player", 27)


@pytest.mark.parametrize(
    "route",
    [
        "secure/authenticate/SECRET",
        "audio/cfg/getkey/full",
        "jdev/sys/SECRET",
        "audio/27/position/NaN",
        "audio/27/playuploadedfile/SECRET.wav/80",
        "audio/27/unknown/SECRET",
        "audio/27/serviceplay/spotify/acct/https://u:pass@x/?token=SECRET",
    ],
)
def test_routes_never_retain_auth_urls_or_private_announcement_text(route):
    events = []
    diag = emitter(events.append)
    diag.enabled = True
    diag.emit(
        "send_attempt",
        route=route,
        position=float("nan"),
        duration=True,
        source="SENTINEL",
        reason="SENTINEL",
        stage="SENTINEL",
    )
    encoded = json.dumps(events, allow_nan=False)
    assert "SECRET" not in encoded and "SENTINEL" not in encoded
    assert "NaN" not in encoded
    assert "position" not in events[0]
    assert "duration" not in events[0]


def test_unknown_stages_are_not_persisted_and_sink_failure_is_isolated():
    events = []
    diag = emitter(events.append)
    diag.enabled = True
    diag.emit("UNTRUSTED-SECRET", raw="SECRET")
    assert events == []

    def broken(_):
        raise OSError("private storage error SECRET")

    diag = emitter(broken)
    diag.enabled = True
    diag.emit("feedback", player=1)
    assert diag.sink_failures == 1


def test_identity_aliases_are_bounded_unicode_safe_and_keyed():
    diag = emitter(lambda _: None)
    assert len(diag.alias("content", "雪" * 10000)) < 64
    assert diag.alias("account", "x") != diag.alias("content", "x")
    from pyloxone_audio.diagnostic_events import DiagnosticEmitter

    other = DiagnosticEmitter(b"other-synthetic-key", lambda _: None)
    assert diag.alias("content", "x") != other.alias("content", "x")


@pytest.mark.parametrize(
    "route,content,parent",
    [
        (
            "audio/7/library/play/library%3Alocal%3Atrack%3Afive/parentpath/library%3Alocal%3Afolder%3Aalbum/4",
            "library:local:track:five",
            "library:local:folder:album",
        ),
        (
            "audio/7/serviceplay/spotify/account/spotify%3Atrack%3Afive/parentpath/spotify%3Aplaylist%3Aalbum/4",
            "spotify:track:five",
            "spotify:playlist:album",
        ),
    ],
)
def test_content_and_parent_correlate_between_encoded_send_and_native_feedback(
    route, content, parent
):
    diag = emitter(lambda _: None)
    clean = diag.route(route)
    assert clean is not None
    assert diag.alias("content", content) in clean
    assert clean.endswith("/parentpath/" + diag.alias("parent", parent) + "/4")
    assert content not in clean and parent not in clean


@pytest.mark.parametrize("prefix", ["spotify", "spotify@synthetic-account"])
@pytest.mark.parametrize("kind", ["track", "episode"])
@pytest.mark.parametrize("parent", [False, True])
def test_per_item_noshuffle_route_keeps_only_fixed_flag_and_keyed_aliases(prefix, kind, parent):
    from urllib.parse import quote

    diag = emitter(lambda _: None)
    content = f"{prefix}:{kind}:synthetic-private-item"
    route = "audio/7/serviceplay/spotify/synthetic-account/" + quote(content, safe="")
    if parent:
        route += "/parentpath/spotify%3Aalbum%3Asynthetic-private-parent/13"
    clean = diag.route(route + "/noshuffle")
    assert clean is not None and clean.endswith("/noshuffle")
    assert diag.alias("content", content) in clean
    assert "synthetic-private" not in clean and "synthetic-account" not in clean
    if parent:
        assert clean.endswith("/13/noshuffle")


@pytest.mark.parametrize("route", [
    "audio/7/serviceplay/spotify/account/spotify%3Aalbum%3Afive/noshuffle",
    "audio/7/serviceplay/radio/world/tunein%3Astation%3Afive/noshuffle",
    "audio/7/library/play/library%3Alocal%3Atrack%3Afive/noshuffle",
    "audio/7/serviceplay/spotify/account/spotify%3Atrack%3Afive/noshuffle/untrusted",
    "audio/7/serviceplay/spotify/account/spotify%3Atrack%3Afive/parentpath/private/13/untrusted",
])
def test_unrecognized_item_flag_variants_are_not_exported(route):
    assert emitter(lambda _: None).route(route) is None
