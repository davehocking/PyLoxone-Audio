# Optional developer checks

Not an installation prerequisite. Use the complete [source bundle](https://github.com/davehocking/PyLoxone-Audio/releases/download/v0.1.7/PyLoxone-Audio-0.1.7-source-preview.zip), the tested release wheel and exact stock 0.10.3 source. Never use real HA configuration or credentials. The supplied [runner](offline/test_project.py) explicitly loads the native HA test plugin and retains socket/import/warning guards.

With Linux, Python 3.14 and an isolated developer environment containing `pytest-homeassistant==2026.11.0`, setuptools, pytest-socket, PyYAML and the release wheel's dependencies, extract the source bundle and enter `repository/`. An existing environment with those prerequisites can be reused. To provision one, use `uv venv --python python3.14 /path/to/venv`, then `uv pip install --python /path/to/venv/bin/python pytest-homeassistant==2026.11.0 setuptools pytest-socket PyYAML /path/to/tested/pyloxone_audio-0.1.7-py3-none-any.whl`. Never use the running HA environment.

Substitute `PYTHON`, `HOST_BASE`, `WHEEL` and a new existing empty `OUTPUT` directory:

```sh
PYTHON=/path/to/prepared/venv/bin/python
HOST_BASE=/path/to/exact-stock-0.10.3
WHEEL=/path/to/tested/pyloxone_audio-0.1.7-py3-none-any.whl
OUTPUT=/path/to/new-release-check-output
"$PYTHON" -m zipfile -e "$WHEEL" "$OUTPUT/exact-wheel"
TMPDIR="$OUTPUT" "$PYTHON" adapters/pyloxone/jo-review/offline/test_project.py adapter --library-root "$OUTPUT/exact-wheel" --host-base "$HOST_BASE" --work-dir "$OUTPUT/adapter-check" --case tests/adapter/test_diagnostics_environment_ha.py --case tests/adapter/test_automation_action_compatibility_ha.py --case tests/adapter/test_reusable_session_ha.py
```

Expected: the selected cases pass, with `result.json`, `result.xml`, `actual-imports.json` and `input-manifest.json` under `adapter-check`. The session tests exercise native RSA/AES setup, registered services, Browse lock fairness, mapped receiver retention/unload and injected cold/warm timings. Portable policy/failure tests are in `tests/library/test_session*.py` and `test_reusable_command_session.py`. This is offline evidence, not public dependency resolution or device playback. [Focused frontend checks](../../../tests/frontend/r13/README.md) and [portable library/build instructions](../../../CONTRIBUTING-RELEASE.md) are separate.

For a later upstream rebase, apply only the intended changes, rerun affected tests, update the exact library pin and release the host adapter together. [Back to the overview](README.md).
