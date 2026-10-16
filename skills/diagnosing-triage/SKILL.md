---
name: diagnosing-triage
description: "Route 'something is wrong / slow / crashed / stopped working / not responding / won't launch / not firing' to the right diagnosing-* playbook — triage layer mapping symptoms to skills."
version: 1.0.12
metadata:
  hermes:
    tags: [hermes, triage, routing, diagnostics]
    related_skills: [hermes-configuration-guide, diagnosing-runtime, diagnosing-cli-tui, diagnosing-path, diagnosing-host-pressure, diagnosing-commands, diagnosing-mcp, diagnosing-skills, diagnosing-plugins, diagnosing-hooks, diagnosing-auth, diagnosing-memory, diagnosing-desktop, diagnosing-providers, diagnosing-bot-mode, diagnosing-browser, diagnosing-cron, diagnosing-gateway, diagnosing-voice, installing-hermes]
---

# Diagnosing Triage

Route vague user descriptions to the correct diagnostic skill. This is the **triage layer** — when the user says "something is wrong" without naming a subsystem, use the flowchart and mapping table below to pick the right `diagnosing-*` playbook.

> **Disambiguation**: this skill does **not** diagnose anything itself. It only routes. Once you have identified the target skill, load that skill and follow its playbook. If the description is too vague to route, ask the clarifying questions in §3 before guessing.

## 0. When to use this skill

Load this skill when the user's description is **non-specific** — they know something is broken but haven't (or can't) name the subsystem. Typical triggers:

- "Something is wrong with Hermes."
- "It's slow." / "It keeps timing out."
- "It crashed." / "It stopped working."
- "The bot isn't responding." (without saying which platform or layer)
- "Skills aren't working." (without saying whether it's discovery, triggering, or a `/command`)
- "I can't install anything." (without saying whether it's skills, plugins, or the whole app)

Do **not** load this skill when the user has already named a specific subsystem ("MCP won't connect", "a hook isn't firing", "the TUI looks garbled") — go directly to the relevant `diagnosing-*` skill.

> **Headless / one-shot mode.** Skill auto-discovery does not fire in `hermes -z` one-shot runs: name the target skill explicitly (`hermes -z "Use the diagnosing-path skill: …"`). Slash commands (`/hermes-doctor`) and `/reload-*` steps work only in a live session — headless, use `hermes guide <scope>` (exits `0` healthy, `1` broken/unknown, `2` bad scope) for every check and verify step below.

## 0b. Baseline first: run the health check before routing

Before walking the flowchart, capture the machine-readable baseline — it routes whole branches by itself and exposes findings no symptom description mentions:

- Headless / one-shot: `hermes guide` (all scopes) or `hermes guide <scope>`.
- In-session: `/hermes-doctor` or `/hermes-doctor <scope>`.

Route its `~`/`x`/`?` lines first:

| Baseline line | Load |
|---|---|
| `~ commands` (e.g. a skill slug shadowing a builtin) | diagnosing-commands |
| `~ memories` (store near/over limit, undated entries) | diagnosing-memory |
| `x config` | hermes-configuration-guide Step 0, then re-run the scope |
| `x mcp` | diagnosing-mcp |
| `x skills` | diagnosing-skills |
| `x commands` | diagnosing-commands |
| `x hooks` | diagnosing-hooks |
| `x plugins` | diagnosing-plugins |
| `x memories` | diagnosing-memory |
| `x sessions` (runaway loop signature) | stay here — §1b runaway branch below |
| `x update` (stale update lock) | diagnosing-cli-tui §1 stale-lock note |
| `?` (unknown — home unresolvable, doctor output unrecognized) | hermes-configuration-guide Step 0 (resolve home/config), then re-run the scope; unknown means unmeasured, never healthy; `2 bad scope` for a documented scope means the installed hermes-guide predates the docs — run `hermes plugins update hermes-guide`, then re-run |

Exception — no baseline possible: when every `hermes` invocation hangs (e.g. on `an update is still running`), the baseline cannot run. Load the diagnosing-cli-tui stale-lock note directly and follow its manual steps; run `hermes guide update` after the CLI recovers as confirmation, not as the entry point. Minutes-long launches that keep retrying update completion are a different shape — route to diagnosing-path (retry-loop note), not here.

Then continue with symptom routing below for whatever the baseline did not explain.

Ownership: symptom-order routing lives in this skill; surface-order rows live in the config map; pairwise precedence is canonical in the config-map Disambiguation list — edit each where it lives.

## 1. Triage flowchart

Start at the top. Follow the first branch that matches the user's description.

```
Is `config.yaml` missing, unparsable, or did a guide scope return unknown?
  └─ YES → hermes-configuration-guide Step 0 (resolve home/config), then
           diagnosing-path if the venv/interpreter is suspect; re-run the scope
  └─ NO ↓

Is the agent LOOPING — repeating the same answer or tool calls turn after
  turn, interrupts don't change course (`hermes guide sessions` shows
  `x sessions` with a runaway signature)?
  └─ YES → do NOT keep interrupting the same session: start a fresh session;
           inspect the default model tier in config.yaml (`model:` — a
           free-tier default with a large context is a known loop risk);
           split generate-then-verify into separate turns. Details in §1b.
  └─ NO ↓

Is the CLI itself broken — `hermes guide` prints nothing, commands hang,
  or `hermes --version` is empty?
  └─ YES → diagnosing-runtime
  └─ NO ↓

Is a `hermes skills` / `hermes plugins install` failing with not-found/401/403?
  └─ YES → diagnosing-auth first (a dead token degrades every hub adapter to
           "not found"), then installing-hermes only if Hermes itself is broken
  └─ NO ↓

Is the problem about INSTALLING or UPGRADING Hermes itself?
  └─ YES → installing-hermes
  └─ NO ↓

Is the problem about HOST RESOURCES — high load, OOM, plugin discards,
  resource exhaustion, multiple surfaces failing at once?
  └─ YES → diagnosing-host-pressure
  └─ NO ↓

Is the problem about the DESKTOP APP (Electron) not launching,
  showing a blank window, or npm/build errors?
  └─ YES → diagnosing-desktop
  └─ NO ↓

Is the problem about the CLI/TUI — rendering, themes, busy indicators,
  mouse modes, encoding, garbled output, launch/resume?
  └─ YES on native Windows → diagnosing-cli-tui
  └─ YES on POSIX/WSL → `hermes doctor` + the `display:` block of `config.yaml`
     (no dedicated skill covers POSIX CLI/TUI — do NOT load diagnosing-cli-tui,
     it documents the Windows console stack only)
  └─ NO ↓

Is the problem about PATHS, VENVS, or the wrong Python interpreter?
  └─ YES → diagnosing-path
  └─ NO ↓

Is the problem about a MESSAGING PLATFORM — bot not responding,
  platform allowlist, token validation, gateway connectivity?
  └─ YES → diagnosing-gateway first (`hermes gateway status`); only if the
           gateway is healthy and the fault is bot profiles/conflicts/DMs
           → diagnosing-bot-mode
  └─ NO ↓

Is the problem about BOT PROFILES specifically — bots not appearing,
  profile conflicts, bot-to-bot messaging (gateway itself already healthy)?
  └─ YES → diagnosing-bot-mode
  └─ NO ↓

Is the problem about BROWSER AUTOMATION — CDP connection failures,
  Chrome version, Playwright, agent-browser?
  └─ YES → diagnosing-browser
  └─ NO ↓

Is the problem about SCHEDULED JOBS — cron not firing, scheduler dead,
  wedged fire-claim, timezone issues?
  └─ YES → diagnosing-cron
  └─ NO ↓

Is the problem about VOICE — STT/TTS failures, audio device, latency, ffmpeg?
  └─ YES → diagnosing-voice
  └─ NO ↓

Is the problem about AUTH — "Could not fetch from any source", GitHub 401,
  rate-limit 403, hub install fails?
  └─ YES → diagnosing-auth
  └─ NO ↓

Is the problem about MEMORY — agent forgot, memory provider down,
  MEMORY.md/USER.md errors?
  └─ YES → diagnosing-memory
  └─ NO ↓

Is the problem about PROVIDERS — provider picker flooded, discover_models,
  auth failures, model catalog bloat?
  └─ YES → diagnosing-providers
  └─ NO ↓

Is the problem about MCP — server won't connect, no tools, OAuth, config?
  └─ YES → diagnosing-mcp
  └─ NO ↓

Is the problem about SKILLS — not discovered, shadowed, hidden, user-modified?
  └─ YES → diagnosing-skills
  └─ NO ↓

Is the problem about SLASH COMMANDS — missing, overridden, skills-as-commands,
  bundles?
  └─ YES → diagnosing-commands
  └─ NO ↓

Is the problem about HOOKS — not firing, gateway HOOK.yaml, plugin hooks,
  shell hooks?
  └─ YES → diagnosing-hooks
  └─ NO ↓

Is the problem about PLUGINS — not loading, not enabled, plugins.enabled gate?
  └─ YES → diagnosing-plugins
  └─ NO ↓

Still unsure?
  └─ Ask the clarifying questions in §3.
  └─ If the user is asking "where is X configured?" → hermes-configuration-guide
```

## 1b. Runaway session (looping agent)

Signature (live incident: 47-turn session, 20+ tool-turns/turn, 70K+ input
tokens/call on a free-tier default model): the agent repeats the
same answer or tool sequence every turn, and interrupts produce
meta-reasoning about looping without changing course. Interrupts fire
correctly — the defect is that interrupt repair re-sends the full context
and a weak model regenerates the same output.

1. Kill the session, don't rescue it — each post-interrupt turn reasons about the loop itself and poisons context further.
2. Inspect `config.yaml` `model:` — a `:free` default paired with a large context is a known loop-risk configuration (one factor among others, not a sole cause). Use a capable model for research/agentic work.
3. Split the task: one turn generates candidates with no verification, a later turn verifies only the shortlist. Interleaving generation with per-item checks is what the loop feeds on.
4. `hermes guide sessions` detects the signature early (turns/api-calls, tool-turns, context size, free-tier flag) — run it at the first "looping again" report, not the tenth.

## 2. Symptom → Skill mapping table

The flowchart above resolves most reports. When it doesn't match, grep the full symptom table in `references/symptom_map.md` — 68 rows from specific symptoms to the target skill. Load the matched skill directly.

## 3. Clarifying questions

When the description is too vague to route with confidence, ask these questions before guessing. Pick the question(s) that match the ambiguity.

### Scope questions

- **"Is this about the CLI/TUI, the desktop app, or a messaging platform?"**
  - CLI/TUI (native Windows) → diagnosing-cli-tui; POSIX/WSL → `hermes doctor`
  - Desktop app → diagnosing-desktop
  - Messaging platform → diagnosing-gateway (or diagnosing-bot-mode if it's about bot profiles)

- **"Is this about a specific feature (MCP, skills, hooks, plugins) or general performance?"**
  - Specific feature → route to that feature's skill
  - General performance → diagnosing-host-pressure

### History questions

- **"Did this work before and stop, or never work?"**
  - Worked before, stopped → likely config drift, token expiry, or resource pressure; check diagnosing-auth, diagnosing-host-pressure, or the relevant feature skill
  - Never worked → likely install, path, or config issue; check installing-hermes, diagnosing-path, or hermes-configuration-guide

### Consistency questions

- **"Is the problem consistent or intermittent?"**
  - Consistent → likely a config or code issue; route to the relevant feature skill
  - Intermittent → likely resource pressure, rate-limiting, or a race condition; check diagnosing-host-pressure or diagnosing-auth

### Surface questions

- **"Is this about installing something, or about something that's already installed?"**
  - Installing → diagnosing-auth (hub installs) or installing-hermes (Hermes itself)
  - Already installed → route to the relevant feature skill

## 4. Escalation

When multiple skills might apply, the priority rules live in one place:
the Disambiguation list in `hermes-configuration-guide` (canonical — order
there is load-first priority). Apply it instead of re-deriving precedence
here; this section keeps only triage-local escalation.

### When to load multiple skills

Some problems span multiple layers. Load the higher-priority skill first
per the canonical list, then the second.

### When to use hermes-configuration-guide

If the user is asking "where is X configured?" rather than "X is broken", load `hermes-configuration-guide` instead of a diagnostic skill. The configuration guide maps each extension surface to its config location and points to the right diagnostic skill if something is wrong.

---

## 5. Report format

When the triage skill routes to a diagnostic skill, the model reports findings using the standard format defined in `hermes-configuration-guide`. The triage skill itself reports only the routing decision:

**Golden prompts:** `skills/diagnosing-triage/goldens.md` is a manual regression set — run it after any flowchart or mapping-table edit to verify routing still matches expectations.

**Triage report example**:

- **Summary**: "Your description matches a host resource pressure problem. Load average is high with idle CPU, indicating I/O bottleneck."
- **Routed to**: `diagnosing-host-pressure`
- **Reason**: "High load + idle CPU + plugin load timeouts = host pressure, not Hermes config"
- **Next step**: "Run `bash skills/diagnosing-host-pressure/scripts/host_pressure_probe.sh` and follow the resolution order in that skill."

*Facts re-verified 2026-10-13 against upstream source at commit `50035ef63c5536757e63bc1c1ffe4e5c19ac7fad` and this repo's `skills/` directory (every mapped skill resolves; no renames); routing behavior verified live on Hermes v0.21.7 (Windows native) — unnamed headless runs do not auto-load triage (D4), and free-style answers invented 8 `hermes` subcommands (D5). Runaway-session branch (§1b, §0b row, symptom-map row, goldens A8/B5b) verified against a live runaway in `$HERMES_HOME/logs/agent.log` (session `20261016_021208_97c585`; agent.log timestamps read 2026-10-16 local, matching the session id). `x update` row + symptom-map stale-lock row point at the diagnosing-cli-tui §1 stale-lock note with a no-baseline exception (update-lock check verified by tools/test_update_lock.py; rows re-checked 2026-10-16). §4 escalation rules moved to the canonical config-map list 2026-10-16 (verbatim move, pointer left behind). Routing additions verified 2026-10-16 (retry-loop vs wedge split to diagnosing-path; outdated-plugin `2 bad scope` → `hermes plugins update hermes-guide`). Re-verify before reuse.*
