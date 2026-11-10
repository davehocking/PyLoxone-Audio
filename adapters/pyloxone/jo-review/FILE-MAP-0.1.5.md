# Adapter file map — 0.1.5

## Update from the previous public release

`audio-0.1.4-post1-to-0.1.5.patch` changes only `manifest.json`: adapter version 0.1.4 → 0.1.5 and exact library pin 0.1.4.post1 → 0.1.5. Python audio behaviour is unchanged. The separate frontend r13 module and its two source changes supply the UI update; replace the module URL as described in the installation guide.

`frontend-r12-to-r13.patch` is a repository-relative source patch against public commit `7954594f0d6effbf417cf7fc0e2f8f5910f4f57a`: `group-manager.js` retains an outstanding request until settlement and distinguishes ordinary feedback from invalidation; `native-group-manager.js` binds the freshly opened leader before its first grouping action. Focused synthetic regressions live in `tests/frontend/r13/`.

## Complete stock 0.10.3 comparison

`audio-0.1.5-on-stock-0.10.3.patch` contains the complete host-side audio adapter, including the inherited files below. It is separate from the library and frontend module.

| File under custom_components/loxone | What / why |
|---|---|
| `__init__.py` | Entry-owned diagnostics startup/stop and native setup integration |
| `audio.py` | Library metadata coordinator facade, not a second state engine |
| `audio_announcement.py` | Native announcement wrapper and existing guards; no household night policy |
| `audio_artwork.py` | Existing safe artwork adapter; no new artwork fix |
| `audio_catalogue.py` | Catalogue facade for native Browse/Search |
| `audio_diagnostics.py` | Opt-in bounded HA journal, timing/correlation and privacy |
| `audio_grouping.py` | Shared grouping, serial member deadlines and automation actions |
| `audio_models.py` | Library model facade for entity consumers |
| `audio_radio.py` | Native radio facade; deferred latency is not fixed |
| `audio_sources.py` | Source-return facade and existing target guards |
| `config_flow.py` | Audio host/playback configuration on the existing entry |
| `const.py` | Audio setup constants preserving upstream platform support |
| `coordinator.py` | Current-token callbacks, diagnostic and command lifecycle ownership |
| `diagnostics.py` | Existing admin diagnostic download with bounded audio report |
| `manifest.json` | Exact compatible dependency and native logger registration |
| `media_player.py` | Standard room entities, grouped sources/seek and typed services |
| `music-placeholder.png` | Existing placeholder image; no new artwork policy |
| `pyloxone_api/audioserver.py` | Library transport compatibility facade |
| `pyloxone_api/connection.py` | Observe existing audio-only Miniserver sends without raw credentials |
| `services.yaml` | Native action fields, default-OFF explicit membership override |
| `spotify_continuity.py` | Retained native compatibility/fences, not HA Spotify API bridge |
| `switch.py` | Entry diagnostic switch, default OFF and existing preference retention |
| `translations/cs.json` | Current audio setup/diagnostic/service strings; existing language coverage retained |
| `translations/de.json` | Current audio setup/diagnostic/service strings; existing language coverage retained |
| `translations/en.json` | Current audio setup/diagnostic/service strings; existing language coverage retained |
| `translations/es.json` | Current audio setup/diagnostic/service strings; existing language coverage retained |
| `translations/fr.json` | Current audio setup/diagnostic/service strings; existing language coverage retained |
| `translations/it.json` | Current audio setup/diagnostic/service strings; existing language coverage retained |
| `translations/nl.json` | Current audio setup/diagnostic/service strings; existing language coverage retained |
| `translations/pt-BR.json` | Current audio setup/diagnostic/service strings; existing language coverage retained |
| `translations/pt-PT.json` | Current audio setup/diagnostic/service strings; existing language coverage retained |
| `translations/pt.json` | Current audio setup/diagnostic/service strings; existing language coverage retained |

[Exact patch baselines and target inventory](PATCH-MANIFEST-0.1.5.json) · [Short review guide](README.md)
