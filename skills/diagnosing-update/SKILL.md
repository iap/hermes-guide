---
name: diagnosing-update
description: Diagnose Hermes update issues — stale update lock, dead owner PID, wedged checkout, and update failures.
version: 1.0.2
metadata:
  hermes:
    tags: [hermes, update, troubleshooting]
    related_skills: [hermes-configuration-guide, hermes-post-update, diagnosing-path]
---

# Diagnosing Updates

Goal: reduce any update problem to one concrete fix — a lock removal, a retry, or a manual checkout update.

## 1. How to inspect

- `hermes guide` — runs `check_update_lock` (stale lock audit)
- `hermes update` — trigger an update
- `hermes --version` — current version
- `ls ~/.hermes/installs/*/source-completion-*` — pending update state

## 2. Common failures

### Stale update lock (dead owner, held checkout)

**Symptom:** `hermes guide` reports broken update lock; `hermes update` hangs or fails.

**Cause:** Previous update process died but left the lock held on the checkout.

**Fix:**
```bash
# Check lock candidates
ls ~/.hermes/installs/*/source-completion-pending 2>/dev/null
# If owner PID is dead, the lock is genuinely wedged.
# DO NOT delete the lock while a holder exists.
# Identify the exact holder PID from the lock file before acting.
# Wait for the holder to finish, or use a supported stop procedure.
# Then retry:
hermes update
```

### Stale update lock (dead owner, free checkout)

**Symptom:** `hermes guide` reports informational (not broken) stale lock.

**Cause:** Previous update completed but left residue. Harmless.

**Fix:**
```bash
# Safe to remove (human confirmation required) — exact paths only:
rm ~/.hermes/installs/*/source-completion-pending
rm ~/.hermes/installs/*/source-completion-attempts
# Then retry:
hermes update
```

### Update layout unrecognized

**Symptom:** `hermes guide` reports UPDATE_LAYOUT_UNRECOGNIZED.

**Cause:** Install layout doesn't match expected patterns (git checkout, ZIP root).

**Fix:**
```bash
hermes config path           # verify $HERMES_HOME
ls ~/.hermes/installs/       # check install directories
# If layout is non-standard, prefer hermes update.
# Manual fallback requires locating the actual install directory first:
ls ~/.hermes/installs/       # identify the install root
# Then run from that directory:
# cd <install-root> && git pull && pip install -e .
```

### macOS < 13 node toolchain issue

**Symptom:** Update fails on macOS < 13 with node v25+ (libc++ symbol missing).

**Cause:** Node v25+ requires `__libcpp_verbose_abort` which Monterey doesn't export.

**Fix:**
- Pin node to a host-compatible 24.x build in `pm/lock.json` using the official nodejs.org SHASUMS256 digests; keep `--without cua-driver` only for the separate CUA-driver failure.
- Then run `hermes pm install node`.
- If the update tail has already hit its six-attempt cap, clear `~/.hermes/installs/<install-id>/source-completion-pending` and `source-completion-attempts`, then run one uninterrupted `hermes` command. Do not run a full `hermes update` as the resume step: its re-resolution can replace the pin.
- See `docs/agent/deep-ops.md` (macOS < 13 host limitation) and AGENTS.md "Traps" for details.

### Pending update tail

**Symptom:** Every `hermes` command triggers a multi-minute retry loop.

**Cause:** `source-completion-pending` file exists; Hermes tries to finish the update tail.

**Fix:**
```bash
rm ~/.hermes/installs/*/source-completion-pending
rm ~/.hermes/installs/*/source-completion-attempts
# Let one uninterrupted hermes command finish
hermes --version
```

## 3. Verification

```bash
hermes guide               # update check healthy
hermes update              # completes without error
hermes --version           # shows expected version
```

Pass: update check shows healthy; `hermes update` completes.

Fail: update check shows broken — check for stale locks or layout issues.

## Verification

After applying the fix:

```bash
hermes guide               # update check healthy
hermes update              # completes without error
hermes --version           # shows expected version
```

Pass: update check shows healthy; `hermes update` completes.

Fail: update check shows broken — check for stale locks or layout issues.


## 4. Related

- `hermes-post-update` — post-update verification and cleanup
- `installing-hermes` — install/reinstall procedures
- `diagnosing-path` — path resolution issues

*Facts re-verified 2026-10-31 against upstream source at commit `cedf4a3d78675283fa93e4e6ea2d6212bf414667`: `hermes_cli/checks.py` (check_update_lock), `hermes_cli/plugins_cmd_update.py`. Staged-Node recovery cross-checked 2026-11-11 against upstream `dcfbaf06` and `docs/agent/deep-ops.md`: the macOS < 13 fix is a hand-set `pm/lock.json` pin plus clearing `source-completion-{pending,attempts}` before one uninterrupted `hermes` run; `--without cua-driver` only addresses the separate CUA-driver failure. Re-verify before reuse.*