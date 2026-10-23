---
name: diagnosing-triage
description: "Route 'something is wrong / slow / crashed / stopped working / not responding / won't launch / not firing' to the right diagnosing-* playbook — triage layer mapping symptoms to skills."
version: 1.1.0
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

- Headless / one-shot: `hermes guide` (all scopes) or `hermes guide <scope>`. On a degraded host where every launch takes minutes, add `--fast` — in-process checks, no subprocess; helps when launches are slow, not when the CLI is wedged (the no-baseline exception below still applies). When the shell is available, prefer the JSON document: `hermes guide --json` (or `hermes guide <scope> --json`) carries the same findings — `broken`/`unknown` envelopes with stable `id`s, the sanctioned `fix`es, and `informational` ones as plain envelopes — fall back to the text report (and say so) when the flag errors: installs older than the release carrying `--json` answer with an argparse usage error and exit `2`.
- In-session: `/hermes-doctor` or `/hermes-doctor <scope>`.

Route its `~`/`x`/`?` lines first:

| Baseline line | Load |
|---|---|
| `~ commands` (e.g. a skill slug shadowing a builtin) | diagnosing-commands |
| `~ memories` (store near/over limit, undated entries) | diagnosing-memory |
| `~ update` (lock owner alive, or dead owner with a free checkout) | diagnosing-cli-tui §1 stale-lock note |
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

## 0c. Finding-id decision table

Every `broken`/`unknown` finding the baseline reports carries a stable `id`
(the generated catalog lives in `docs/findings.md` in the repo). Use this
table to turn each id into what you present to the user: at most three
options — a session-scoped workaround, the sanctioned fix, or proceeding
without the capability — and never a persistent change without explicit
confirmation in the same turn.

Two rules bound the table: repair of runtime state belongs to upstream
(`hermes doctor --fix`, `hermes doctor --live`), not to this plugin; and each
command below was checked against a named Hermes build before it was cited —
Hermes Agent v0.22.2+1915.gdd519c7.dirty (upstream `dd519c74`), checked
2026-10-23.

| Symptom | Finding id | Session workaround | Permanent fix (consent first) | Verify |
|---|---|---|---|---|
| Custom provider, model, or tool choice silently reverts to defaults | `CONFIG_PATH_UNRESOLVED` | none safe — acknowledge defaults are untrusted | run `hermes config path`; if it fails, reinstall the Hermes CLI | `hermes guide config` |
| Hermes ignores every custom setting | `CONFIG_MISSING` | none — state that built-in defaults are in force | run `hermes setup`, or restore the file to the reported path | `hermes guide config` |
| Hermes cannot load its settings at startup | `CONFIG_UNPARSEABLE` | none — every consumer of the file fails | fix the YAML at the reported path (indentation, quoting, duplicate keys) | `hermes guide config` |
| `mcp` or `plugins` reports the config could not be read | `CONFIG_UNREADABLE` | none | check read permissions on the reported path; if readable, fix its YAML | `hermes guide mcp` when the finding came from the `mcp` scope, `hermes guide plugins` when from `plugins` |
| A scope reports the Hermes home unresolved | `HOME_UNRESOLVED` | run `hermes config path` to see whether the profile resolves | restore or correct the profile the check names | `hermes guide <scope>` |
| Listed MCP servers will not start; their tools are missing | `MCP_SERVER_MALFORMED` | name the tools that are absent and move on | in `config.yaml` move foreign keys (e.g. `mcpServers`) under top-level `mcp_servers`, make `mcp_servers` a mapping, fix the listed entries (`command` for stdio, `url` for HTTP) | `hermes guide mcp` |
| Listed skills will not load or are shadowed | `SKILLS_ISSUES` | use the skills that do load; name the missing ones | fix the listed frontmatter, name, or path problems | `hermes guide skills` |
| Commands from a listed bundle do not resolve | `COMMANDS_BUNDLE_MALFORMED` | use the built-ins that still resolve | fix or remove the listed bundle files | `hermes guide commands` |
| Possibly-approved hooks are skipped or re-prompt; detail quotes hook problems | `HOOKS_ALLOWLIST_INVALID` | run hooks manually, expecting re-approval prompts | repair or delete the reported `shell-hooks-allowlist.json`, then fix the hook problems quoted in the detail | `hermes guide hooks` |
| One or more hooks fail or are misconfigured; guarded events unhandled | `HOOKS_DOCTOR_FINDINGS` | reproduce the affected event by hand | fix each hook reported by `hermes hooks doctor` | `hermes guide hooks` |
| Hook health could not be verified; a broken hook can fail silently | `HOOKS_DOCTOR_UNAVAILABLE` | treat hook health as unverified this turn | run `hermes hooks doctor` manually and fix the error it reports | `hermes guide hooks` |
| Hook health undetermined; `hermes hooks doctor` output unrecognized | `HOOKS_DOCTOR_OPAQUE` | same as above: health unknown | run `hermes hooks doctor` manually and compare its output with the installed Hermes version | `hermes guide hooks` |
| Hooks were skipped in this run; failures would only surface in-session | `HOOKS_INSPECTION_UNAVAILABLE` | accept the skip; say what was not measured | run `hermes guide hooks` without `--fast` to inspect hooks on demand | `hermes guide hooks` |
| Hooks cannot be inspected; the profile's config file is missing | `HOOKS_CONFIG_NOT_FOUND` | none | run `hermes config path` and restore the profile's `config.yaml` | `hermes guide hooks` |
| Hooks cannot be inspected; the config file could not be loaded | `HOOKS_CONFIG_UNREADABLE` | none | check read permissions on the profile's `config.yaml`; if readable, fix its YAML | `hermes guide hooks` |
| Hook inspection raised an error | `HOOKS_INSPECTION_FAILED` | none | re-run `hermes guide hooks`; if it repeats, report the exception type from the reason | `hermes guide hooks` |
| Shell hooks malformed, unreachable, or not allowlisted | `HOOKS_FINDINGS` | invoke the affected event by hand where possible | fix the listed hook entries in `config.yaml`; approve each valid hook at the interactive prompt when the detail says it is not allowlisted | `hermes guide hooks` |
| `plugins` section is not a mapping; enable/disable settings ignored | `PLUGINS_CONFIG_SHAPE` | plugins run on whatever loads by default | rewrite the `plugins` section in `config.yaml` as a mapping with `enabled` and `disabled` lists | `hermes guide plugins` |
| Enabled plugins missing or failed to load; their commands/tools/hooks absent | `PLUGINS_MISSING_OR_BROKEN` | run without the missing plugin's surface; name what is gone | run `hermes plugins list`; reinstall from the catalog with `hermes plugins install <name>`, or re-link an already-installed one with `hermes plugins update <name>`; for an exclusive provider select its category key (e.g. `memory.provider`) instead of `plugins.enabled` | `hermes guide plugins` |
| Memory files inconsistent; stored context stale or ignored | `MEMORIES_ISSUES` | restate the needed context manually in-chat | fix the listed files under `$HERMES_HOME/memories/` | `hermes guide memories` |
| Session activity cannot be analyzed; runaway sessions undetected | `SESSIONS_LOG_UNREADABLE` | none — measurements stay blind | check read permissions on the reported agent log | `hermes guide sessions` |
| Session log format unrecognized | `SESSIONS_LOG_UNPARSED` | same as above | re-run `hermes guide sessions`; if it repeats, check the log format written by the installed Hermes version | `hermes guide sessions` |
| Agent loops, burning API calls and context without progress | `SESSIONS_RUNAWAY` | kill the session and start a fresh one — do not keep interrupting | start a new session instead of resuming the listed one, and split generation from verification into separate turns; a `:free` default model in `config.yaml` `model:` is one known aggravator, so if it is set, moving off it is a further candidate fix — the finding can occur without it | `hermes guide sessions` |
| Update scope says the install checkout is unresolved | `UPDATE_CHECKOUT_UNRESOLVED` | none — update health unknown | run `hermes doctor` to confirm the install layout | `hermes guide update` |
| Install layout unrecognized; stuck update lock not ruled out | `UPDATE_LAYOUT_UNRECOGNIZED` | treat update health as unknown | run `hermes doctor` to confirm the install layout, then locate the checkout and its update lock by hand | `hermes guide update` |
| An updater's process still holds the checkout and wedges every `hermes` command | `UPDATE_LOCK_HELD` | wait — the holder must exit; the PID in the reason is the dead updater that spawned it, so find the holding process by hand, not by that PID | none — do not remove the lock while it is held; once the holder exits, re-run the check | `hermes guide update` |
| The lock does not name an owner | `UPDATE_LOCK_MALFORMED` | none | confirm no update is running, then remove the reported file with human confirmation | `hermes guide update` |
| The lock could not be probed; a dead owner may hold the checkout | `UPDATE_LOCK_UNPROBEABLE` | none | check for a running `hermes` or `git` process by hand before touching the reported lock file | `hermes guide update` |
| Ownership cannot be determined | `UPDATE_LOCK_INDETERMINATE` | none | check whether the owner PID in the reason is alive by hand before touching the lock file | `hermes guide update` |
| The update lock could not be read | `UPDATE_LOCK_UNREADABLE` | none | check read permissions on the reported lock file | `hermes guide update` |
| A fast-mode run skipped the surface; its real state unknown | `FAST_MODE_UNRESOLVED` | accept the skip; say what was not measured | re-run `hermes guide <scope>` without `--fast` | `hermes guide <scope>` |
| The check itself crashed — a defect in hermes-guide, not in your config | `CHECK_CRASHED` | none | re-run `hermes guide <scope>`; if it repeats, file the exception type and `hermes --version` at https://github.com/iap/hermes-guide/issues | `hermes guide <scope>` |

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

The flowchart above resolves most reports. When it doesn't match, grep the full symptom table in `references/symptom_map.md` — 70 rows from specific symptoms to the target skill. Load the matched skill directly.

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

*Facts re-verified 2026-10-23 against upstream source at commit `50035ef63c5536757e63bc1c1ffe4e5c19ac7fad` and this repo's `skills/` directory (every mapped skill resolves; no renames); routing behavior verified live on Hermes v0.21.7 (Windows native) — unnamed headless runs do not auto-load triage (D4), and free-style answers invented 8 `hermes` subcommands (D5). Runaway-session branch (§1b, §0b row, symptom-map row, goldens A8/B5b) verified against a live runaway in `$HERMES_HOME/logs/agent.log` (session `20261016_021208_97c585`; agent.log timestamps read 2026-10-16 local, matching the session id). `x update` row + symptom-map stale-lock row point at the diagnosing-cli-tui §1 stale-lock note with a no-baseline exception (update-lock check verified by tools/test_update_lock.py; rows re-checked 2026-10-16). §4 escalation rules moved to the canonical config-map list 2026-10-16 (verbatim move, pointer left behind). Routing additions verified 2026-10-16 (retry-loop vs wedge split to diagnosing-path; outdated-plugin `2 bad scope` → `hermes plugins update hermes-guide`). `~ update` row, the `--fast` degraded-host clause, and the row count (re-counted: 70) added 2026-10-17. §0c finding-id decision table added 2026-10-23 (JSON contract consumed per #334): all 32 finding ids tabulated against this repo's `docs/findings.md` catalog (PR-head `tools/render_docs.py` render, cross-checked against `checks.FINDING_IDS`); commands verified live on Hermes Agent v0.22.2+1915.gdd519c7.dirty (upstream `dd519c74`): `hermes --version`, `hermes doctor --fix`/`--live`, `hermes setup --help`, `hermes config path` (`/Users/iap/.hermes/config.yaml`), `hermes skills` (install/tap/inspect subcommands), `hermes plugins` (install/update/list subcommands), `hermes hooks doctor`, `hermes gateway status`; `--json` fallback wording keyed off the flag erroring (argparse exit `2`, observed on this host because hermes-guide 0.8.7 predates #336), not off a hard version number. Review-round corrections 2026-10-23 (semantic re-checks against the repo source, no new live facts): `SESSIONS_RUNAWAY` no longer implies `model:` is part of the sanctioned fix for every finding; `PLUGINS_MISSING_OR_BROKEN` carries the concrete reinstall commands (`hermes plugins install <name>` from the catalog, `hermes plugins update <name>` for an installed one); `CONFIG_UNREADABLE` verifies against the scope that reported it (mcp or plugins); `UPDATE_LOCK_HELD` row reworded to the check's semantics (`checks.py::check_update_lock` — a live owner renders as the informational update-in-progress line, while this id means the owner PID is dead and a process it started still holds the checkout). Re-verify before reuse.*
