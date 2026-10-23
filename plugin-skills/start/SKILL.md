---
name: start
description: "Route vague Hermes problem reports ('something is wrong', slow, crashed, won't start, not responding) to the `hermes guide` baseline and the diagnosing-* playbooks. Registered by the plugin itself, so it works before the skills tap is installed."
version: 1.1.0
metadata:
  hermes:
    tags: [hermes, diagnostics, triage, routing]
    related_skills: [diagnosing-triage, diagnosing-runtime, hermes-configuration-guide, installing-hermes]
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
the nine scopes below; cron and voice, for example, are playbook-only.

## Step 1 — baseline before guessing

Run the health check and read its lines:

- Terminal: `hermes guide` (all scopes) or `hermes guide <scope>`.
  Exit codes: `0` healthy, `1` broken or unknown, `2` bad scope. Add `--fast`
  on a degraded host where every launch takes minutes. The command is one CLI
  process either way; what `--fast` removes is the per-check `hermes`
  subprocess work (the config-path fallback, `hermes hooks doctor`), which on
  such a host is where the minutes go. It does not help when the CLI itself
  will not start — that launch still happens, so fall back to reading state
  directly and routing by subsystem name (Step 2).
- Prefer the machine-readable document when the shell is available:
  `hermes guide --json` (or `hermes guide <scope> --json`) prints one JSON
  document whose `checks` object is keyed by scope and carries the same
  envelopes the text report prints, each `broken`/`unknown` envelope with a
  stable `id`, a plain-language `impact`, and the sanctioned `fix` (id
  catalog: `docs/findings.md` in the repo). Fall back to the text output —
  and say so — when `--json` errors: installs whose `hermes guide --help`
  does not list `--json` reject it with an argparse usage error
  (`unrecognized arguments: --json`, exit `2`). Do not reword that error or
  retry the flag; the text report carries the same findings.
- In a session: `/hermes-doctor`, or `/hermes-doctor <scope>`.

Valid scopes: `config`, `mcp`, `skills`, `commands`, `hooks`, `plugins`,
`memories`, `sessions`, `update`.

The check writes nothing. Both exceptions are disclosed: the `hooks` scope runs
`hermes hooks doctor`, which executes each approved shell hook once with a
synthetic payload — that is how it verifies a hook actually runs; the `update`
scope reads the update-lock record and opens that file writable (read-only
fallback for a root-owned lock on POSIX) to take a non-blocking lock it
releases immediately, which is how it separates a live owner from stale residue
(no content is written and the lock file is never deleted). Every other scope
reads state only. With `--fast`, the `hooks` scope swaps to an in-process check
instead — nothing executes.

Status marks in the output: `+` healthy, `~` informational, `x` broken,
`?` unknown. `?` means unmeasured — treat it as broken until the scope runs
clean.

## Step 2 — route the findings

Read the document in one order: `broken` findings first, then `unknown`
(`?` means unmeasured — treat it as broken until the scope runs clean), then
informational (`~` lines, which are actionable hints, not noise). For each
`broken`/`unknown` finding carry the envelope verbatim: the stable `id`, the
reason with any upstream error text quoted exactly, and the `impact` copy —
what the user cannot do until it is fixed. Only `broken`/`unknown` envelopes
carry an `id`, `impact`, and `fix`; informational lines carry the reason and
detail text and route straight into the mapping below — do not invent
metadata for them.

Then offer at most three options per finding and let the user pick:

1. A **session-scoped workaround** — an existing `hermes` command or manual
   substitute that unblocks the current turn without persisting anything.
2. The **sanctioned fix** — the exact command from the envelope's `fix` (or
   the loaded playbook's resolution order), with the persistent change named
   before anything runs.
3. **Proceed without the capability** — say what stays unavailable.

Anything persistent needs explicit user confirmation in the same turn; never
run a persistent fix unprompted. After a confirmed change, re-run the check
that flagged it.

The tap's `diagnosing-triage` playbook carries the full symptom-to-finding-id
to playbook mapping. The short version:

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

*Facts (re-)verified 2026-10-23 against this repo's `checks.py` `_CHECKS` (nine scopes) and `check_update_lock` (writable non-blocking probe, POSIX read-only fallback for a root-owned lock, released immediately, no content written, never deleted); `__init__.py` (`--fast` flag, exit codes); in-repo routing targets verified in `skills/`. Scope list corrected from seven to nine 2026-10-17; --fast clause corrected 2026-10-17: it suppresses per-check hermes subprocesses, not the single CLI launch, and points at Step 2 rather than a no-baseline route that does not exist in this file — `sessions` and `update` shipped earlier but were missing here; update-scope lock probe disclosed 2026-10-22 (the earlier "every other scope reads state only" claim omitted it). `--json` preference, ordered reporting, and the three-option rule added 2026-10-23: `--json` contract taken from this repo's `hermes guide --json` tests (`tools/test_json_output.py`, #336); the fallback shape observed live on the host (Hermes Agent v0.22.2+1915.gdd519c7.dirty, hermes-guide 0.8.7) where `hermes guide config --json` exits `2` with `unrecognized arguments: --json`; the fallback wording keys off `hermes guide --help` listing `--json` rather than a hard version; commands cited (`hermes config path`, `hermes doctor --fix`/`--live`, `hermes setup`, `hermes skills install`/`tap`, `hermes plugins install`/`update`/`list`, `hermes hooks doctor`, `hermes gateway status`) re-verified live on v0.22.2. Review-round corrections 2026-10-23 (re-checked against the repo source, no new live facts): the JSON document's `checks` is an object keyed by scope (from `_build_json_payload` in this repo's `__init__.py`), not an array; `id`/`impact`/`fix` apply to `broken`/`unknown` envelopes only — informational lines carry reason and detail and route without invented metadata. Re-verify before reuse.*
