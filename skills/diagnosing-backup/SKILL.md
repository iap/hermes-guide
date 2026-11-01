---
name: diagnosing-backup
description: Diagnose Hermes backup and restore issues — backup creation failures, restore errors, checkpoint corruption, and import/export problems.
version: 1.0.0
metadata:
  hermes:
    tags: [hermes, backup, restore, checkpoints, troubleshooting, diagnosing]
    related_skills: [diagnosing-storage, diagnosing-sessions, installing-hermes]
---

# Diagnosing Backup

Goal: reduce any backup/restore problem to one concrete fix — a backup creation failure, a restore error, or checkpoint corruption.

## 1. How to inspect

- `hermes backup` — create a backup of Hermes home
- `hermes import <file>` — restore from a backup zip
- `hermes checkpoints status` — show checkpoint store size and breakdown
- `hermes checkpoints list` — alias for status
- `hermes checkpoints prune` — delete orphan/stale checkpoints
- `hermes checkpoints clear` — wipe all checkpoints
- `hermes doctor` — flags backup/restore issues

## 2. Common failures

### Backup creation fails

**Symptom:** `hermes backup` exits with error or produces an empty/corrupt zip.

**Cause:** Insufficient disk space, permission errors, or large files exceeding zip limits.

**Fix:**
```bash
hermes backup --output /tmp/hermes-backup.zip
ls -lh /tmp/hermes-backup.zip
# Check disk space:
df -h ~/.hermes
# Check permissions:
ls -la ~/.hermes/
```

### Restore fails

**Symptom:** `hermes import <file>` fails with "invalid archive" or "version mismatch".

**Cause:** Backup from incompatible Hermes version, or corrupt zip file.

**Fix:**
```bash
# Verify zip integrity:
unzip -t /path/to/backup.zip
# Check Hermes version compatibility:
hermes --version
# Restore with force if version mismatch is acceptable:
hermes import /path/to/backup.zip --force
```

### Checkpoint corruption

**Symptom:** `hermes checkpoints list` shows corrupted entries, or checkpoint restore fails.

**Cause:** Disk write interrupted, or checkpoint file permissions wrong.

**Fix:**
```bash
hermes checkpoints list                  # list checkpoints
hermes checkpoints show <id>            # inspect details
# Clear corrupted checkpoints:
hermes checkpoints clear
# Re-create by running a checkpointed operation
```

### Backup too large

**Symptom:** Backup zip exceeds reasonable size, or backup takes too long.

**Cause:** Large session logs, cache, or venv included in backup.

**Fix:**
```bash
du -sh ~/.hermes/*                      # find large directories
# Exclude large dirs:
hermes backup --exclude logs,cache,venv
# Or manually prune first:
hermes sessions prune --older-than 30d
```

### Import path conflicts

**Symptom:** Restore overwrites existing config or creates duplicate entries.

**Cause:** Restoring to a non-empty Hermes home without merge handling.

**Fix:**
```bash
# Back up current state first:
hermes backup --output /tmp/pre-restore.zip
# Restore with merge:
hermes import /path/to/backup.zip --merge
# Or restore to a fresh profile:
hermes profile create restored --clone
hermes -p restored import /path/to/backup.zip
```

## 3. Verification

```bash
hermes backup --output /tmp/test-backup.zip
unzip -t /tmp/test-backup.zip           # verify integrity
hermes checkpoints list                  # checkpoints healthy
hermes doctor                            # no backup/restore errors
```

Pass: backup creates valid zip; checkpoints list cleanly; doctor shows no errors.

Fail: backup corrupt — check disk space and permissions; restore fails — verify version compatibility.

## 4. Related

- `diagnosing-storage` — disk space and storage issues
- `diagnosing-sessions` — session data and pruning
- `installing-hermes` — installation and setup

*Facts re-verified 2026-11-01 against upstream source at commit `40804ce4074c561220c4a766e116e07b4873b1c3` (installed Hermes CLI: `hermes backup --help`, `hermes import --help`, `hermes checkpoints --help`). Re-verify before reuse.*