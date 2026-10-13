---
name: hermes-post-update
description: Verify and clean up after a Hermes update — confirm the gateway restarted on new code, check plugin migrations, review config changes, run health checks, and surface cleanup opportunities.
version: 1.0.0
metadata:
  hermes:
    tags: [hermes, update, verification, maintenance]
    related_skills: [installing-hermes, diagnosing-gateway, diagnosing-plugins]
---

# Hermes Post-Update

Run after `hermes update` to verify the update landed correctly, catch silent
migrations, and surface cleanup opportunities. The updater handles code and
dependencies but does not restart gateways, review config changes, or report
what moved.

## When to use

- After any `hermes update` (manual or automatic)
- After a desktop app update
- When the gateway seems stale or unresponsive after an update
- As periodic maintenance (weekly)

## Workflow

### 1. Confirm the update landed

```bash
hermes --version
```

Check the version string. If it still shows the old version, the update may not
have completed — check `logs/update.log` for errors.

### 2. Verify the gateway restarted on new code

```bash
hermes gateway status
```

If the output contains:

> ⚠ A previous `hermes update` pulled new code but did not restart running gateways.

Run:

```bash
hermes gateway restart
```

Then confirm the new PID:

```bash
hermes gateway status
```

The PID should differ from the pre-restart value. If the gateway process is
still running old code (check `Get-CimInstance Win32_Process` on Windows or
`ps aux | grep hermes` on POSIX), a restart is required.

### 3. Check for plugin migrations

Recent updates have moved functionality out of core into plugins:

| Plugin | What it replaces | Install command |
|---|---|---|
| `honcho` | Memory provider (built into core pre-0.21.5) | `hermes plugins install honcho` |
| `homeassistant` | Home Assistant integration (built into core pre-0.21.5) | `hermes plugins install hermes-homeassistant` |
| `hermes-session-reset-policy` | `session_reset.mode: both` behavior | `hermes plugins install hermes-session-reset-policy` |

Check which are installed:

```bash
hermes plugins list
```

If a plugin is listed as `not enabled` but was previously active, enable it:

```bash
hermes plugins enable <name>
```

### 4. Review config format changes

Updates may bump the config schema version. Check for per-profile changes:

```bash
hermes config path
```

If the update log shows `config format updated (v46 → v50)` or similar, review
the new schema:

```bash
hermes config migrate --dry-run
```

### 5. Review skills sync

The updater syncs bundled skills but preserves user-modified copies. Check what
was updated vs. kept:

```bash
hermes skills list-modified
```

For each user-modified skill, decide:
- **Keep** — your local changes are intentional
- **Reset** — discard local changes and accept the upstream version:

```bash
hermes skills reset <skill-name>
```

### 6. Run health check

```bash
hermes doctor
```

Categorize the output:

| Category | Action |
|---|---|
| Auto-fixable | Run `hermes doctor --fix` |
| Manual (API keys, tokens) | User must provide credentials |
| Informational | No action needed |

### 7. Cleanup opportunities

#### Stale autoshash entries

The updater stashes local changes before pulling. Old entries accumulate:

```bash
git -C "$HERMES_HOME/hermes-agent" stash list
```

Entries older than 7 days with `hermes-update-autostash-` prefix are safe to
drop:

```bash
git -C "$HERMES_HOME/hermes-agent" stash drop stash@{N}
```

#### Large WAL file

If `hermes doctor` reports a large WAL file:

```bash
hermes sessions optimize-storage
```

This reclaims ~60% of `state.db` and is safe to interrupt/re-run.

#### Disk headroom

```bash
df -h "$HERMES_HOME"
```

If free space drops below 10 GB, investigate large directories before the
next update (the updater needs several GB for dependencies and backups).

### 8. Report

Present findings in the standard format:

#### Summary
Update to v0.21.5+9802 completed. Gateway restarted (PID 29780). Two plugin
migrations applied (honcho, homeassistant). Three items need attention.

#### Findings

| Severity | What | Evidence |
|---|---|---|
| MEDIUM | `session_reset.mode: both` deprecated | Gateway log: "no longer applied" — install `hermes-session-reset-policy` |
| LOW | 3 stale autoshash entries | `git stash list` shows entries from 2026-09-03 |
| INFO | 4 skills updated, 15 user-modified kept | `hermes skills list-modified` |

#### Recommended Actions
1. Install `hermes-session-reset-policy` to restore old reset behavior
2. Review user-modified skills: `hermes skills list-modified`
3. Drop stale autoshash entries (optional, cosmetic)

#### References
- `logs/update.log` — full update output
- `logs/gateway.log` — gateway restart confirmation
- `hermes doctor` — health check results

---

*Facts re-verified 2026-10-12 against upstream source at commit `a082d1e180be1e603a6a307fce4d098e30f54eb7`: `hermes_cli/update_cmd.py` (update workflow, gateway restart detection, plugin migration logic, skills sync, autoshash handling); `hermes_cli/main.py` (doctor --fix, config migrate, plugins list/enable, skills list-modified/reset, sessions optimize-storage). Re-verify before reuse.*
