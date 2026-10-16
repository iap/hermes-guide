---
name: start
description: "Route vague Hermes problem reports ('something is wrong', slow, crashed, won't start, not responding) to the `hermes guide` baseline and the diagnosing-* playbooks. Registered by the plugin itself, so it works before the skills tap is installed."
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

If Hermes itself will not launch — it crashes on start, or no command runs —
the baseline cannot execute, and the tap may not be installed either.
Sequence it by reachability:

1. Load `installing-hermes` if it is already installed — the install and
   repair routes are the remedy for a broken launch.
2. If the tap is not installed and a command runs at all (`hermes --help`,
   `hermes plugins info`, anything), install it and load `installing-hermes`.
3. If nothing runs, answer from this skill's Rules and the README install
   section (`hermes plugins install iap/hermes-guide --enable`) — name the
   install route instead of deferring to an unreachable playbook. Return to
   `hermes guide` once a command runs.

When the subsystem is already named (MCP, hooks, cron, voice, ...), go
straight to its playbook when installed — `hermes guide <scope>` covers only
the seven scopes below; cron and voice, for example, are playbook-only.

## Step 1 — baseline before guessing

Run the health check and read its lines:

- Terminal: `hermes guide` (all scopes) or `hermes guide <scope>`.
  Exit codes: `0` healthy, `1` broken or unknown, `2` bad scope.
- In a session: `/hermes-doctor`, or `/hermes-doctor <scope>`.

Valid scopes: `config`, `mcp`, `skills`, `commands`, `hooks`, `plugins`,
`memories`.

The check writes nothing, with one disclosed exception: the `hooks` scope runs
`hermes hooks doctor`, which executes each approved shell hook once with a
synthetic payload — that is how it verifies a hook actually runs. Every other
scope reads state only.

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
- `~` lines are actionable hints, not noise: `~ commands` →
  `diagnosing-commands`; `~ memories` → `diagnosing-memory`; otherwise treat
  them like a softer `x`.
- A flagged `?` (unknown) line → `hermes-configuration-guide` Step 0 first;
  when the venv or interpreter is suspect, `diagnosing-path`.
- Failed installs: `hermes skills install` / `hermes plugins install` ending
  in not-found, 401, or 403 → `diagnosing-auth` first (a dead token makes
  every hub adapter read "not found"); a Hermes install or upgrade itself
  failing → `installing-hermes`. While the install path is failing, do not
  loop the tap install below — fix the failure first.
- Every scope healthy but the symptom persists → keep going: the baseline
  cannot see delivery, host load, or platform problems. Route by the symptom
  itself — for example a bot that is not responding → `diagnosing-gateway`
  first; when the gateway checks out healthy, continue to `diagnosing-bot-mode`
  (profiles, conflicts, DMs). Slowness needs one clarifying question first:
  general performance or several surfaces → `diagnosing-host-pressure`; a
  single feature (one model call, one skill, one provider) → that feature's
  playbook (`diagnosing-providers` for model calls, `diagnosing-skills` for
  skills, ...). A non-responding bot stays on the gateway path above — not
  slowness.

When the tap is not installed, the install path is healthy, and the user
wants the deeper playbooks:

```bash
hermes skills tap add iap/hermes-guide
hermes skills install "iap/hermes-guide/skills/<playbook>"
```

Substitute the playbook the routing selected (`diagnosing-mcp` for MCP
findings, `diagnosing-gateway` for messaging, ...). The identifier must
include the `skills/` prefix; the README carries the install-all loop for the
full set.

## Rules

- Triage writes nothing. The only execution allowed is the `hooks` scope's own
  synthetic verification run (Step 1) — do not execute hooks beyond it, and do
  not edit configuration while diagnosing.
- Mutations need explicit user consent, one change at a time, then re-run the
  check that flagged it.
- One-shot (`hermes -z`) sessions do not auto-discover skills — name this skill
  or the target playbook explicitly.

*Facts (re-)verified 2026-10-15 against upstream source at commit `f97608f178d1ffeca59860195ab7da295f7c8e5f` (`hermes guide` scopes and exit codes); in-repo routing targets verified in `checks.py` and `skills/`. Re-verify before reuse.*
