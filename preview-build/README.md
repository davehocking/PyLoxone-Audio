# Install or upgrade PyLoxone-Audio

**Library 0.1.4 · reference adapter 0.10.3.dev19 · frontend r12.** The manifest pins the public `PyLoxone-Audio==0.1.4` package. It was checked with HA Core 2026.11.0 / Python 3.14.10. The library needs Python >=3.14; the guarded installer needs Linux with atomic rename support.

Download and extract the **[0.1.4 installation bundle](https://github.com/davehocking/PyLoxone-Audio/releases/download/v0.1.4/PyLoxone-Audio-0.1.4-docs2-install.zip)**, then work from its top-level folder. It includes the preview ZIP, `preview.py`, `PROVENANCE.json`, `SHA256SUMS` and frontend file. Developer source/tests are a separate optional download; you do not need a Docker image to install it.

## Before changing anything

- Make a full Home Assistant backup, download a copy elsewhere and confirm how to restore it. Keep the previous matching library and frontend file/registration for rollback.
- Keep your existing Loxone entry and entities; do not delete/re-add them. Pause automatic integration updates while trying the preview.
- Stop Core normally before replacing files. No Audio Server or Miniserver restart is needed.

The installer accepts a fresh installation, exact stock PyLoxone 0.10.3 with or without its three hash-pinned packaged test files, this exact preview, or the 0.1.3 audio preview. It backs up and restores the complete recognised layout, including packaged tests. Other edited, partial or extra-file layouts are refused. If refused, keep the original files and ask for a matching upgrade route; do not delete files to force it.

<a id="public-dependency"></a>

## Install or upgrade

1. Home Assistant Core needs access to PyPI to resolve the manifest's exact `PyLoxone-Audio==0.1.4` requirement and its dependencies. No wheel placement or manual pip install is needed. Do not install into an add-on or substitute a different package build.

2. Replace `<ZIP-SHA256>` below with the preview ZIP's value in `preview-build/SHA256SUMS`, and set your stopped config/backup paths. Use a new backup directory outside the configuration:

```sh
python preview-build/preview.py verify --archive preview-build/PyLoxone-0.10.3.dev19-audio-0.1.4-r12-docs2-preview.zip --sha256 <ZIP-SHA256>
python preview-build/preview.py install --archive preview-build/PyLoxone-0.10.3.dev19-audio-0.1.4-r12-docs2-preview.zip --sha256 <ZIP-SHA256> --config /path/to/stopped/config --backup /path/outside/config/new-component-backup
```

The helper replaces the complete component and keeps a component backup. It does not install Python dependencies, configure HA or install the frontend. Keep any reported `.loxone-recovery-*` directories if it fails; do not retry blindly.

## Frontend

Copy `preview-build/frontend/group-control-card-0.1.4-r12.js` to `/config/www/pyloxone-audio/group-control-card-0.1.4-r12.js`.

Merge this into your existing configuration, preserving other frontend settings:

```yaml
frontend:
  extra_module_url:
    - /local/pyloxone-audio/group-control-card-0.1.4-r12.js
```

Replace the previous audio module URL with this r12 URL; do not register both versions. Keep an already-working matching registration rather than adding it twice. A dashboard resource alone does not load it for every native Home/area panel. Keep wheels, backups and diagnostic files out of `www`.

## Start and try it

1. Run the normal configuration check (`ha core check` on HAOS), then start Core normally (`ha core start`). If the check fails, keep the error and recover rather than bypassing it.
2. Use your existing Loxone entry. On a fresh installation only, add Loxone once through **Settings > Devices & services**.
3. In the entry's configuration/options set **Audioserver host**, enable **Use Audio Server player play/pause (experimental; off by default)** (`audioserver_playback: true`) and save. This enables the other enhanced audio controls too. Keep your other options and diagnostics preference. No separate Spotify login/integration is needed.
4. Check your room players are still available with their usual identities/settings. Refresh the browser, open a player's expanded controls and check **Join** opens **Audio groups**. If controls look old, refresh the frontend cache before restarting the backend again.

Use the [short user guide](../USER-GUIDE.md) to try the features you use in a suitable room/time. There is no mandatory full regression checklist: useful feedback is what you tried, what you expected and what you heard/saw. If something fails, [collect a diagnostic report](../DIAGNOSTICS.md). Group edits can interrupt sound; previous-source bookmarks can be lost across a restart.

## Roll back if needed

Stop Core. With the same unchanged installation and component backup:

```sh
python preview-build/preview.py rollback --config /path/to/stopped/config --backup /path/outside/config/new-component-backup
```

That reverses **component files only**. Restore the previous matching library through HA's normal dependency route and the previous frontend file/registration too. If the previous native state is uncertain, use the full HA backup rather than copying Python packages or `.storage` files by hand. Do not force a refusal from changed files/backups.

Check configuration, start normally and refresh the browser. Confirm the previous players and controls are back. Automatic PyLoxone updates can overwrite the preview; do not reapply these full files over a different upstream version.

[User guide](../USER-GUIDE.md) · [Automation](../AUTOMATION-GROUPING.md) · [Report a problem](../DIAGNOSTICS.md)
