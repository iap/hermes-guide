# Session database (`state.db`) — size and compaction

Built-in memory and the external provider are the *content* stores. The session
*log* lives separately in `$HERMES_HOME/state.db` (SQLite — resolve the home
first with `hermes config path`, never assume `~/.hermes`), and its growth has
nothing to do with either store. A 900+ MB `state.db` is not a memory problem
and trimming `MEMORY.md` will not shrink it.

## What is in it

| Table | Meaning |
|---|---|
| `sessions` | one row per conversation (953 in a typical install) |
| `messages` | every user/assistant/tool row (~250K) |
| `messages_fts` | full-text index over `messages` (kept in sync) |
| `session_model_usage` | token accounting per session |
| `system_prompts` | cached system prompt variants |
| `compaction_events` | **records of every compaction run** |

## The compaction signal

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

## Integrity checks (run before anything else)

Corruption and FTS drift are separate from growth. Verify both:

```bash
# FTS in sync with messages — 0 means clean
sqlite3 "$HERMES_HOME/state.db" \
  "SELECT COUNT(*) FROM messages m LEFT JOIN messages_fts f ON m.rowid = f.rowid
   WHERE f.rowid IS NULL;"
# Stale FTS rows whose source messages were deleted — 0 means clean
sqlite3 "$HERMES_HOME/state.db" \
  "SELECT COUNT(*) FROM messages_fts f LEFT JOIN messages m ON f.rowid = m.rowid
   WHERE m.rowid IS NULL;"
# Orphan messages pointing at deleted sessions — 0 means clean
sqlite3 "$HERMES_HOME/state.db" \
  "SELECT COUNT(*) FROM messages m LEFT JOIN sessions s ON m.session_id = s.id
   WHERE s.id IS NULL;"
```

If any returns non-zero, the database is damaged: back it up first (see below),
then consider `hermes sessions repair` before anything destructive — pruning and
optimizing assume a consistent store.

## The fix

There is no `hermes compact` command. Reclaim space with the real
session-store commands, in this order:

```bash
hermes backup -q -l pre-prune          # explicit snapshot; verify the zip exists
hermes sessions prune --help           # delete old sessions (filterable) — read flags first
hermes sessions archive --help         # soft-hide instead of deleting, if preferred
hermes sessions optimize               # VACUUM + merge FTS5 segments (no data change)
```

`hermes sessions optimize-storage` migrates the search index to the compact v23 layout and
reclaims disk on large DBs; `hermes sessions repair` fixes a malformed schema so hidden
sessions reappear. Run these on a session you are not currently in, since they
operate on the live database.

## Disk hygiene beyond state.db

`state.db` is only one consumer. Ephemeral files (test/temp/cron-output tracked by
the `disk-cleanup` plugin), `request_dump_*.json`, cache scratch, and old logs
are cleaned separately and do not shrink `state.db`:

```bash
# In a session: /disk-cleanup status | dry-run | quick | deep
# Full procedure: load the `hermes-disk-housekeeping` skill
```

Resolve `$HERMES_HOME` first (`hermes config path`); never assume `~/.hermes`.
The `storage` scope of `hermes guide` reports only `state.db` size.

> [!CAUTION]
> Pruning is lossy by design — it deletes raw message rows. Compaction creates
> no backup itself, and nothing guarantees a recent archive already exists
> (`backups/` holds conditional full archives, `state-snapshots/` holds quick
> snapshots). Create one explicitly with `hermes backup -q -l pre-prune` and
> confirm the zip before pruning a database you have not trimmed before.
