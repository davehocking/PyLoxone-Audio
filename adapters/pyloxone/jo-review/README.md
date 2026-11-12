# Review the audio adapter — 0.1.7

**Library and adapter 0.1.7 · frontend r14 · stock PyLoxone base 0.10.3.**

Start with the [full stock 0.10.3 patch](audio-0.1.7-on-stock-0.10.3.patch), the [file map](FILE-MAP-0.1.7.md) and [exact-input manifest](PATCH-MANIFEST-0.1.7.json). The library supplies audio communication/state; the adapter retains the existing Loxone configuration, entities, authentication and lifecycle.

## Review and adopt

1. Inspect the focused adapter changes and library `session.py` / `grouping.py`; review native frontend source separately. Group and room volume are separate actions, and queued room targets use current room feedback.
2. Optionally reproduce the [offline checks](OFFLINE-VALIDATION.md) from the complete source download. Normal testers need only the [installer](../../../preview-build/README.md).
3. Rebase the intended changes onto the actual destination branch, preserving newer host changes; do not overwrite a newer host with an old whole-file snapshot.
4. Test affected configuration, services and lifecycle on that branch, then release its adapter with the exact `PyLoxone-Audio==0.1.7` pin and matching r14 frontend.

The [0.1.6 → 0.1.7 patch](audio-0.1.6-to-0.1.7.patch) targets the public 0.1.6 adapter; the [0.1.5 → 0.1.7 patch](audio-0.1.5-to-0.1.7.patch) targets the exact public 0.1.5 adapter. Both assume stock 0.10.3 beneath the adapter and reconstruct the same complete target. They are not interchangeable with an unknown feature branch.

## Customised installations

If you have custom climate, sensor, translation or other changes, keep your full backup and original tree. Make an offline copy on a separate branch. Select the patch matching its original **public adapter** version and run `git apply --check` there first. Even if it applies, inspect the diff and retained custom files; resolve conflicts individually rather than forcing or replacing the component. Compare the result with the file map and exact-input manifest, retain the matching library pin/frontend, then test your custom features in a separate HA test installation before adoption. If the starting tree is not one of those public baselines, first identify its actual base and adapt the focused changes manually. The guarded installer deliberately refuses modified trees; it is not the adoption tool for a custom branch.

## Try the complete build

Follow [installation/update/rollback](../../../preview-build/README.md). Set **Audioserver host** and enable **Use Audio Server player play/pause (experimental; off by default)** in the existing Loxone entry. That option also gates Browse/Search, source return, supported seeking, modes, announcements and enhanced grouping; diagnostics is separate and optional. Update both early-module and any retained dashboard resource registration to the same new URL, or remove the obsolete audio duplicate.

Try your usual room/group/source controls and report what you tried, expected and heard/saw. Native player volume affects only its room; the custom manager's **Group volume** is explicit. See [normal controls](../../../USER-GUIDE.md) and [current limits](../../../KNOWN-ISSUES.md).
