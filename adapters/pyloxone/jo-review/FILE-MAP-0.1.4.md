# Per-file review map — 0.1.4 reference adapter

The cumulative patch targets exact stock PyLoxone 0.10.3; the incremental patch
assumes the released 0.1.3 audio adapter (0.10.3.dev18), not stock PyLoxone.

- `audio-0.1.4.post1-on-stock-0.10.3.patch`: **32 changed files**, +5174/−39 text lines, 1 binary files.
- `audio-0.1.3-to-0.1.4.post1.patch`: **2 changed files**, +4/−3 text lines, 0 binary files.

The incremental adapter delta adds a per-member qualification timeout and updates
the adapter version/library pin. The serial group-budget implementation lives in
the library; full-width sliders and matching UI deadlines live in frontend r12.

| File under custom_components/loxone | What / why | Existing test evidence |
|---|---|---|
| `__init__.py` | Entry-owned diagnostics startup/stop and native setup integration | `tests/adapter/test_audio_diagnostics_ha.py` |
| `audio.py` | Library metadata coordinator facade, not a second state engine | `tests/adapter/test_automation_action_compatibility_ha.py` |
| `audio_announcement.py` | Native announcement wrapper and existing guards; no household night policy | `tests/adapter/test_audio_announcement.py` |
| `audio_artwork.py` | Existing safe artwork adapter; no new artwork fix | `tests/adapter/test_automation_action_compatibility_ha.py` |
| `audio_catalogue.py` | Catalogue facade for native Browse/Search | `tests/adapter/test_audio_catalogue.py` |
| `audio_diagnostics.py` | Opt-in bounded HA journal, timing/correlation and privacy | `tests/adapter/test_diagnostic_outcomes_v2_ha.py` |
| `audio_grouping.py` | Shared grouping, serial member deadlines and automation actions | `tests/adapter/test_party_group_scale_ha.py` |
| `audio_models.py` | Library model facade for entity consumers | `tests/adapter/test_automation_action_compatibility_ha.py` |
| `audio_radio.py` | Native radio facade; deferred latency is not fixed | `tests/adapter/test_audio_radio.py` |
| `audio_sources.py` | Source-return facade and existing target guards | `tests/adapter/test_native_source_return_ha.py` |
| `config_flow.py` | Audio host/playback configuration on the existing entry | `tests/adapter/test_automation_action_compatibility_ha.py` |
| `const.py` | Audio setup constants preserving upstream platform support | `tests/adapter/test_automation_action_compatibility_ha.py` |
| `coordinator.py` | Current-token callbacks, diagnostic and command lifecycle ownership | `tests/adapter/test_audio_diagnostics_lifecycle_run86.py` |
| `diagnostics.py` | Existing admin diagnostic download with bounded audio report | `tests/adapter/test_diagnostics_environment_ha.py` |
| `manifest.json` | Exact compatible dependency and native logger registration | `tests/adapter/test_automation_action_compatibility_ha.py` |
| `media_player.py` | Standard room entities, grouped sources/seek and typed services | `tests/adapter/test_grouped_media_source_ha.py` |
| `music-placeholder.png` | Existing placeholder image; no new artwork policy | `tests/adapter/test_automation_action_compatibility_ha.py` |
| `pyloxone_api/audioserver.py` | Library transport compatibility facade | `tests/adapter/test_automation_action_compatibility_ha.py` |
| `pyloxone_api/connection.py` | Observe existing audio-only Miniserver sends without raw credentials | `tests/adapter/test_audio_diagnostics_miniserver_ha.py` |
| `services.yaml` | Native action fields, default-OFF explicit membership override | `tests/adapter/test_automation_action_compatibility_ha.py` |
| `spotify_continuity.py` | Retained native compatibility/fences, not HA Spotify API bridge | `tests/adapter/test_native_source_return_ha.py` |
| `switch.py` | Entry diagnostic switch, default OFF and existing preference retention | `tests/adapter/test_audio_diagnostics_preference_run86.py` |
| `translations/cs.json` | Current audio setup/diagnostic/service strings; existing language coverage retained | `tests/adapter/test_automation_action_compatibility_ha.py` |
| `translations/de.json` | Current audio setup/diagnostic/service strings; existing language coverage retained | `tests/adapter/test_automation_action_compatibility_ha.py` |
| `translations/en.json` | Current audio setup/diagnostic/service strings; existing language coverage retained | `tests/adapter/test_automation_action_compatibility_ha.py` |
| `translations/es.json` | Current audio setup/diagnostic/service strings; existing language coverage retained | `tests/adapter/test_automation_action_compatibility_ha.py` |
| `translations/fr.json` | Current audio setup/diagnostic/service strings; existing language coverage retained | `tests/adapter/test_automation_action_compatibility_ha.py` |
| `translations/it.json` | Current audio setup/diagnostic/service strings; existing language coverage retained | `tests/adapter/test_automation_action_compatibility_ha.py` |
| `translations/nl.json` | Current audio setup/diagnostic/service strings; existing language coverage retained | `tests/adapter/test_automation_action_compatibility_ha.py` |
| `translations/pt-BR.json` | Current audio setup/diagnostic/service strings; existing language coverage retained | `tests/adapter/test_automation_action_compatibility_ha.py` |
| `translations/pt-PT.json` | Current audio setup/diagnostic/service strings; existing language coverage retained | `tests/adapter/test_automation_action_compatibility_ha.py` |
| `translations/pt.json` | Current audio setup/diagnostic/service strings; existing language coverage retained | `tests/adapter/test_automation_action_compatibility_ha.py` |

Hashes and complete baselines are in [PATCH-MANIFEST-0.1.4.post1.json](PATCH-MANIFEST-0.1.4.post1.json).
The engineering assembly includes the stock packaged tests; the installable preview
omits those tests. [Short maintainer guide](README.md).
