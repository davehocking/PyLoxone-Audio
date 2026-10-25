# Spotify support: library 0.1.0 / PyLoxone adapter 0.10.2

This document describes the accepted 0.1.0 implementation, not a proposed new
Spotify integration. The host base is released PyLoxone 0.10.2, commit
`3db77b81f69c77cc814675d191061533b464df5e`. The source and exact installed
component/library runtime hashes were compared during this documentation audit.
Documentation changes do not change the installed code or rebuild release assets.

## The requirement in plain English

**Home Assistant's separate Spotify integration is optional.** A Spotify account
configured in Loxone is not the same as a Spotify integration configured in HA.
Neither the library's Python dependencies nor the adapter's HA manifest makes
HA Spotify a mandatory installation/setup dependency.

Without HA Spotify, the adapter still uses Loxone for:

- native room play/pause/stop, volume and other controls where supported;
- now-playing title, artist, artwork, source and position where supplied;
- Loxone-backed Browse/Search and starting available native catalogue content;
- Local Library, Loxone Radio, TuneIn, Line-In and Loxone-configured Spotify;
- ordinary native seeking where exposed, and bounded best-effort position return.

These still require their normal Loxone/provider configuration, supported device
capabilities and, for Audio Server commands, configured/enabled audio playback.
Optional HA Spotify does not supply those native capabilities or subscriptions.

The optional enhancement adds a different route when **selecting Spotify as a
source**: validate the already-linked Spotify account and current receiver, then
ask Loxone to resume that account's existing live Spotify session. This avoids
having to start an older remembered catalogue item when that live route qualifies.
It is not a Spotify Web API track/queue/position-restoration feature.

**The live-session Spotify return path does not restore a remembered playback
position.** It asks Loxone to resume the current Spotify session and leaves its
position to Spotify. A session continuing at some position is not evidence that
the adapter restored the point at which the room previously left Spotify.
Native manual seeking and generic best-effort catalogue position handling are
separate; neither establishes saved-position restoration for this live-session
Spotify path.

## Practical enabled-versus-disabled comparison

The additional integration changes one source-return decision, not whether a
room can play Spotify:

- **HA Spotify enabled, explicit binding, matching room-owned live session:**
  selecting Spotify can send the native resume command with an empty content
  path. It leaves Spotify's newer content/session alone rather than selecting
  an older remembered item.
- **HA Spotify disabled or absent:** native controls, metadata, Browse/Search
  and Loxone-configured Spotify remain. Returning from another source uses the
  native current/qualified remembered-content route; it can start the room's
  previous content instead of a newer Spotify session.
- **HA Spotify enabled and positively reporting another receiver:** the linked
  route rejects the request without issuing native playback. This is a real
  trade-off: enabling it can refuse a source click that the native fallback
  would otherwise start from remembered content. It does not transfer that
  receiver's playlist into the chosen room.
- **HA Spotify installed but no explicit room binding:** it adds no capability
  to that room's source selection.

`tests/adapter/test_spotify_enabled_disabled_ha.py` compares enabled/disabled
HA Spotify with matching/foreign receivers through the same real HA
`media_player.select_source` service and otherwise equivalent native history.
The four cases use synthetic external transports. They prove software paths,
not physical Spotify firmware behaviour or that a particular household request
used the enhanced path. A cached provider state with no playback is not live
proof of an HTTP204 response or of branch execution.

## What must be configured to enable the enhancement

A loaded official HA `spotify` config entry is necessary but not sufficient.
The adapter consumes the optional `audioserver_spotify_return` object in Loxone's
setup/options form. Its default is `{}`: no optional room bridge. Both setup and
options expose an object selector; no automatic room/receiver discovery is added.
Playback must be enabled when a non-empty binding is supplied.

The object maps an exact existing Loxone room/control UUID to:

- `entry_id`: the existing HA Spotify config-entry ID;
- `user_id`: that entry's exact Spotify user ID;
- `account_id`: the exact native Loxone Spotify service-account ID;
- `device_id`: the exact Spotify Connect receiver ID for that room.

These are identifiers, not credentials. Do not guess IDs or use display names
in their place. The adapter validates literal binding fields and duplicate
user/receiver assignments. It uses the already mapped Audio Server player; it
does not create another room/entity, perform an additional OAuth login, or store
another copy of Spotify credentials. The portable library never receives tokens.

## Active functions and exactly what they use

Paths below are relative to the repository. Adapter paths are under
`adapters/pyloxone/overlay/custom_components/loxone/`.

### Configuration and the real source-selector caller

- `config_flow.py:validate_loxone_setup()` and
  `spotify_continuity.py:SpotifyBinding.parse()` / `validate_bindings()` validate
  the optional mapping. `DATA_SCHEMA_SETUP` and `DATA_SCHEMA_OPTIONS` default it
  to an empty object. They do not require a Spotify integration for ordinary setup.
- `media_player.py:_create_spotify_return()` constructs `SpotifySourceReturn`
  only for an explicitly bound room with an available native playback path.
- `media_player.py:_async_optional_spotify_resume()` invokes
  `SpotifySourceReturn.async_resume_native()` only for the bound Spotify account.
  Other source/account choices do not borrow this session.

### HA integration facilities actually consumed

- `SpotifySourceReturn._session()` uses
  `hass.config_entries.async_get_entry(entry_id)`, checks domain `spotify`,
  `ConfigEntryState.LOADED`, enabled state and matching `entry.unique_id`, then
  takes **`entry.runtime_data.session`**. It requires the session's
  `async_request` and `async_ensure_token_valid` facilities. It does not use the
  HA Spotify media-player entity or its play/transfer services, coordinator
  playback cache, browser, search implementation or Spotify client wrapper.
- `SpotifySourceReturn._read()` uses that existing HA `OAuth2Session`'s
  `async_request("GET", ..., allow_redirects=False)`, decodes and releases the
  response. Token validity/refresh stays with HA's OAuth session, not a new
  library token manager.
- `SpotifySourceReturn._identity()` calls **`GET /v1/me`** and compares the
  response's **`id`** with the bound `user_id`. It does not use profile email,
  subscription, name or image fields for the source-return decision.
- `SpotifySourceReturn.async_native_session()` calls **`GET /v1/me/player`**;
  `_own_device(..., require_control=False)` compares **`device.id`** with the
  configured receiver. The active route does not require Spotify Web API
  playback control or reject a receiver merely because `is_restricted` is true.
  Missing playback/receiver identity is unavailable optional evidence; a
  positively different receiver is a conflict. The active route does not use
  Spotify's track URI, context, progress, shuffle, repeat or queue to restore
  anything, even though the playback response can contain those fields.
- `SpotifySourceReturn._native_user()` separately reads **Loxone's** native
  service-account inventory, matches the configured `account_id` and its unique
  native user label, and rejects an ambiguous/unusable inventory. This is not
  a third Spotify Web API endpoint.
- `SpotifySourceReturn.async_native_session()` holds the existing shared-account
  lock and checks request generation, lifecycle, room identity and native
  freshness around its reads. It yields only
  `SpotifyNativeSession(native_user, account_id)`, not a copied playback session.

### Playback and success confirmation

- `SpotifySourceReturn.async_resume_native()` delegates to the portable library's
  `pyloxone_audio.spotify.async_resume_native_session()` through the
  `SpotifySessionBridge` protocol.
- That library function either recognises already-playing matching native
  Spotify as a no-op, or calls `AudioServerCommands.async_spotify_handoff()`.
  The command is **Loxone** `audio/<player>/serviceplay/spotify/<account>/`.
  It does **not** call Spotify's playback/transfer/seek APIs.
- Success needs native command settlement and fresh feedback for the exact room,
  Spotify source and matched native account, with a valid Spotify track/episode
  path. It need not match the old remembered track or an exact saved position.
  Spotify keeps its current session/queue; the adapter does not reconstruct it.

## What happens without usable optional Spotify information

The source router (`pyloxone_audio/selection.py:async_optional_native_resume()`)
classifies missing optional capability separately from a real command/ownership
failure. It allows an otherwise valid native route; it does not promise every
Spotify source click will succeed without a usable native session or history.

- **No binding / no HA Spotify / unloaded entry:** ordinary native features
  remain. No missing-integration warning is required to use those features.
- **No current Spotify API playback (HTTP 204), unreadable/malformed optional
  identity, or a handled optional read failure/timeout:** the optional enhancement
  is unavailable. The routing catch covers `NativeSessionUnavailableError`
  (including `SpotifyReturnUnavailable`), `aiohttp.ClientError` and `TimeoutError`.
  A still-valid native route may proceed quietly. A superseded request, changed
  room or real native command failure is not hidden. Other exception types are
  not blanket-classified as optional absence; this is not a promise that every
  possible OAuth/token-refresh failure is silently ignored.
- **Spotify already playing for the exact native target:** a valid native
  selection can be a no-op; no queue or position replacement is needed.
- **Exact native Spotify source paused:** native `serviceplay` can resume it
  without the HA bridge; offline cases exercise absent/unavailable/read-error
  bridge paths and ensure no replacement item/queue is sent.
- **Returning from another source with qualified remembered native Spotify
  content:** the normal catalogue/last-good return is available where valid.
  That may start remembered content rather than resume a newer live session.
- **No usable current session or qualified remembered content:** use native
  Browse or Spotify Connect. The adapter must not invent a default item or
  silently transfer playback from an arbitrary other receiver.
- **A readable profile identifies another user, or playback identifies another
  receiver:** that is positive conflicting evidence; the enhanced request is
  rejected rather than downgraded to optional absence and takeover.

## Explicit non-features of the active enhancement

The current source selector does not use HA Spotify to:

- search/browse Spotify or provide room artwork/now-playing metadata;
- play/pause/stop/change volume or seek through HA's Spotify entity;
- transfer an arbitrary receiver's Spotify playback into the room;
- capture/rebuild a Spotify queue or restore a playlist/context;
- send Spotify API playback, seek, shuffle or repeat writes;
- guarantee an exact historical track, queue slot or position.

Native metadata/seek/last-good position behaviour is separate and does not become
available only when HA Spotify is installed. Switching **away** from Spotify does
not wait for an optional Spotify capture or API read.

## Retained older helpers: present is not the same as active

`spotify_continuity.py` still contains `SpotifySourceReturn.async_capture()`,
`async_resume()` and their supporting bookmark/activation helpers. Those methods
implement the earlier capture/restore approach: profile/playback and queue reads,
track/context/progress/shuffle/repeat checks and guarded provider requests via
`_send_once()` (`PUT /v1/me/player` and `PUT /v1/me/player/play`).

**The current owning source-selector path does not call `async_capture()` or
`async_resume()`.** Its controller call is `async_resume_native()` instead. Thus:

- it would be inaccurate to say the entire adapter contains no Spotify PUT code;
- it would also be inaccurate to advertise those older helpers as active
  source-selector features, or claim leaving a source captures its Spotify queue;
- direct helper tests establish those helpers' contracts, not their use by the
  current native UI. Lifecycle/fence support remaining in the module is not
  evidence that the old capture/restore route is selected.

This audit/doc update does not remove those methods or change runtime behaviour.
A cleanup, if desired, is a separate implementation change, not a hidden part of
documenting 0.1.0.

## Evidence and limits

Source trace: the active method families above, the complete adapter call-site
scan and the portable `SpotifySessionBridge` boundary. Host base and all overlay
members remain pinned in `adapters/pyloxone/BASE.json`.

Relevant existing offline owning-HA tests include:

- `tests/adapter/test_source_simple_session_ha.py`:
  `test_valid_native_spotify_session_resumes_empty_path_without_capture_queue_or_replacement`
  checks a newer live session, native `serviceplay`, untouched queue and GET-only
  provider traffic without queue reads;
  `test_leaving_spotify_never_waits_for_capture_or_provider_account_lock`
  checks no Spotify API calls while leaving.
- `tests/adapter/test_source_simple_boundaries_ha.py`:
  `test_repeated_native_spotify_returns_leave_queue_and_position_to_spotify`
  and `test_native_session_return_preserves_foreign_identity_rejection`.
- `tests/adapter/test_source_review75_ha.py`:
  `test_paused_exact_native_spotify_resume_never_replaces_item_or_queue`
  covers absent, unavailable and read-error bridge cases.
- `tests/adapter/test_spotify_continuity_ha.py`:
  `test_unavailable_optional_spotify_quietly_preserves_native_sources` exercises
  unavailable official-entry/provider cases through native source selection.

These are socket-blocked synthetic external boundaries using real owning HA
service/entity paths. They are not a new audible playback check, live Spotify
account test, firmware certification or proof that every Spotify receiver is
visible to the Web API.

External contract references: Home Assistant Core 2026.10.3
[`spotify` setup](https://github.com/home-assistant/core/blob/2026.10.3/homeassistant/components/spotify/__init__.py)
and [OAuth2 session](https://github.com/home-assistant/core/blob/2026.10.3/homeassistant/helpers/config_entry_oauth2_flow.py);
Spotify's [current-user profile](https://developer.spotify.com/documentation/web-api/reference/get-current-users-profile)
and [playback-state](https://developer.spotify.com/documentation/web-api/reference/get-information-about-the-users-current-playback)
references. These explain the external API shape, not independent certification
of this unpublished adapter or its behaviour on a household's devices.
