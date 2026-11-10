# Install or upgrade PyLoxone-Audio

**Library 0.1.5 · adapter 0.1.5 · frontend r13**, on PyLoxone 0.10.3. Requires HA Core 2026.11 / Python >=3.14 and PyPI access for `PyLoxone-Audio==0.1.5`. The file installer needs Linux with atomic rename support; it does not install dependencies or run HA.

Download and extract the [0.1.5 installer](https://github.com/davehocking/PyLoxone-Audio/releases/download/v0.1.5/PyLoxone-Audio-0.1.5-docs1-install.zip). Work from its top-level folder. No developer image or test suite is needed.

## Before you start

Make a full HA backup, keep a copy elsewhere and know how to restore it. Keep your previous bundle, matching library and frontend registration. Keep the existing Loxone entry/entities and pause automatic integration updates. Stop Core normally before replacing files; do not restart the Audio Server or Miniserver.

Supported starting points: no component, exact stock PyLoxone 0.10.3 (including its optional three packaged test files), this 0.1.5 build, or the released library 0.1.4.post1 / adapter 0.1.4 preview. Edited, partial, extra-file and other-version layouts are refused without forcing them. For an older bundle, use its original helper and unchanged backup to roll back first; keep each backup with its bundle. Ask for a matching route if refused.

## Install or upgrade

Replace `<ZIP-SHA256>` with the preview ZIP value in `preview-build/SHA256SUMS`; substitute your stopped config and a **new** backup directory outside it:

```sh
python preview-build/preview.py verify --archive preview-build/PyLoxone-Audio-0.1.5-r13-docs1-preview.zip --sha256 <ZIP-SHA256>
python preview-build/preview.py install --archive preview-build/PyLoxone-Audio-0.1.5-r13-docs1-preview.zip --sha256 <ZIP-SHA256> --config /path/to/stopped/config --backup /path/outside/config/new-component-backup
```

Keep the component backup and any reported `.loxone-recovery-*` directories. Do not blindly retry a failed replacement. HA resolves the exact library and dependencies when Core starts; no manual pip command or wheel placement is needed.

## Frontend

Copy `preview-build/frontend/group-control-card-0.1.5-r13.js` to `/config/www/pyloxone-audio/group-control-card-0.1.5-r13.js`. Preserve other frontend settings and replace the previous audio URL, registering **one** audio module:

```yaml
frontend:
  extra_module_url:
    - /local/pyloxone-audio/group-control-card-0.1.5-r13.js
```

If an older audio module is also registered as a Lovelace/dashboard resource, update it to the same `/local/pyloxone-audio/group-control-card-0.1.5-r13.js` URL shown above, or remove that obsolete audio duplicate; leave unrelated resources unchanged.

A dashboard resource alone does not cover native Home/area panels. Keep backups, wheels and diagnostics out of `www`.

## Start and use it

Run the normal configuration check (`ha core check` on HAOS), then start Core (`ha core start`). If the check fails, keep the error and recover rather than bypassing it. Use your existing Loxone entry; add one only on a fresh installation.

In **Settings > Devices & services**, open the Loxone entry options, set **Audioserver host** and enable **Use Audio Server player play/pause (experimental; off by default)**. This also enables Browse/Search, source return, supported seeking, modes, announcements and enhanced grouping. Keep other options; diagnostics is separate and optional. No separate HA Spotify login is needed.

Refresh the browser and use your usual room players. [The user guide](../USER-GUIDE.md) covers the controls. Feedback is simply what you tried, expected and heard/saw, with versions and time/timezone; [collect a diagnostic report](../DIAGNOSTICS.md) if useful. Group edits can interrupt sound, and previous-source bookmarks can be lost on restart. [Current limits](../KNOWN-ISSUES.md) remain relevant.

## Roll back

Stop Core. Using the same bundle and unchanged component backup:

```sh
python preview-build/preview.py rollback --config /path/to/stopped/config --backup /path/outside/config/new-component-backup
```

This restores **component files only**. Restore the previous matching library through HA's normal dependency handling and the previous frontend file/registration. If uncertain, use the full HA backup, not manual package or `.storage` edits. Do not force a changed-file/backup refusal. Check configuration, start Core normally and refresh the browser. Future automatic integration updates can overwrite these files; do not copy this snapshot over a different upstream version.
