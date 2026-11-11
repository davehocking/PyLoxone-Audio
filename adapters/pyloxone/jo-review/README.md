# Review the audio adapter — 0.1.5

**Library and adapter 0.1.5 · frontend r13 · PyLoxone base 0.10.3.**

## Review the changes

Use the [complete adapter patch](audio-0.1.5-on-stock-0.10.3.patch) to review the integration changes against PyLoxone 0.10.3. The [per-file summary](FILE-MAP-0.1.5.md) explains each part.

The adapter connects the audio library to Home Assistant authentication, lifecycle and services. It keeps the existing Loxone entry and room entities. The library owns native audio communication; the frontend supplies the room-group controls.

Please focus on interface fit, existing-entry/entity behaviour and connection/task cleanup. No full regression programme is needed for initial feedback.

## Try the complete build

Follow the [installation and rollback guide](../../../preview-build/README.md), including the matching frontend. Set **Audioserver host** and enable **Use Audio Server player play/pause (experimental; off by default)** in the existing Loxone entry. Diagnostics is optional. Home Assistant resolves `PyLoxone-Audio==0.1.5` from the adapter manifest.

The [user guide](../../../USER-GUIDE.md) covers normal controls. [Developer checks](OFFLINE-VALIDATION.md) are optional and separate from installation.
