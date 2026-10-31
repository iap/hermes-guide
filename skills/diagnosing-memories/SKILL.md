---
name: diagnosing-memories
description: Diagnose Hermes memory store issues — MEMORY.md/USER.md over-limit, duplicates, mis-targeted entries, and undated dynamic stores.
version: 1.0.0
metadata:
  hermes:
    tags: [hermes, memory, troubleshooting]
    related_skills: [hermes-configuration-guide, diagnosing-memory]
---

# Diagnosing Memory Stores

Goal: reduce any memory store problem to one concrete fix — a trim, a dedup, or a re-target.

> **Disambiguation**: if the agent "forgot" something or an external memory provider is unavailable, see `diagnosing-memory`. This skill covers the built-in store files (`MEMORY.md`, `USER.md`) and their content hygiene.

## 1. How to inspect

- `hermes guide` — runs `check_memory_hygiene` (store audit)
- `hermes memory status` — provider/store health
- `cat ~/.hermes/memories/MEMORY.md` — agent notes store
- `cat ~/.hermes/memories/USER.md` — user profile store

## 2. Common failures

### Store over limit

**Symptom:** `hermes guide` reports memory store as broken (over char limit).

**Cause:** Too many entries; store exceeds configured char limit (~2,200).

**Fix:**
- Trim low-value entries
- Consolidate related entries into one
- Remove stale/duplicate information
- Use `memory` tool to patch/remove entries

### Exact duplicates

**Symptom:** `hermes guide` reports duplicate entries.

**Cause:** Same fact added multiple times.

**Fix:**
- Remove duplicate entries via `memory` tool (remove action)
- Keep the most complete version

### Near-duplicates

**Symptom:** `hermes guide` reports near-duplicate entries.

**Cause:** Similar but not identical entries (e.g. "User prefers X" and "User likes X").

**Fix:**
- Consolidate into one entry
- Remove the redundant one

### User preference in wrong store

**Symptom:** `hermes guide` reports user-preference entries in MEMORY.md (agent notes).

**Cause:** Facts about the user were saved to the agent-notes store instead of USER.md.

**Fix:**
- Move the entry to USER.md
- Remove from MEMORY.md
- Re-add via `memory` tool with correct target

### Undated dynamic store

**Symptom:** `hermes guide` reports undated dynamic store.

**Cause:** Memory entries lack timestamps; dynamic store has no date anchor.

**Fix:**
- Add date prefix to dynamic entries
- Or convert to dated entries

### Missing store file

**Symptom:** `hermes guide` reports missing store.

**Cause:** Hermes hasn't created the store yet (first run).

**Fix:**
```bash
mkdir -p ~/.hermes/memories
# Hermes creates stores on first memory write
hermes  # start a session
```

## 3. Verification

```bash
hermes guide               # memory hygiene check healthy
hermes memory status       # provider/store health ok
cat ~/.hermes/memories/MEMORY.md  # entries within limit
```

Pass: memory hygiene check shows healthy; stores within limits.

Fail: memory hygiene check shows broken — address the specific finding.

## 4. Related

- `diagnosing-memory` — memory provider and "forgot" issues
- `hermes-disk-housekeeping` — storage cleanup
- `hermes-configuration-guide` — memory configuration

*Facts verified 2026-11-01 against upstream source at commit `cedf4a3d78675283fa93e4e6ea2d6212bf414667`: `hermes_cli/checks.py` (check_memory_hygiene), `hermes_constants.py` (BUILTIN_MEMORY_STORES, MEMORY_ENTRY_DELIMITER). Re-verify before reuse.*