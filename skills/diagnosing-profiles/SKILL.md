---
name: diagnosing-profiles
description: Diagnose Hermes multi-profile issues — profile not found, config not isolated, profile switching failures, and clone/sync-imports problems.
version: 1.0.0
metadata:
  hermes:
    tags: [hermes, profiles, troubleshooting, diagnosing]
    related_skills: [diagnosing-config, diagnosing-path, installing-hermes]
---

# Diagnosing Profiles

Goal: reduce any profile problem to one concrete fix — a profile creation issue, a path resolution error, or a config isolation failure.

## 1. How to inspect

- `hermes profile list` — list all profiles
- `hermes profile show <name>` — show profile details
- `hermes -p <name> config path` — resolve config for a specific profile
- `hermes profile create <name>` — create a new profile
- `hermes profile delete <name>` — delete a profile
- `hermes config path` — resolve default profile config

## 2. Common failures

### Profile not found

**Symptom:** `hermes -p <name>` fails with "profile not found" or "No such profile".

**Cause:** Profile directory doesn't exist under `~/.hermes/profiles/`, or profile name has a typo.

**Fix:**
```bash
hermes profile list                      # list available profiles
ls ~/.hermes/profiles/                   # check filesystem
# Create if missing:
hermes profile create <name>
```

### Profile config not isolated

**Symptom:** Changes in one profile affect another, or config leaks between profiles.

**Cause:** Profile shares `HERMES_HOME` with default, or symlinked config directory.

**Fix:**
```bash
hermes -p <name> config path            # should point to profiles/<name>/
# Verify isolation:
hermes -p <name> config show | grep -i home
ls -la ~/.hermes/profiles/<name>/        # should be a real dir, not symlink
```

### Profile switching fails

**Symptom:** `hermes -p <name>` starts but uses wrong config or default profile.

**Cause:** Shell alias or wrapper script overrides `-p` flag, or `HERMES_PROFILE` env var set.

**Fix:**
```bash
# Check env vars (redacts values):
set | grep -i hermes
which hermes                             # check for wrapper
hermes -p <name> --version              # verify profile is used
```

### Clone with sync-imports fails

**Symptom:** `hermes profile create <name> --clone --sync-imports` fails or doesn't carry imports.

**Cause:** Source profile has no `import-sync.json`, or plugin not installed.

**Fix:**
```bash
ls ~/.hermes/import-sync.json            # check source has sync manifest
hermes plugins list                      # verify agent-importers installed
hermes profile create <name> --clone --sync-imports
```

### Profile deletion leaves orphaned data

**Symptom:** After deleting a profile, disk usage doesn't decrease, or stale config remains.

**Cause:** Profile directory not fully removed, or shared resources (venv, cache) remain.

**Fix:**
```bash
hermes profile delete <name>
ls ~/.hermes/profiles/                   # verify removed
du -sh ~/.hermes/profiles/<name> 2>/dev/null || echo "cleaned"
```

## 3. Verification

```bash
hermes profile list                      # all profiles listed
hermes -p <name> config path            # resolves to correct profile dir
hermes -p <name> doctor                 # no errors
```

Pass: profile resolves correctly; config is isolated; doctor shows no errors.

Fail: profile not found or config leaks — check profile directory and env vars.

## 4. Related

- `diagnosing-config` — config parsing issues
- `diagnosing-path` — path resolution issues
- `installing-hermes` — installation and profile setup

*Facts re-verified 2026-11-01 against upstream source at commit `40804ce4074c561220c4a766e116e07b4873b1c3` (installed Hermes CLI: `hermes profile --help`, `hermes -p <name> config path`). Re-verify before reuse.*