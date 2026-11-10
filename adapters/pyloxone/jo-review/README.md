# Review the audio adapter

**Library and adapter 0.1.5 · frontend r13 · stock base PyLoxone 0.10.3** (`026e8b931fc1de0412f7c8bcc0daa615d1fa91fb`). Users keep the existing integration, configuration and room entities; the library owns native audio, while this adapter supplies authentication and HA lifecycle/services.

## Choose the right comparison

- Updating the actual previous public release (adapter 0.1.4, library 0.1.4.post1): **[incremental host patch](audio-0.1.4-post1-to-0.1.5.patch)**. Only the manifest version/pin changes; update the frontend module too. The [frontend source patch](frontend-r12-to-r13.patch) is separate.
- First adoption on stock 0.10.3: **[complete host patch](audio-0.1.5-on-stock-0.10.3.patch)**.

Neither patch is based on `audio-0.1.1-review`; reconcile that branch separately rather than overwriting its changes. The [per-file map](FILE-MAP-0.1.5.md) explains the full adapter. Please focus on interface fit, existing-entry/entity behaviour and connection/task cleanup. No full regression programme is needed for initial feedback.

## Try it, if useful

Use the [installer and rollback guide](../../../preview-build/README.md). Set **Audioserver host** and enable **Use Audio Server player play/pause (experimental; off by default)**; it gates the other enhanced audio controls too. Diagnostics is optional. The manifest pins `PyLoxone-Audio==0.1.5` through normal HA dependency handling.

The [user guide](../../../USER-GUIDE.md) describes normal controls and feedback. [Optional developer checks](OFFLINE-VALIDATION.md) are separate from installation. When incorporating changes into another host revision, rebase them, preserve settings/entities and publish the matching library pin with the host release.
