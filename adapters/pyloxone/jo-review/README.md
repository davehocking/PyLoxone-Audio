# Review the audio adapter — 0.1.6

**Library and adapter 0.1.6 · unchanged frontend r13 · PyLoxone base 0.10.3.**

## Review and reproduce

1. Inspect the [focused 0.1.5 → 0.1.6 adapter patch](audio-0.1.5-to-0.1.6.patch) and [per-file map](FILE-MAP-0.1.6.md). The [complete patch](audio-0.1.6-on-stock-0.10.3.patch) is for a clean stock 0.10.3 base. Their [manifest](PATCH-MANIFEST-0.1.6.json) pins the exact inputs and reconstructed files.
2. Review the library's `native.py`, `session.py` and `metadata.py`: one entry-owned authenticated command connection, one reader and one in-flight request, conservative retirement on uncertainty, and bounded playback/idle/unload ownership. Existing command/source/group eligibility and no-replay guards remain in their original callers.
3. Reproduce the [offline checks](OFFLINE-VALIDATION.md), including the real registered services, Browse fairness and mapped playback/unload controls. The [release notes](../../../RELEASE-NOTES-0.1.6.md) distinguish synthetic latency evidence from household performance.
4. For adoption into a newer upstream branch, rebase the focused changes onto that branch rather than copying this entire snapshot. Retain its configuration, entity and lifecycle ownership and rerun the affected tests.
5. Release the host adapter and exact `PyLoxone-Audio==0.1.6` pin together. A separately published library does not update existing HA integration files by itself.

The adapter still uses the existing Loxone entry, entities and authentication provider. The library owns Audio Server command/reply sessions; the Miniserver and metadata/event connections are separate, not duplicate command sockets. No daemon or connection pool is added.

## Try the complete build

Follow the [installation and rollback guide](../../../preview-build/README.md). Set **Audioserver host** and enable **Use Audio Server player play/pause (experimental; off by default)** in the existing Loxone entry; that also gates Browse/Search, source return, seeking, modes, announcements and enhanced grouping. Diagnostics is separate and optional. Frontend r13 is unchanged.

Keep the existing entry/entities and test ordinary room/group/source controls, cold and warm Browse/transport, idle reopen and unload/reload on your installation. Connection reuse does not diagnose the separately reported static-group or capability issues. [The user guide](../../../USER-GUIDE.md) covers normal controls.
