# Per-file review map — 0.1.3 reference adapter

This is the cumulative audio diff from exact stock PyLoxone 0.10.3, not a claim
a replacement for every future host revision. Test paths identify the relevant
software coverage.

- `audio-dev18-on-stock-0.10.3.patch`: **32 changed files**, +5173/−39 text lines, 1 binary files.
- `audio-0.1.2-to-dev18.patch`: **33 changed files**, +2718/−139 text lines, 0 binary files.

The incremental older-audio comparison contains stock 0.10.2→0.10.3 host changes.
Do not count them as new audio features. The release adapter uses the normal public 0.1.3 library pin.

| File under custom_components/loxone | What / why | Existing test evidence |
|---|---|---|
| `__init__.py` | Entry-owned diagnostics startup/stop and native setup integration | `tests/adapter/test_audio_diagnostics_ha.py` |
| `audio.py` | Library metadata coordinator facade, not a second state engine | `tests/adapter/test_automation_action_compatibility_ha.py (assembly/service compatibility only; see broader accepted engineering selection)` |
| `audio_announcement.py` | Native announcement wrapper and existing guards; no household night policy | `tests/adapter/test_audio_announcement.py` |
| `audio_artwork.py` | Existing safe artwork adapter; no new artwork fix | `tests/adapter/test_automation_action_compatibility_ha.py (assembly/service compatibility only; see broader accepted engineering selection)` |
| `audio_catalogue.py` | Catalogue facade for native Browse/Search | `tests/adapter/test_audio_catalogue.py` |
| `audio_diagnostics.py` | Opt-in bounded HA journal, timing/correlation and privacy | `tests/adapter/test_diagnostic_outcomes_v2_ha.py` |
| `audio_grouping.py` | Shared owner, exact automation grouping and current native tokens | `tests/adapter/test_automation_group_intent_ha.py` |
| `audio_models.py` | Library model facade for entity consumers | `tests/adapter/test_automation_action_compatibility_ha.py (assembly/service compatibility only; see broader accepted engineering selection)` |
| `audio_radio.py` | Native radio facade; deferred latency is not fixed | `tests/adapter/test_audio_radio.py` |
| `audio_sources.py` | Source-return facade and existing target guards | `tests/adapter/test_native_source_return_ha.py` |
| `config_flow.py` | Audio host/playback configuration on the existing entry | `tests/adapter/test_automation_action_compatibility_ha.py (assembly/service compatibility only; see broader accepted engineering selection)` |
| `const.py` | Audio setup constants preserving upstream platform support | `tests/adapter/test_automation_action_compatibility_ha.py (assembly/service compatibility only; see broader accepted engineering selection)` |
| `coordinator.py` | Current-token callbacks, diagnostic and command lifecycle ownership | `tests/adapter/test_audio_diagnostics_lifecycle_run86.py` |
| `diagnostics.py` | Existing admin diagnostic download with bounded audio report | `tests/adapter/test_diagnostics_environment_ha.py` |
| `manifest.json` | Exact compatible dependency and native logger registration | `tests/adapter/test_automation_action_compatibility_ha.py` |
| `media_player.py` | Standard room entities, grouped sources/seek and typed services | `tests/adapter/test_grouped_media_source_ha.py` |
| `music-placeholder.png` | Existing placeholder image; no new artwork policy | `tests/adapter/test_automation_action_compatibility_ha.py (assembly/service compatibility only; see broader accepted engineering selection)` |
| `pyloxone_api/audioserver.py` | Library transport compatibility facade | `tests/adapter/test_automation_action_compatibility_ha.py (assembly/service compatibility only; see broader accepted engineering selection)` |
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

Hashes, full baseline inventories and line statistics are in [PATCH-MANIFEST-DEV18.json](PATCH-MANIFEST-DEV18.json).
Complete engineering assembly: 68 files. Installable preview excludes the three packaged upstream test files, leaving 65 component files.
[Review/adoption checklist](README.md).
