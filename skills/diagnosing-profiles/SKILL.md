---
name: diagnosing-profiles
description: Diagnose Hermes multi-profile issues — profile not found, config not isolated, profile switching failures, and clone/sync-imports problems.
version: 1.0.1
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
- `hermes config path` — resolve default profile config
- `hermes profile create <name>` — create a new profile
- `hermes profile delete <name>` — delete a profile

## 2. Common failures

### Profile not found

**Symptom:** `hermes -p <name>` fails with "profile not found" or "No such profile".

**Cause:** Profile directory doesn't exist under the profiles root, or profile name has a typo.

**Fix:**
```bash
hermes profile list                      # list available profiles
# Resolve the active home:
cfg=$(hermes config path)
echo "Active home: $(dirname "$cfg")"
ls "$(dirname "$cfg")/../profiles/" 2>/dev/null || ls ~/.hermes/profiles/  # check filesystem
# Create if missing:
hermes profile create <name>
```

### Profile config not isolated

**Symptom:** Changes in one profile affect another, or config leaks between profiles.

**Cause:** Profile shares HERMES_HOME with default, or symlinked config directory.

**Fix:**
```bash
default_cfg=$(hermes config path)
profile_cfg=$(hermes -p <name> config path)
echo "Default: $default_cfg"
echo "Profile: $profile_cfg"
# They must differ:
test "$default_cfg" != "$profile_cfg" && echo "Isolated: OK" || echo "LEAK: same config path"
# Verify profile dir is real, not symlink:
ls -ld "$(dirname "$profile_cfg")"
```

### Profile switching fails

**Symptom:** `hermes -p <name>` starts but uses wrong config or default profile.

**Cause:** Shell alias or wrapper script overrides `-p` flag, or HERMES_HOME env var set incorrectly.

**Fix:**
```bash
# Check env vars (no values printed):
python3 -c "import os; print([k for k in os.environ if 'hermes' in k.lower()])"
which hermes                             # check for wrapper
hermes -p <name> config path            # verify profile is used
```

### Clone with sync-imports fails

**Symptom:** `hermes profile create <name> --clone --sync-imports` fails or doesn't carry imports.

**Cause:** Source profile has no `import-sync.json`, or plugin not installed.

**Fix:**
```bash
# Resolve source profile home:
src_cfg=$(hermes -p <source> config path)
ls "$(dirname "$src_cfg")/import-sync.json"  # check source has sync manifest
hermes plugins list                      # verify agent-importers installed
hermes profile create <name> --clone --sync-imports
```

Note: cloning copies `import-sync.json` from the source profile directory. It does not require the import plugin to be installed for the copy to succeed.

### Profile deletion leaves orphaned data

**Symptom:** After deleting a profile, disk usage doesn't decrease, or stale config remains.

**Cause:** Profile directory not fully removed, or shared resources (venv, cache) remain.

**Fix:**
```bash
hermes profile delete <name>
cfg=$(hermes config path)
ls "$(dirname "$cfg")/profiles/<name>" 2>/dev/null && echo "still exists" || echo "cleaned"
```

## 3. Verification

```bash
hermes profile list                      # all profiles listed
default_cfg=$(hermes config path)
profile_cfg=$(hermes -p <name> config path)
test "$default_cfg" != "$profile_cfg" && echo "Isolation: OK"
hermes -p <name> doctor                 # no errors
```

Pass: profile resolves correctly; config is isolated; doctor shows no errors.

Fail: profile not found or config leaks — check profile directory and env vars.

After applying fixes, restart the session to pick up profile changes.

## 4. Related

- `diagnosing-config` — config parsing issues
- `diagnosing-path` — path resolution issues
- `installing-hermes` — installation and profile setup

*Facts re-verified 2026-11-01 against upstream source at commit `40804ce4074c561220c4a766e116e07b4873b1c3` (hermes_cli/profiles.py, hermes_constants.py). Re-verify before reuse.*