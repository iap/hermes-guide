---
name: diagnosing-memory
description: "Diagnose Hermes memory problems — the agent forgot something, an external memory provider configured but silently unavailable, missing provider plugins or API keys, and built-in MEMORY.md/USER.md errors from config or char limits."
version: 1.1.2
metadata:
  hermes:
    tags: [hermes, memory, providers, troubleshooting, diagnosing]
    related_skills: [hermes-configuration-guide, diagnosing-plugins, diagnosing-path]
---

# Diagnosing Memory

Goal: reduce any "it forgot what I told it" / "my memories are gone" / memory-provider failure to one concrete fix — a config field, an env var, a plugin install, or a session restart.

> [!WARNING]
> **Hermes memory has two independent layers, and the external one fails silently.** Built-in memory (`MEMORY.md` / `USER.md`) is always active. At most one external provider can be active; if it is unavailable, **external memory is disabled for that session and built-in memory answers instead** — the agent does not announce this. "My mem0 memories are gone" usually means "mem0 was unavailable; built-in answered."

## 1. How memory resolves

| Layer | Files / source | Controlled by |
|---|---|---|
| **Built-in** (always available) | `$HERMES_HOME/memories/MEMORY.md` (agent notes) + `USER.md` (user profile) | `memory.memory_enabled`, `memory.user_profile_enabled` in `config.yaml` |
| **External provider** (opt-in, one at a time) | plugin at `$HERMES_HOME/plugins/memory/<name>/` + pip deps in the active venv + secrets in `$HERMES_HOME/.env` | `memory.provider:` in `config.yaml` (empty string = built-in only) |

A provider is *available* only when all four hold: plugin installed, its pip dependencies importable in the active venv, its env vars set, and its `is_available()` check passing. Any one missing → silent fallback to built-in (see the warning above).

> [!IMPORTANT]
> **Built-in memory is a frozen snapshot.** `MEMORY.md`/`USER.md` are injected into the system prompt once at session start. Mid-session saves hit disk immediately but do **not** update the current session's prompt — this is by design (it keeps the prompt cache stable). "It forgot what I just told it" is usually this, not a bug: the write landed and appears next session. Verify with a file read before diagnosing further.

## 2. How to inspect

Probe in this order — the first two are built-in helpers and answer most cases:

1. **`hermes memory status`** — the authoritative check. Real example (a machine with `honcho` selected but no API key):

   ```
   Memory status
   ────────────────────────────────────────
     Built-in (MEMORY.md / USER.md):
       Memory injection:   enabled ✓
       User profile:       enabled ✓
       Memory tool:        enabled ✓
     Provider:  honcho
     Plugin:    installed ✓
     Status:    not available ✗
     Missing:
       ✗ HONCHO_API_KEY  → https://app.honcho.dev
   ```

   A trailing `Note:` line (quoted verbatim in the tool's output) explains that systemd/gateway services do not inherit the profile `.env` secrets file — set any listed variables in the service environment itself (see the gateway/systemd row in §3).

   Read it line by line: the three built-in lines confirm the stores and the `memory` tool are on; `Provider:` shows what `memory.provider` is set to; `Plugin:` / `Status:` / `Missing:` are the three failure points in order (plugin file → pip deps → env vars). The installed-plugins list at the bottom is the ground truth for provider names — the `hermes memory --help` string is not kept in sync with it.

2. **`hermes doctor`** — its "Memory Provider" section probes the active provider deeper (config file, API key, live connect, `ImportError` on the provider package). Run it after `memory status` points at a layer.

3. **Config + files** — read the `memory:` block of `$HERMES_HOME/config.yaml` (or `hermes config show`), and `ls "$HERMES_HOME/memories/"`. On native Windows `$HERMES_HOME` is `%LOCALAPPDATA%\hermes` — confirm with `hermes config path`, never assume.

4. **Session log** — a provider selected but unavailable logs a one-shot warning at agent start ("Memory provider … reports unavailable — external memory is disabled for this session"): `hermes logs --follow` while starting a session.

5. **`hermes guide memories`** (or `/hermes-doctor memories` in-session) — this plugin's read-only hygiene audit of the built-in stores: over-limit files, exact/near-duplicate entries, user-profile facts mis-targeted into `MEMORY.md`, and undated dynamic entries. It reports content-level findings that `hermes memory status` does not look at.

## 3. Pitfalls (symptom → cause → fix)

| Symptom | Cause | Fix |
|---|---|---|
| Agent forgot something said mid-session | Frozen snapshot by design (see §1) | None needed — restart the session / new session picks it up. Verify the write landed in `$HERMES_HOME/memories/MEMORY.md` first |
| External provider "not available ✗", missing env var listed | Secret absent from `$HERMES_HOME/.env` | Re-run `hermes memory setup <provider>` or add the var to `.env`; keep secrets out of `config.yaml` |
| Provider works in terminal, not in gateway/systemd | Services do not inherit `$HERMES_HOME/.env` | Set the provider's env vars in the service environment itself |
| `hermes memory status`: "Plugin: NOT installed ✗" | `memory.provider` names a provider with no plugin under `$HERMES_HOME/plugins/memory/` | Install the provider plugin (hub: `hermes plugins install …`), or `hermes memory off` to go built-in-only |
| `hermes doctor`: "honcho-ai not installed" / "mem0ai not installed" | venv rebuild/sync stripped provider pip deps | Re-run `hermes memory setup <provider>` (force-reinstalls its deps) or `hermes update` |
| Hindsight local mode fails to import | local mode needs `hindsight-all`, not `hindsight-client` | `hermes memory setup hindsight` after setting `mode: local` in `hindsight/config.json` |
| Memory tool missing from the tool schema | Both stores disabled: `memory.memory_enabled: false` **and** `user_profile_enabled: false` | Re-enable one in `config.yaml`; both off removes the tool entirely |
| Writes rejected: "…would exceed the limit. Consolidate now…" | Char limits are hard caps (defaults 2200 / 1375 chars) — there is no auto-compaction | Have the agent consolidate/dedupe in the same turn, or raise `memory.memory_char_limit` |
| Writes silently staged, never saved | `memory.write_approval: true` stages writes for review | Approve via `/memory approve` in-session, or set `write_approval: false` |
| Hygiene check flags "no entry has a [YYYY-MM-DD] date prefix" | Entries carry no dates, so staleness is uncheckable — the `memories` scope of `hermes guide` reports undated entries as notes | Date new entries `[YYYY-MM-DD] …` where staleness matters; undated entries are a note, not an error |
| Provider config edits ignored | Active-provider name mismatch, or edits made to the wrong profile's home | `hermes config path` to confirm the active home/profile; one provider at a time — `memory.provider` is a single string |
| Memory "disappeared" after profile work | `HERMES_HOME` unset while a non-default profile is active → files written to the wrong home | Set `HERMES_HOME` explicitly for profile work; watch for the `[HERMES_HOME fallback]` stderr warning |

Two name traps that are **not** this surface:

- `context.memory_trim` is **process-heap release** for long-lived gateway processes (Linux/glibc only) — nothing to do with `MEMORY.md`.
- `hermes memory-graph` is an alias of `hermes journey` (learned-skills/memory timeline viewer), not a memory provider.

## 4. The `memory:` config block

| Key | Default | Meaning |
|---|---|---|
| `provider` | `""` | Active external provider; empty = built-in only; `hermes memory off` sets this |
| `memory_enabled` | `true` | Agent-notes store (`MEMORY.md`) |
| `user_profile_enabled` | `true` | User-profile store (`USER.md`) |
| `memory_char_limit` | `2200` | Hard cap in characters of the decoded file (`len(text)`) — not bytes, not tokens |
| `user_char_limit` | `1375` | Hard cap in characters of the decoded file (`len(text)`) — not bytes, not tokens |
| `nudge_interval` | `10` | Memory-save nudge every N user turns; `0` = off |
| `write_approval` | `false` | Stage writes for `/memory approve` instead of saving |

Hermes configuration is **YAML** — edit `config.yaml`, never JSON syntax.

## 5. Apply and verify

There is no `/reload-memory`: built-in memory is snapshotted at session start, so **restart the session** after any config/`.env`/plugin fix. Then confirm with `hermes memory status` (all lines ✓, or provider lines as intended) and, for built-in, ask the agent to remember something and check the file changed on disk.

> [!CAUTION]
> `hermes memory reset` **erases** `$HERMES_HOME/memories/MEMORY.md` and/or `USER.md` irreversibly (`--target all|memory|user`, confirmation prompt, `--yes` skips it). It resets built-in memory only — it does not touch external providers.

## 6. The session database (`state.db`) — size and compaction

Built-in memory and the external provider are the *content* stores. The session
*log* lives separately in `$HERMES_HOME/state.db` (SQLite), and its growth has
nothing to do with either store. A 900+ MB `state.db` is not a memory problem
and trimming `MEMORY.md` will not shrink it.

### What is in it

| Table | Meaning |
|---|---|
| `sessions` | one row per conversation (953 in a typical install) |
| `messages` | every user/assistant/tool row (~250K) |
| `messages_fts` | full-text index over `messages` (kept in sync) |
| `session_model_usage` | token accounting per session |
| `system_prompts` | cached system prompt variants |
| `compaction_events` | **records of every compaction run** |

### The compaction signal

`compaction_events` is the canary. If it is **0**, compaction has never fired —
the database has been growing with no trim ever applied. This is the most common
cause of a bloated `state.db`.

**Diagnose it directly:**

```bash
sqlite3 "$HERMES_HOME/state.db" "SELECT COUNT(*) FROM compaction_events;"
```

Correlate with the other tables:

```bash
sqlite3 "$HERMES_HOME/state.db" \
  "SELECT 'sessions', COUNT(*) FROM sessions
   UNION ALL SELECT 'messages', COUNT(*) FROM messages
   UNION ALL SELECT 'open_sessions', COUNT(*) FROM sessions WHERE ended_at IS NULL
   UNION ALL SELECT 'sessions_older_than_90d',
     COUNT(*) FROM sessions WHERE started_at < $(date +%s) - 7776000;"
```

A healthy profile: `compaction_events > 0`, few open sessions, old sessions
summarized. A sick one: `compaction_events = 0`, 100+ open sessions, 18+ sessions
older than 90 days, and a top session carrying 10K+ raw message rows.

### Integrity checks (run before anything else)

Corruption and FTS drift are separate from growth. Verify both:

```bash
# FTS in sync with messages — 0 means clean
sqlite3 "$HERMES_HOME/state.db" \
  "SELECT COUNT(*) FROM messages m LEFT JOIN messages_fts f ON m.rowid = f.rowid
   WHERE f.rowid IS NULL;"
# Orphan messages pointing at deleted sessions — 0 means clean
sqlite3 "$HERMES_HOME/state.db" \
  "SELECT COUNT(*) FROM messages m LEFT JOIN sessions s ON m.session_id = s.id
   WHERE s.id IS NULL;"
```

If either returns non-zero, the database is damaged and should be restored from
`backups/` before running compaction — compaction assumes a consistent store.

### The fix

```bash
hermes compact
```

This is the built-in compaction trigger. It creates the first
`compaction_events` row, summarizes old sessions, and drops the raw message rows
they held. Run it on a session you are not currently in, since it operates on the
live database.

If `compaction_events` stays 0 after running it, the scheduler may simply not
have ticked. Check `hermes cron list` for a compaction job; if none is scheduled,
`hermes compact` runs it manually.

> [!CAUTION]
> Compaction is lossy by design — it replaces raw message rows with a summary.
> `state.db` has a backup under `$HERMES_HOME/backups/`. Confirm one exists and is
> recent before running compaction on a database you have not trimmed before.
