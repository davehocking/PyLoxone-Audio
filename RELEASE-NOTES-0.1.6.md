# 0.1.6 — reduced command wait-time

Library and reference adapter **0.1.6**, exact dependency `PyLoxone-Audio==0.1.6`, on PyLoxone **0.10.3**. Frontend **r13** is unchanged.

## What changes

The adapter reuses one authenticated Audio Server command connection across its rooms. Clean warm commands and sequential Browse requests no longer open, authenticate and close a new connection each time. Native replies, source confirmation and existing ownership checks are still required; commands are not automatically replayed after uncertain failures.

The connection remains available while mapped rooms report fresh playback. Otherwise it closes after five minutes without meaningful command activity. Background status/event traffic does not renew that allowance, and expiry does not close an in-flight request. A later required read or command can open a new connection. Reload/unload closes the owned reader and connection.

## Evidence and limits

Paired offline tests used identical native sends, response delays and outcomes against exact 0.1.5 and 0.1.6. Four clean requests used one handshake instead of four. Injected connection/authentication/close delays produced lower full-operation warm latency through both the native transport and registered HA services. These are synthetic benchmarks, not measured household Browse or speaker latency. Cold setup, slow source responses and a request already in progress can still delay another command; Browse releases the shared lock between individual requests.

This release does not diagnose or claim to fix the separately reported static-group, capability-flapping or next/previous eligibility issues. Existing group/source/announcement behaviour and operation deadlines are unchanged. The native protocol has no demonstrated unique per-request ID for distinguishing a delayed byte-identical reply to a later identical command; uncertain sessions are retired conservatively.

## Install and check

Follow [the installation/rollback guide](https://github.com/davehocking/PyLoxone-Audio/blob/v0.1.6/preview-build/README.md). In the existing Loxone entry, set **Audioserver host** and enable **Use Audio Server player play/pause (experimental; off by default)**. Diagnostics remains separate and optional. Keep the matching library/adapter pair and the unchanged r13 frontend; the library alone does not update HA integration files.
