# Reporting an audio problem

Audio diagnostics records recent audio actions and feedback so we can investigate a report. It is optional and off by default for new users. Your existing choice is preserved on upgrade.

## Collect and download a report

1. In **Settings > Devices & services > Entities**, filter to Loxone and turn on **Audio diagnostics** for the relevant entry.
2. Use the player normally and note the problem's time, timezone, room and source. Avoid repeatedly triggering it just to fill the log.
3. Open the Loxone entry under **Settings > Devices & services** and choose **Download diagnostics** from its menu.
4. Review the whole JSON before sharing it. Nothing uploads automatically. If you only enabled collection for this report, you can turn it off afterwards; otherwise leave your usual setting.

Include the build/version, what you did, what you expected and what you actually heard or saw. Distinguish an on-screen change from audible playback.

## Privacy and coverage

Audio events use pseudonyms and omit raw credentials and media paths, but Home Assistant's surrounding system information can still identify an installation. Do not post passwords, tokens or an unreviewed download.

Collection keeps up to 24 hours by age, subject to storage limits; a download can contain less. It cannot recover events from before it was enabled. Missing coverage, omitted records and errors are reported in the download. A command reply alone does not prove sound was heard.

Turning diagnostics on or off does not restart playback or clear bookmarks. It is separate from the experimental playback option in [Required setup](README.md#required-setup). You do not need broad DEBUG logging or a Debug console for this workflow.

[Technical report reference (optional)](https://github.com/davehocking/PyLoxone-Audio/blob/main/DIAGNOSTICS-REFERENCE.md) · [User guide](USER-GUIDE.md)
