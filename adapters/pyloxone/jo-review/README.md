# Jo: review the audio adapter

**Library 0.1.3:** library **0.1.3**, adapter **0.10.3.dev18**, frontend **r10**. The patch is based on stock PyLoxone **0.10.3**, commit `026e8b931fc1de0412f7c8bcc0daa615d1fa91fb`.

## What to review

Start with **`audio-dev18-on-stock-0.10.3.patch`** and the [per-file change map](FILE-MAP-DEV18.md). They show the complete audio-adapter change against stock PyLoxone. Please focus on whether the library/adapter interface, existing-entry setup, entity behaviour and connection/task cleanup fit PyLoxone.

The library handles native audio communication; the adapter supplies existing authentication and connects it to the current integration. Users keep one integration and their room entities. The [user guide](../../../USER-GUIDE.md) describes the grouping and playback behaviour to compare against.

If you are comparing with the previously supplied 0.1.2 audio preview, `audio-0.1.2-to-dev18.patch` is also available. It includes stock 0.10.2→0.10.3 changes as well as audio changes; use the stock-0.10.3 patch for a first adoption. [Exact baselines and hashes](PATCH-MANIFEST-DEV18.json) are available if needed.

## Try the preview, if useful

Use [Sebastian's installation and rollback guide](../../../preview-build/README.md). Enable **Use Audio Server player play/pause (experimental; off by default)** after setting **Audioserver host**. The setting also enables the other enhanced audio controls. Diagnostics is optional and separate.

The adapter pins `PyLoxone-Audio==0.1.3` for normal Home Assistant dependency resolution.

## Development and integration

[Optional developer validation](OFFLINE-VALIDATION-DEV18.md) describes the
qualified test environment and supplied helper. It is not an installation step.
For integration into another host revision, rebase the focused changes, retain
the matching library pin and preserve existing entries, settings and entities.

[Per-file map](FILE-MAP-DEV18.md) · [User limits](../../../KNOWN-ISSUES.md)
