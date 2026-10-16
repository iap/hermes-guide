---
name: diagnosing-runtime
description: "Diagnose Hermes runtime failures — CLI commands that produce no output, exit 0 with no diagnostic text, hang, or return empty (e.g. hermes guide prints nothing, hermes --version is blank). Covers stuck source updates, broken node dependencies, and recovery routes when the runtime itself is the problem."
version: 1.0.0
metadata:
  hermes:
    tags: [hermes, runtime, cli, node, update, recovery, troubleshooting]
    related_skills: [hermes-configuration-guide, diagnosing-triage, diagnosing-desktop, installing-hermes]
---

# Hermes Runtime Diagnostics

When the Hermes CLI itself is broken — commands produce no output, exit 0 with
no diagnostic text, hang, or return empty — the problem is the runtime, not
any config surface. This skill covers the diagnosis and recovery.

## Symptoms

- `hermes guide` exits 0 but prints no scope output (just "finishing an interrupted source update" or nothing)
- `hermes --version` returns empty or hangs
- `hermes doctor` produces no output
- CLI commands hang indefinitely (exit 124 from timeout)
- Plugin load timeouts ("load timed out after 10s")

## Step 1 — Confirm the scope

Run these in order. If any produces normal output, the runtime is fine and
the issue is config-level (use `diagnosing-triage` instead).

```bash
hermes --version
hermes config path
hermes plugins list
```

If all three return empty or hang, proceed to Step 2.

## Step 2 — Check for a stuck source update

The most common cause: an interrupted `hermes update` leaves the runtime in a
degraded state where every CLI invocation tries to finish the update before
doing anything else.

**Symptoms:** every command prints "finishing an interrupted source update..." and then either hangs or exits 0 with no real output.

**Recovery:**

```bash
# Retry the update
hermes update

# If that exits 0 but doesn't fix it, check for lock files
ls ~/.hermes/.update-lock 2>/dev/null
ls ~/.hermes/.source-update.lock 2>/dev/null

# Remove stale locks (they prevent the update from completing)
rm -f ~/.hermes/.update-lock ~/.hermes/.source-update.lock

# Retry
hermes update
```

## Step 3 — Check node dependencies

The Hermes runtime depends on node for its own operation (the CLI, plugin
loading, desktop app). A broken node install blocks everything.

```bash
# Check if the active node symlink exists
ls -la ~/.hermes/tools/node/bin/node

# If missing, check for versioned installs
ls ~/.hermes/tools/node-*/bin/node

# If versioned installs exist, create the symlink
ln -sf ~/.hermes/tools/node-*/ ~/.hermes/tools/node

# Verify
~/.hermes/tools/node/bin/node --version
```

**If no node binary exists at all**, the package manager needs to reinstall it:

```bash
hermes pm doctor
hermes pm install node
```

## Step 4 — Check plugin load health

If the CLI partially works but plugins fail:

```bash
# Check which plugins are enabled
python3 -c "import yaml; c=yaml.safe_load(open('$HOME/.hermes/config.yaml')); print(c.get('plugins',{}).get('enabled',[]))"

# Check plugin discovery
hermes plugins list 2>&1 | head -20
```

Plugins that time out during load (e.g. "load timed out after 10s") may
indicate:
- A plugin with a broken import or missing dependency
- A plugin trying to connect to an external service during load
- Resource exhaustion (see `diagnosing-host-pressure`)

**Temporary workaround:** disable the failing plugin in `config.yaml`:

```yaml
plugins:
  enabled:
    # Remove or comment out the failing plugin
    # - telegram-platform
```

Then restart the session.

## Step 5 — Direct config inspection (bypass the CLI)

When the CLI is completely unusable, read config directly:

```bash
# Config location
cat ~/.hermes/config.yaml

# Plugin directory
ls ~/.hermes/plugins/

# Skills directory
ls ~/.hermes/skills/ | head -20

# Recent errors
tail -50 ~/.hermes/logs/errors.log
tail -50 ~/.hermes/logs/agent.log
```

This lets you diagnose config-level issues (wrong paths, missing files,
syntax errors) without a working CLI.

## Step 6 — Recovery escalation

If none of the above resolves the issue:

1. **Restart the session** — a fresh process may clear stuck state
2. **Check for stale processes:** `ps aux | grep hermes` — kill any zombie Hermes processes
3. **As a last resort, reinstall Hermes** — see `installing-hermes`

## When to use this vs other skills

- **This skill:** CLI produces no output, commands hang, runtime is broken
- **`diagnosing-triage`:** CLI works, but something is misconfigured
- **`diagnosing-desktop`:** Desktop app specifically won't launch
- **`diagnosing-plugins`:** A specific plugin won't load (but CLI works)
- **`installing-hermes`:** Fresh install or complete reinstall needed

*Facts verified 2026-10-16 against Hermes Agent v0.21.5+2176.g962d453.dirty (2026.9.24) on macOS 12.7.6; node v24.13.1 and v20.18.0 under ~/.hermes/tools/. Re-verify before reuse.*
