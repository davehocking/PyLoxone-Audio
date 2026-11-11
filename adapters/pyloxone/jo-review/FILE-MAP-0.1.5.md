# Adapter file map — 0.1.5

The [complete adapter patch](audio-0.1.5-on-stock-0.10.3.patch) shows the Home Assistant integration changes against PyLoxone 0.10.3. Its manifest requires `PyLoxone-Audio==0.1.5`.

## Home Assistant adapter

| File under custom_components/loxone | What / why |
|---|---|
| `__init__.py` | Entry-owned diagnostics startup/stop and native setup integration |
| `audio.py` | Library metadata coordinator facade, not a second state engine |
| `audio_announcement.py` | Native announcement handling and playback guards |
| `audio_artwork.py` | Artwork retrieval and fallback handling |
| `audio_catalogue.py` | Catalogue facade for native Browse/Search |
| `audio_diagnostics.py` | Opt-in bounded HA journal, timing/correlation and privacy |
| `audio_grouping.py` | Shared grouping, serial member deadlines and automation actions |
| `audio_models.py` | Library model facade for entity consumers |
| `audio_radio.py` | Native radio integration |
| `audio_sources.py` | Source-return facade and existing target guards |
| `config_flow.py` | Audio host/playback configuration on the existing entry |
| `const.py` | Audio setup constants preserving upstream platform support |
| `coordinator.py` | Current-token callbacks, diagnostic and command lifecycle ownership |
| `diagnostics.py` | Existing admin diagnostic download with bounded audio report |
| `manifest.json` | Exact compatible dependency and native logger registration |
| `media_player.py` | Standard room entities, grouped sources/seek and typed services |
| `music-placeholder.png` | Fallback artwork image |
| `pyloxone_api/audioserver.py` | Library transport compatibility facade |
| `pyloxone_api/connection.py` | Observe existing audio-only Miniserver sends without raw credentials |
| `services.yaml` | Native action fields, default-OFF explicit membership override |
| `spotify_continuity.py` | Native Spotify source-continuity handling |
| `switch.py` | Entry diagnostic switch, default OFF and existing preference retention |
| `translations/cs.json` | Audio setup, diagnostic and service translations |
| `translations/de.json` | Audio setup, diagnostic and service translations |
| `translations/en.json` | Audio setup, diagnostic and service translations |
| `translations/es.json` | Audio setup, diagnostic and service translations |
| `translations/fr.json` | Audio setup, diagnostic and service translations |
| `translations/it.json` | Audio setup, diagnostic and service translations |
| `translations/nl.json` | Audio setup, diagnostic and service translations |
| `translations/pt-BR.json` | Audio setup, diagnostic and service translations |
| `translations/pt-PT.json` | Audio setup, diagnostic and service translations |
| `translations/pt.json` | Audio setup, diagnostic and service translations |

## Frontend

The matching r13 module supplies the room-group controls. `group-manager.js` tracks pending commands until they settle; `native-group-manager.js` connects the controls to the native player dialog. Follow the [frontend setup instructions](../../../preview-build/README.md#frontend) to install the module.

[Short review guide](README.md) · [User guide](../../../USER-GUIDE.md)
