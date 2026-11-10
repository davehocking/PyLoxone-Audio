# Optional developer validation

These instructions are optional for developers, not installation prerequisites.
Use the complete source bundle, the separately downloaded tested release wheel,
the supplied [helper](offline/test_project.py) and
[fixture descriptor](offline/QUALIFIED-FIXTURE.json). Do not substitute the
repository runner for this HA command: the helper explicitly loads
`pytest_homeassistant` before plugin autoload in the matching fixture.

Prerequisites: Linux Docker, the exact stock PyLoxone 0.10.3 source matching
`BASE.json`, a new output directory writable by UID 1000, and the separately
supplied local test-tools image
`sha256:80cfe2bbf2ef0fc81dc0925fd367ea262fe8404b467daae93d97c059b55e2946`.
The image is not distributed with the source or required to try the integration;
obtain it from the project owner if absent. It provides Python 3.14.10,
Core/pytest-homeassistant 2026.11.0, pytest 9.0.3, pytest-asyncio 1.4.0 and
pytest-socket 0.8.1. Never mount real HA configuration or credentials.

Extract the complete source bundle and enter its `repository/` directory.
Replace the three absolute path placeholders and the wheel checksum from the
release checksums. Do not use the smaller installation preview as the source root.

```sh
REPO=$(pwd -P)
HOST_BASE=/path/to/exact-stock-0.10.3
OUTPUT=/path/to/new-release-check-output
WHEEL=/path/to/tested/pyloxone_audio-0.1.4.post1-py3-none-any.whl
WHEEL_SHA256=<WHEEL-SHA256>
IMAGE=sha256:80cfe2bbf2ef0fc81dc0925fd367ea262fe8404b467daae93d97c059b55e2946
docker image inspect "$IMAGE" >/dev/null || exit 1
python -c 'from pathlib import Path; import hashlib,sys; p=Path("adapters/pyloxone/jo-review/offline/test_project.py"); sys.exit(0 if hashlib.sha256(p.read_bytes()).hexdigest()=="f45df66323bc08e5a2a9906790a1751dd4bbb4940d6067fec93dd86313390e1e" else "Helper hash mismatch")' || exit 1
printf '%s  %s\n' "$WHEEL_SHA256" "$WHEEL" | sha256sum --check --status || exit 1
mkdir "$OUTPUT" || exit 1
python -m zipfile -e "$WHEEL" "$OUTPUT/exact-wheel" || exit 1
docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges \
  --user 1000:1000 --read-only --pids-limit 256 \
  --tmpfs /scratch:rw,mode=1777 --tmpfs /tmp:rw,mode=1777 \
  --mount "type=bind,source=$REPO,target=/repo,readonly" \
  --mount "type=bind,source=$REPO/adapters/pyloxone/jo-review/offline/test_project.py,target=/work/test_project.py,readonly" \
  --mount "type=bind,source=$HOST_BASE,target=/host-base,readonly" \
  --mount "type=bind,source=$OUTPUT,target=/review" \
  --workdir /repo --env TMPDIR=/scratch --env PYTHONDONTWRITEBYTECODE=1 \
  --entrypoint python "$IMAGE" /work/test_project.py adapter \
  --library-root /review/exact-wheel --host-base /host-base \
  --work-dir /review/jo-focused \
  --case tests/adapter/test_automation_action_compatibility_ha.py
```

Expect 22 passed, exit 0, `jo-focused/result.json`, `result.xml`,
`actual-imports.json` and `input-manifest.json`. Compare case identities, unchanged
inputs and loaded library hashes with the tested wheel. Expanding a wheel is an
offline test input, not Home Assistant dependency installation. The image's warm
older development package is not the selected release library.

For portable tests and packaging, see [CONTRIBUTING-RELEASE.md](../../../CONTRIBUTING-RELEASE.md).
[Back to the short review guide](README.md).
