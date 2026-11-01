---
name: diagnosing-backup
description: Diagnose Hermes backup and restore issues — backup creation failures, restore errors, checkpoint corruption, and import/export problems.
version: 1.0.1
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
- `hermes checkpoints clear` — wipe all checkpoints (irreversible)
- `hermes doctor` — flags backup/restore issues

## 2. Common failures

### Backup creation fails

**Symptom:** `hermes backup` exits with error or produces an empty/corrupt zip.

**Cause:** Insufficient disk space, permission errors, or large files exceeding zip limits.

**Fix:**
```bash
cfg=$(hermes config path)
hermes backup --output /tmp/hermes-backup.zip
ls -lh /tmp/hermes-backup.zip
# Check disk space:
df -h "$(dirname "$cfg")"
# Check permissions:
ls -la "$(dirname "$cfg")"
```

### Restore fails

**Symptom:** `hermes import <file>` fails with "invalid archive" or "version mismatch".

**Cause:** Backup from incompatible Hermes version, or corrupt zip file.

**Fix:**
```bash
# Verify zip integrity:
unzip -t /path/to/backup.zip
# Check Hermes version:
hermes --version
# Restore (overwrites existing files; back up current state first):
hermes backup --output /tmp/pre-restore.zip
hermes import /path/to/backup.zip
```

Note: `hermes import` overwrites existing files in Hermes home. There is no `--merge` option. Back up current state before restoring.

### Checkpoint corruption

**Symptom:** `hermes checkpoints list` shows corrupted entries, or checkpoint restore fails.

**Cause:** Disk write interrupted, or checkpoint file permissions wrong.

**Fix:**
```bash
hermes checkpoints status                # show store size and breakdown
hermes checkpoints list                  # alias for status
hermes checkpoints prune                 # delete orphan/stale checkpoints
# Only if prune is insufficient and you accept full loss:
# hermes checkpoints clear              # IRREVERSIBLE — deletes entire store
```

### Backup too large

**Symptom:** Backup zip exceeds reasonable size, or backup takes too long.

**Cause:** Large session logs, cache, or venv included in backup.

**Fix:**
```bash
cfg=$(hermes config path)
du -sh "$(dirname "$cfg")"/*            # find large directories
# Use --quick for a smaller backup:
hermes backup --quick --output /tmp/hermes-backup.zip
# Or prune sessions first:
hermes sessions prune --older-than 30d
hermes backup --output /tmp/hermes-backup.zip
```

Note: `hermes backup` has built-in exclusions. There is no `--exclude` option.

### Import path conflicts

**Symptom:** Restore overwrites existing config or creates duplicate entries.

**Cause:** Restoring to a non-empty Hermes home. Import overwrites existing files.

**Fix:**
```bash
# Back up current state first:
hermes backup --output /tmp/pre-restore.zip
# Inspect archive contents before restoring:
unzip -l /path/to/backup.zip
# Restore to a fresh profile to avoid overwriting:
hermes profile create restored
hermes -p restored import /path/to/backup.zip
```

## 3. Verification

```bash
cfg=$(hermes config path)
hermes backup --output /tmp/test-backup.zip
unzip -t /tmp/test-backup.zip           # verify integrity
hermes checkpoints status                # checkpoints healthy
hermes doctor                            # no backup/restore errors
```

Pass: backup creates valid zip; checkpoints healthy; doctor shows no errors.

Fail: backup corrupt — check disk space and permissions; restore fails — verify archive integrity and Hermes version.

After applying fixes, restart the session to pick up restored configuration.

## 4. Related

- `diagnosing-storage` — disk space and storage issues
- `diagnosing-sessions` — session data and pruning
- `installing-hermes` — installation and setup

*Facts re-verified 2026-11-01 against upstream source at commit `40804ce4074c561220c4a766e116e07b4873b1c3` (hermes_cli/subcommands/backup.py, hermes_cli/subcommands/import_cmd.py, hermes_cli/checkpoints.py). Re-verify before reuse.*