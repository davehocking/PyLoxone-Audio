# Review the audio adapter

**Documentation revision:** library **0.1.4.post1**, adapter **0.1.4**, frontend **r12**. The patch is based on stock PyLoxone **0.10.3**, commit `026e8b931fc1de0412f7c8bcc0daa615d1fa91fb`.

## What to review

Start with **`audio-0.1.4.post1-on-stock-0.10.3.patch`** and the [per-file change map](FILE-MAP-0.1.4.md). They show the complete audio-adapter change against stock PyLoxone. Please focus on whether the library/adapter interface, existing-entry setup, entity behaviour and connection/task cleanup fit PyLoxone.

The library handles native audio communication; the adapter supplies existing authentication and connects it to the current integration. Users keep one integration and their room entities. The [user guide](../../../USER-GUIDE.md) describes the grouping and playback behaviour to compare against.

For an update from the released 0.1.3 audio adapter (0.10.3.dev18), use `audio-0.1.3-to-0.1.4.post1.patch`. Use the stock-0.10.3 patch for a first adoption. `audio-aligned-0.1.4-to-0.1.4.post1.patch` is only for the previously supplied aligned adapter 0.1.4 snapshot; it changes the dependency pin alone, not an arbitrary maintainer branch. [Exact baselines and hashes](PATCH-MANIFEST-0.1.4.post1.json) are available if needed.

## Try the preview, if useful

Use [the installation and rollback guide](../../../preview-build/README.md). Enable **Use Audio Server player play/pause (experimental; off by default)** after setting **Audioserver host**. The setting also enables the other enhanced audio controls. Diagnostics is optional and separate.

The adapter pins `PyLoxone-Audio==0.1.4.post1` for normal Home Assistant dependency resolution.

## Development and integration

[Optional developer validation](OFFLINE-VALIDATION-0.1.4.md) describes the
qualified test environment and supplied helper. It is not an installation step.
For integration into another host revision, rebase the focused changes, retain
the matching library pin and preserve existing entries, settings and entities.

[Per-file map](FILE-MAP-0.1.4.md) · [User limits](../../../KNOWN-ISSUES.md)
