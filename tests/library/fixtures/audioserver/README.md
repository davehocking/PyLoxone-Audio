# Contributed Audioserver samples

Source: SebastianEitzert's PyLoxone #523 comment:
https://github.com/JoDehli/PyLoxone/issues/523#issuecomment-6251138699
Updated: 2026-10-18T14:34:04Z.
Original HTML comment body SHA-256:
`b93ed8a2db83e98a6fde19a2572093966bf2257cfa27a93e03edef256599e4cf`.

Sebastian explicitly offered the translated prototype for reuse under PyLoxone's
licence and the raw samples as test fixtures. Reused material is attributed here
under the repository's Apache-2.0 licence; see the root LICENSE.

- `sebastian_tts.json`, `sebastian_tunein.json`, `sebastian_loxone_radio.json`:
  contributor-provided, sanitised device-derived samples, JSON-reformatted only.
  His TTS JSON contains one target-zone entry, not all nine original zone rows.
  Hosts, tokens and proxy IDs remain literal placeholders; tests never fetch them.
- `sebastian_alarm_end.txt`: the contributor's compact recorded alarm-end timeline,
  copied verbatim. It is NOT a full-frame recording. Tests reconstruct minimal
  synthetic snapshots from its explicit time/event/mode observations; omitted
  modes are supplied as synthetic `play` values, not claimed as recorded facts.

Other tests use explicitly synthetic variants (including his described non-target
TTS difference), not additional device captures. These samples were not captured
from Dave's installation and do not establish its firmware/hardware compatibility.
No surrounding contributed Python code is executed by the tests.
