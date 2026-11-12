# Adapter 0.1.7 file map

The full patch targets stock PyLoxone **0.10.3**, commit `026e8b931fc1de0412f7c8bcc0daa615d1fa91fb`. Incremental patches separately target public adapters **0.1.5** and **0.1.6**. See [the manifest](PATCH-MANIFEST-0.1.7.json) for exact source and reconstructed files.

| Files / surface | What and why | Relevant checks |
|---|---|---|
| `media_player.py`, `audio_grouping.py` | Existing room entities retain native room volume; explicit group service uses balanced additive adjustment. Reuse one synchronous membership projection. | Registered room/group service, queued-room rebasing and rejection controls |
| `services.yaml`, translations | Describe explicit group action and volume-specific errors. | Service/schema and language checks |
| `audio_diagnostics.py` | Report volume failures without mislabelling playback. | Diagnostics/export checks |
| `manifest.json` | Adapter 0.1.7, exact library pin. | Owning version/import checks |
| Library `session.py` | Accept the native once-decoded folder echo only for catalogue reads. | Nested HA Library traversal, exact write-echo negative controls |
| Library `grouping.py` | Rebase queued absolute room requests after admission; retain group balance, fences and deadlines. | Portable and owning rebase/supersession cases |
| Frontend `group-manager.js`, `native-group-manager.js`, `follower-mode-controls.js` | Native Core 2026.11.1 Group entry, follower controls, explicit group-volume contract and 300 ms unsent tap batching. | Compiled native caller and literal service replay checks |
| Existing audio/lifecycle files in the cumulative patch | Supply the audio transport, catalogue, source return, announcements and entry-owned cleanup required by the stock host. Incremental patches avoid repeating unchanged files. | Portable policies and focused HA owning-service checks |
| Current guides, preview and baseline manifests | Keep the exact pair, static module and supported installation/recovery route together. | Patch reconstruction, preview/install/refusal/rollback and packaging checks |

The Miniserver and Audio Server event connections have different roles from the reusable command session. No new service or connection pool is required. Optional developer reproduction is in [Offline validation](OFFLINE-VALIDATION.md); physical playback and custom-branch adoption remain installation-specific.
