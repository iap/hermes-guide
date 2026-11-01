---
name: diagnosing-config
description: Diagnose Hermes configuration issues — config.yaml not parsing, missing file, wrong path, orphaned settings, and legacy key migration.
version: 1.0.0
metadata:
  hermes:
    tags: [hermes, config, troubleshooting]
    related_skills: [hermes-configuration-guide, diagnosing-path]
---

# Diagnosing Configuration

Goal: reduce any config problem to one concrete fix — a YAML syntax correction, a path change, or a key migration.

## 1. How to inspect

- `hermes config path` — resolves the active config file (ground truth for $HERMES_HOME)
- `hermes config show` — dumps effective config after merge
- `hermes doctor` — flags config parse errors
- `hermes guide` — runs `check_config_parses` (config check)

## 2. Common failures

### Config file missing

**Symptom:** `hermes config path` points to a non-existent file.

**Cause:** First run without config bootstrap, or $HERMES_HOME points to wrong directory.

**Fix:**
```bash
hermes config path          # verify the path
cfg=$(hermes config path)
ls -la "$cfg"  # check existence
# If missing, create minimal config:
mkdir -p "$(dirname "$cfg")"
echo "model:" > "$cfg"
```

### Config does not parse (YAML syntax error)

**Symptom:** `hermes doctor` reports CONFIG_UNPARSEABLE; `hermes guide` shows config check as broken.

**Cause:** Invalid YAML — tabs instead of spaces, unquoted special characters, missing colons.

**Fix:**
```bash
# Validate YAML syntax
python -c "import yaml; yaml.safe_load(open('$cfg'))"
# Common fixes:
# - Replace tabs with spaces
# - Quote strings with colons: "key: value" not key: value
# - Ensure proper indentation (2 spaces per level)
```

### Wrong $HERMES_HOME

**Symptom:** Config changes don't take effect; Hermes uses different settings than expected.

**Cause:** $HERMES_HOME env var overrides default location; profile-specific home.

**Fix:**
```bash
echo "HERMES_HOME=$HERMES_HOME"
hermes config path   # ground truth
# If mismatched, unset or correct HERMES_HOME:
unset HERMES_HOME
# Or set explicitly:
export HERMES_HOME=/path/to/correct/.hermes
```

### Orphaned / legacy settings

**Symptom:** Settings in config.yaml have no effect; Hermes ignores them.

**Cause:** Hermes migrated from flat keys to nested structure, or keys were renamed.

**Fix:**
- Check `hermes-configuration-guide` for the current key structure
- Move legacy flat keys to their nested equivalents
- Remove deprecated keys

### Config path unresolved

**Symptom:** `hermes config path` fails or returns empty.

**Cause:** Hermes installation broken, or running from wrong environment.

**Fix:**
```bash
which hermes
hermes --version
# Reinstall if needed: see installing-hermes skill
```

## 3. Verification

```bash
hermes config path          # resolves correctly
hermes config show          # dumps effective config
hermes doctor               # no config errors
hermes guide               # config check healthy
```

Pass: config check shows healthy; `hermes config show` reflects your edits.

Fail: config check shows broken — re-check YAML syntax and $HERMES_HOME.

## Verification

After applying the fix:

```bash
# Confirm config parses
hermes config path          # resolves correctly
hermes config show          # dumps effective config
hermes doctor               # no config errors
hermes guide               # config check healthy
```

Pass: config check shows healthy; `hermes config show` reflects your edits.

Fail: config check shows broken — re-check YAML syntax and $HERMES_HOME.


## 4. Related

- `hermes-configuration-guide` — full config map and key reference
- `diagnosing-path` — path resolution issues
- `diagnosing-plugins` — plugin config issues

*Facts re-verified 2026-10-31 against upstream source at commit `cedf4a3d78675283fa93e4e6ea2d6212bf414667`: `hermes_cli/config.py` (load_config, config path resolution), `hermes_constants.py` (get_hermes_home). Re-verify before reuse.*