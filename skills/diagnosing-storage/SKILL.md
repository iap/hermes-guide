---
name: diagnosing-storage
description: Diagnose Hermes storage issues — state.db size, disk pressure, session database bloat, and cleanup opportunities.
version: 1.0.2
metadata:
  hermes:
    tags: [hermes, storage, disk, troubleshooting]
    related_skills: [hermes-configuration-guide, diagnosing-host-pressure, hermes-disk-housekeeping]
---

# Diagnosing Storage

Goal: reduce any storage problem to one concrete fix — a database optimization, a cleanup command, or a disk pressure resolution.

## 1. How to inspect

- `hermes guide` — runs `check_storage` (state.db size audit)
- `hermes sessions optimize-storage` — reclaim space from session database
- `du -sh ~/.hermes/` — total Hermes disk usage
- `du -sh ~/.hermes/state.db` — session database size

## 2. Common failures

### state.db too large

**Symptom:** `hermes guide` storage check warns; `hermes sessions optimize-storage` is slow.

**Cause:** Accumulated session history without cleanup; large context resends stored in DB.

**Fix:**
```bash
hermes sessions optimize-storage   # reclaim space (stop gateway first)
# Or prune old sessions:
hermes sessions list --limit 50
hermes sessions delete <session_id>
```

### Disk pressure (host full)

**Symptom:** Hermes commands fail with "No space left on device"; sessions can't be saved.

**Cause:** Host disk full; Hermes state.db + logs + caches consume space.

**Fix:**
```bash
df -h /                          # check disk usage
du -sh ~/.hermes/*               # Hermes breakdown
# Clean caches:
find ~/.hermes/cache/scratch -maxdepth 1 -type f -delete  # scratch files (24h TTL anyway)
# Prune old sessions:
hermes sessions optimize-storage
# See hermes-disk-housekeeping skill for full cleanup
```

### state.db missing

**Symptom:** `hermes guide` storage check reports "no state.db yet".

**Cause:** Hermes hasn't run yet, or $HERMES_HOME points to wrong directory.

**Fix:**
```bash
hermes config path               # verify $HERMES_HOME
ls -la $(hermes config path | xargs dirname)/state.db
# If genuinely missing, run Hermes once to create it:
hermes --version
```

### state.db unreadable

**Symptom:** `hermes guide` storage check reports STORAGE_UNREADABLE.

**Cause:** Permission error, corrupted file, or dangling symlink.

**Fix:**
```bash
ls -la ~/.hermes/state.db
file ~/.hermes/state.db
# Fix permissions:
chmod 600 ~/.hermes/state.db
# If corrupted, back up and let Hermes recreate:
mv ~/.hermes/state.db ~/.hermes/state.db.bak
hermes --version
```

## 3. Verification

```bash
hermes guide               # storage check healthy
du -sh ~/.hermes/state.db  # size reasonable
hermes sessions optimize-storage  # completes without error
```

Pass: storage check shows healthy; state.db size is reasonable.

Fail: storage check shows warning — re-check disk usage and state.db.

## Verification

After applying the fix:

```bash
hermes guide               # storage check healthy
du -sh ~/.hermes/state.db  # size reasonable
hermes sessions optimize-storage  # completes without error (stop gateway first)
```

Pass: storage check shows healthy; state.db size is reasonable.

Fail: storage check shows warning — re-check disk usage and state.db.


## 4. Related

- `hermes-disk-housekeeping` — full disk cleanup procedures
- `diagnosing-host-pressure` — OOM and host load issues
- `diagnosing-sessions` — session health issues

*Facts re-verified 2026-10-31 against upstream source at commit `cedf4a3d78675283fa93e4e6ea2d6212bf414667`: `hermes_cli/checks.py` (check_storage), `hermes_constants.py` (get_hermes_home). Re-verify before reuse.*