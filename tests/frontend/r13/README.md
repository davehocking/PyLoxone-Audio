# Focused frontend checks

Optional developer checks for the group manager's outstanding-request handling and cold follower-to-leader grouping entry. These are synthetic browser tests, not speaker playback tests. They use the released HA frontend and no HA instance, credentials or household data. The strict assertion modules and synthetic fixture identities are recorded in [LINEAGE.json](LINEAGE.json).

Prerequisites: Node.js 22+, npm, Python 3.14, `uv`, and an installed Chromium executable. From the complete source bundle's `repository/` directory, substitute a new `OUTPUT` directory and your `CHROMIUM_PATH`:

```sh
OUTPUT=/path/to/new-frontend-output
CHROMIUM_PATH=/path/to/chromium
mkdir "$OUTPUT"
npm ci --prefix adapters/pyloxone/frontend --ignore-scripts
uv venv --python python3.14 "$OUTPUT/venv"
uv pip install --python "$OUTPUT/venv/bin/python" home-assistant-frontend==20261028.5
NATIVE=$("$OUTPUT/venv/bin/python" -c 'import hass_frontend,pathlib; print(pathlib.Path(hass_frontend.__file__).parent)')
node adapters/pyloxone/frontend/build.mjs "$OUTPUT/card.js"
CHROMIUM_PATH="$CHROMIUM_PATH" node tests/frontend/r13/browser.mjs "$OUTPUT/warning" "$NATIVE" "$OUTPUT/card.js" warning-stable
CHROMIUM_PATH="$CHROMIUM_PATH" node tests/frontend/r13/browser.mjs "$OUTPUT/route" "$NATIVE" "$OUTPUT/card.js" route
```

Both commands must exit zero and write `result.json` in their own result directories. The wrapper permits HTTP/WebSocket traffic only to its own synthetic loopback server. Extra warning modes such as `warning-context-aba`, `warning-auth`, `warning-timeout` and `warning-early-failure` retain invalidation, settlement, no-replay and failure controls in the same assertion module. The route case requires a fresh native dialog and its **first** grouping click, with no service calls.

Use a fresh output directory for each run. Chromium profiles are removed after execution; result/trace files stay in that output directory. The installer does not need these tools. [Maintainer overview](../../../adapters/pyloxone/jo-review/README.md).
