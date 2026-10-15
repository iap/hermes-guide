---
name: start
description: "Route vague Hermes problem reports ('something is wrong', slow, crashed, won't start, not responding) to the read-only `hermes guide` baseline and the diagnosing-* playbooks. Registered by the plugin itself, so it works before the skills tap is installed."
version: 1.0.0
metadata:
  hermes:
    tags: [hermes, diagnostics, triage, routing]
    related_skills: [diagnosing-triage, hermes-configuration-guide, installing-hermes]
---

# Hermes Guide — Start

Entry point for a misbehaving Hermes. The plugin registers this skill itself
(`hermes-guide:start`) — it is not a tap skill, so it stays listed in model
sessions whenever the plugin is enabled, even when no other hermes-guide skill
is installed.

## When this applies

The user reports a Hermes problem without naming the subsystem:

- "Something is wrong with Hermes." / "It's broken."
- "It's slow." / "It crashed." / "It stopped working."
- "The bot isn't responding." / "It won't start."
- "I can't install anything."

When the subsystem is already named (MCP, hooks, cron, voice, ...), run
`hermes guide <scope>` directly and load the matching `diagnosing-*` playbook
when it is installed.

## Step 1 — baseline before guessing

Run the read-only health check and read its lines:

- Terminal: `hermes guide` (all scopes) or `hermes guide <scope>`.
  Exit codes: `0` healthy, `1` broken or unknown, `2` bad scope.
- In a session: `/hermes-doctor`, or `/hermes-doctor <scope>`.

Valid scopes: `config`, `mcp`, `skills`, `commands`, `hooks`, `plugins`,
`memories`.

Status marks in the output: `+` healthy, `~` informational, `x` broken,
`?` unknown. `?` means unmeasured — treat it as broken until the scope runs
clean.

## Step 2 — route the findings

The tap's `diagnosing-triage` playbook carries the full line-to-skill mapping.
The short version:

- `x config` → load `hermes-configuration-guide` Step 0 (resolve the home and
  config path), then re-run the scope.
- `x <any other scope>` → load the matching `diagnosing-*` playbook when it is
  installed (scope `memories` maps to `diagnosing-memory`); otherwise act on
  the finding text directly — it names the file and the field.
- A flagged `?` (unknown) line → `hermes-configuration-guide` Step 0 first;
  when the venv or interpreter is suspect, `diagnosing-path`.

When the tap is not installed and the user needs the deeper playbooks, the
install is:

```bash
hermes skills tap add iap/hermes-guide
hermes skills install "iap/hermes-guide/skills/diagnosing-mcp"
```

The identifier must include the `skills/` prefix; the README carries the
install-all loop for the full set.

## Rules

- Triage is read-only: do not edit configuration or execute hooks while
  diagnosing.
- Mutations need explicit user consent, one change at a time, then re-run the
  check that flagged it.
- One-shot (`hermes -z`) sessions do not auto-discover skills — name this skill
  or the target playbook explicitly.

*Facts verified 2026-10-16 against this repo's `checks.py` scope registry and the upstream baseline `f97608f178d1ffeca59860195ab7da295f7c8e5f`; routing targets verified present in `skills/`. Re-verify before reuse.*
