---
name: diagnosing-sessions
description: Diagnose Hermes session issues — runaway sessions, loop signatures, context bloat, and session management problems.
version: 1.0.1
metadata:
  hermes:
    tags: [hermes, sessions, troubleshooting]
    related_skills: [hermes-configuration-guide, diagnosing-host-pressure, diagnosing-storage]
---

# Diagnosing Sessions

Goal: reduce any session problem to one concrete fix — a fresh session, a model change, or a context split.

## 1. How to inspect

- `hermes guide` — runs `check_session_health` (runaway session audit)
- `hermes sessions list` — all sessions with metadata
- `hermes sessions list --limit 50` — find session by ID
- `hermes sessions optimize-storage` — reclaim space (stop gateway first)
- `tail -100 ~/.hermes/logs/agent.log` — recent session activity

## 2. Common failures

### Runaway session (loop signature)

**Symptom:** `hermes guide` flags a session with many turns + high tool use + large context resends.

**Cause:** Free-tier model struggling with complex research; context window filling up; generate-then-verify in same turn.

**Fix:**
```bash
# Start a fresh session
hermes  # new session
# Or use a more capable model for research:
# Set model to a non-free-tier default in config.yaml
# Split work: generate in one turn, verify in another
```

### Session not found

**Symptom:** `hermes sessions list` shows no matching session ID.

**Cause:** Session expired, deleted, or wrong $HERMES_HOME.

**Fix:**
```bash
hermes sessions list          # find correct ID
hermes config path            # verify $HERMES_HOME
```

### Session database corrupted

**Symptom:** `hermes sessions list` errors; state.db unreadable.

**Cause:** Crash during write, disk full, or concurrent access.

**Fix:**
```bash
cp ~/.hermes/state.db ~/.hermes/state.db.bak
# Let Hermes recreate:
rm ~/.hermes/state.db
hermes --version
```

### Context bloat (slow responses)

**Symptom:** Responses get slower as conversation grows; high token usage.

**Cause:** Large context window accumulating; tool outputs not being compacted.

**Fix:**
- Start a new session for new topics
- Use `/compact` if available
- Reduce tool output verbosity
- See `diagnosing-host-pressure` for OOM-related slowdowns

## 3. Verification

```bash
hermes guide               # session health check passes
hermes sessions list       # sessions load correctly
hermes  # new session works
```

Pass: session health check shows healthy; new sessions work.

Fail: session health check flags runaway — start fresh session and split work.

## Verification

After applying the fix:

```bash
hermes guide               # session health check passes
hermes sessions list       # sessions load correctly
hermes  # new session works
```

Pass: session health check shows healthy; new sessions work.

Fail: session health check flags runaway — start fresh session and split work.


## 4. Related

- `diagnosing-host-pressure` — OOM and host load
- `diagnosing-storage` — disk and database issues
- `hermes-disk-housekeeping` — cleanup procedures

*Facts re-verified 2026-10-31 against upstream source at commit `cedf4a3d78675283fa93e4e6ea2d6212bf414667`: `hermes_cli/checks.py` (check_session_health), `hermes_constants.py` (get_hermes_home). Re-verify before reuse.*