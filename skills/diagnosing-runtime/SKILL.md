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

Resolve `$HERMES_HOME` first — every path below hangs off it: `hermes config
path` prints the config file, its directory is the home (POSIX default
`~/.hermes`, native Windows `%LOCALAPPDATA%\hermes`). Named profiles re-home
to `<root>/profiles/<p>`, and `$HERMES_RUNTIME_DIR` overrides tool paths —
never hardcode `~/.hermes`.

## Symptoms

- `hermes guide` exits 0 but prints no scope output (just "finishing an interrupted source update" or nothing)
- `hermes --version` returns empty or hangs
- `hermes doctor` produces no output
- CLI commands hang indefinitely (exit 124 from timeout)
- Plugin load timeouts ("load timed out after 10s")

## Step 1 — Confirm the scope, per probe

Run these in order; route on the FIRST one that misbehaves, not on the first
that works:

```bash
hermes --version
hermes config path
hermes plugins list
hermes guide
```

- `hermes config path` hanging/empty → home unresolvable: fix that first
  (hermes-configuration-guide Step 0), then re-run the probes.
- `hermes plugins list` failing → Step 4 (plugin load health) directly.

- `hermes --version` empty/hanging → the classic CLI is Python, not node:
  suspect the interpreter/venv/shim (see `diagnosing-path`), then continue
  with Step 5 (direct inspection) here — not Step 3.
- Version works but `hermes guide` prints nothing → stay here: the guide
  plugin itself fails to load — continue with Step 4 (plugin load health),
  not `diagnosing-triage` (triage's baseline needs a working guide).
- Version works and guide works → the runtime is fine; the issue is
  config-level (use `diagnosing-triage` instead).

## Step 2 — Check for a stuck source update

The most common cause: an interrupted `hermes update` leaves the runtime in a
degraded state where every CLI invocation tries to finish the update before
doing anything else.

**Symptoms:** every command prints "finishing an interrupted source update..." and then either hangs or exits 0 with no real output.

**Recovery:**

```bash
# Retry the update
hermes update
```

If the wedge persists, the checkout lock or the owed completion tail is
involved — do not invent lock filenames. The lock lives at `<git common
dir>/hermes-update.lock` (or `<install root>/.hermes-update.lock` for a ZIP
install), and an owed tail is recorded as a `source-completion-pending`
marker. Follow the diagnosing-cli-tui stale-lock note for the liveness
verdicts (live owner → wait; dead owner + free lock → human-confirmed
removal; dead owner + held lock → wait, never delete) — including its
no-baseline exception, since a fully wedged CLI cannot run any check first.

## Step 3 — Check node dependencies (TUI/desktop scope only)

Node matters for the TUI (node-pty), the desktop app, and node-backed tools —
not for the classic CLI, which is Python (`hermes --version` blank points at
the interpreter/venv/shim per Step 1, never here). PM keeps one versioned
directory per tool under `$HERMES_HOME/tools/` named
`<tool>-<version>-<platform>` — e.g. `node-26.7.0-win32-x64` on this Windows
host (`darwin-arm64`, `linux-x64` triplets on theirs; list the directory to
see yours, and note `$HERMES_RUNTIME_DIR` redirects the whole store) — plus
a shared `node/` tree — there is no `tools/node` symlink to repair, so never
create one by hand.

```bash
# PM's view of the managed tools (repairs the recorded environment)
hermes pm doctor

# Reinstall a missing tool by package name
hermes pm install node

# Rebuild without re-resolving
hermes pm repair
```

Verify with `hermes pm doctor` (clean) and the previously failing surface
(TUI launch, desktop start) — not by poking versioned directories directly.

## Step 4 — Check plugin load health

If the CLI partially works but plugins fail:

```bash
# Check which plugins are enabled
python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c.get('plugins',{}).get('enabled',[]))"
```
(run from the `$HERMES_HOME` resolved above — never a hardcoded home).

```bash
# Check plugin discovery
hermes plugins list 2>&1 | head -20
```

Plugins that time out during load (e.g. "load timed out after 10s") may
indicate:
- A plugin with a broken import or missing dependency
- A plugin trying to connect to an external service during load
- Resource exhaustion (see `diagnosing-host-pressure`)

**Temporary workaround:** disable the failing plugin. For a regular plugin,
comment it out of `plugins.enabled` in `config.yaml`:

```yaml
plugins:
  enabled:
    # Remove or comment out the failing plugin
    # - some-regular-plugin
```

Then restart the session. Platform sub-plugins (telegram and friends) do
NOT gate on `plugins.enabled` — check their selection key in config (see
`diagnosing-plugins`) instead of editing the list.

## Step 5 — Direct config inspection (bypass the CLI)

When the CLI is completely unusable, read config directly under the
`$HERMES_HOME` resolved above:

```bash
# Config location
cat "$HERMES_HOME/config.yaml"

# Plugin directory
ls "$HERMES_HOME/plugins/"

# Skills directory
ls "$HERMES_HOME/skills/" | head -20

# Recent errors
tail -50 "$HERMES_HOME/logs/errors.log"
tail -50 "$HERMES_HOME/logs/agent.log"
```

This lets you diagnose config-level issues (wrong paths, missing files,
syntax errors) without a working CLI.

## Step 6 — Recovery escalation

If none of the above resolves the issue:

1. **Restart the session** — a fresh process may clear stuck state
2. **Check for stale processes:** `ps aux | grep hermes` — identify stray Hermes processes before killing any; never blanket-kill
3. **As a last resort, reinstall Hermes** — see `installing-hermes`

## When to use this vs other skills

- **This skill:** CLI produces no output, commands hang, runtime is broken
- **`diagnosing-triage`:** CLI works, but something is misconfigured
- **`diagnosing-desktop`:** Desktop app specifically won't launch
- **`diagnosing-plugins`:** A specific plugin won't load (but CLI works)
- **`installing-hermes`:** Fresh install or complete reinstall needed

*Facts verified 2026-10-16 against upstream source at `9bda154d` (v0.21.7): PM-versioned tool layout under `$HERMES_HOME/tools/` (live: `node-26.7.0-win32-x64`; `pm doctor`/`install [names]`/`repair` in `hermes pm --help`); owed-tail marker `source-completion-pending` (`hermes_cli/venv_sync.py`); checkout lock names (`hermes_cli/update_lock.py`); platform selection keys over `plugins.enabled` (see diagnosing-plugins). Re-verify before reuse.*
