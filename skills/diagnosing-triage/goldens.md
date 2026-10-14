# Triage golden prompts

Manual regression set for `diagnosing-triage`.
Hermes does **not** auto-run this file. Use it to check that vague symptoms still route to the expected skill after flowchart edits.

**Skill under test:** `skills/diagnosing-triage/SKILL.md` (keep version in sync when routing rules change)
**How to run:** live session with triage installed, or headless `hermes -z "Use the diagnosing-triage skill: <prompt>"`
**Pass rule:** first routing decision matches **Expected** (or an allowed alternative). Clarifying questions count as a pass when Expected says "clarify".

Record date, Hermes version, and OS when you run a pass. Update this table when you intentionally change routing — do not "fix" goldens by weakening Expected without a skill change.

---

## A. Baseline-first (§0b)

Run `hermes guide` (or `/hermes-doctor`) **before** pure symptom routing when a baseline is available. These rows check that baseline lines drive the skill, not the user's vague words alone.

| # | Setup / input | Expected |
|---|---------------|----------|
| A1 | Baseline shows `x mcp`; user says "something is wrong" | `diagnosing-mcp` (baseline wins over vague text) |
| A2 | Baseline shows `x hooks` | `diagnosing-hooks` |
| A3 | Baseline shows `~ memories` (near/over limit) | `diagnosing-memory` |
| A4 | Baseline shows `~ commands` (skill slug shadowing builtin) | `diagnosing-commands` |
| A5 | Baseline shows `x config` | `hermes-configuration-guide` Step 0, then re-run scope |
| A6 | Baseline shows `?` (unknown) | treat as unmeasured — resolve home/config via configuration guide; never call unknown "healthy" |
| A7 | Baseline all `+` healthy; user still vague | continue symptom flowchart / §3 clarify — do not invent a broken surface |

---

## B. Vague entry (load triage)

| # | User line | Expected |
|---|-----------|----------|
| B1 | Something is wrong with Hermes. | triage loaded; prefer §0b then §3 clarify if no baseline signal — not a random `diagnosing-*` |
| B2 | It keeps timing out. / It's slow. | clarify via §3 (specific feature vs general performance) — do NOT route directly to `diagnosing-host-pressure` without asking |
| B3 | Several things broken at once, intermittent. | `diagnosing-host-pressure` (escalation: multi-surface + intermittent) |
| B4 | It crashed. / It stopped working. | clarify surface (§3 scope questions) — do NOT guess `diagnosing-host-pressure` or `diagnosing-desktop` without a named surface |
| B5 | The bot isn't responding. (no platform named) | `diagnosing-gateway` first — not `diagnosing-bot-mode` first |
| B6 | Skills aren't working. (no discovery vs /command) | clarify: "Is the skill missing from the index, or is its `/command` missing?" → `diagnosing-skills` if discovery, `diagnosing-commands` if `/command` |
| B7a | I can't install a skill/plugin (hub install fails) | `diagnosing-auth` (dead token degrades every hub adapter) |
| B7b | I can't install/upgrade/reinstall Hermes itself | `installing-hermes` |
| B8 | Where is X configured? | `hermes-configuration-guide` — not a diagnosing-* skill |

---

## C. Flowchart first-match (named enough to route, still triage-shaped)

| # | User line | Expected |
|---|-----------|----------|
| C1 | hermes skills install fails / could not fetch from any source | `diagnosing-auth` |
| C2 | Need to reinstall / upgrade Hermes itself | `installing-hermes` |
| C3 | High load, OOM, plugins discarded after load timeout | `diagnosing-host-pressure` |
| C4 | Desktop app blank window / won't launch | `diagnosing-desktop` |
| C5 | TUI garbled on **native Windows** | `diagnosing-cli-tui` |
| C6 | TUI issues on **Linux/WSL** | `hermes doctor` + `display:` in config — **not** `diagnosing-cli-tui` |
| C7 | Wrong venv / wrong Python | `diagnosing-path` |
| C8 | Bot not responding on Telegram/Discord (platform implied) | `diagnosing-gateway` first |
| C9 | Gateway healthy; bot profiles/conflicts only | `diagnosing-bot-mode` |
| C10 | CDP / Playwright / Chrome automation | `diagnosing-browser` |
| C11 | Cron not firing / scheduler wedged | `diagnosing-cron` |
| C12 | STT/TTS / ffmpeg voice errors | `diagnosing-voice` |
| C13 | MCP won't connect / no tools | `diagnosing-mcp` |
| C14 | Skills not discovered / shadowed | `diagnosing-skills` |
| C15 | Slash command missing / overridden | `diagnosing-commands` |
| C16 | Hook not firing | `diagnosing-hooks` |
| C17 | Plugin not loading / plugins.enabled | `diagnosing-plugins` |
| C18 | Provider picker flooded / model catalog | `diagnosing-providers` |
| C19 | Agent forgot / MEMORY.md errors | `diagnosing-memory` |

---

## D. Escalation / anti-patterns

| # | Situation | Expected |
|---|-----------|----------|
| D1 | Hub install "not found" + user blames skills | `diagnosing-auth` before `diagnosing-skills` |
| D2 | Multi-surface failures + one blank desktop window | `diagnosing-host-pressure` **before** `diagnosing-desktop` |
| D3 | User already said "MCP won't connect" | **do not** load triage — go straight to `diagnosing-mcp` |
| D4 | Headless `hermes -z` without naming a skill | skill auto-discovery may not fire — goldens must name triage explicitly |
| D5 | Vague triage answer needs a fix command | use only subcommands from `hermes --help`, skill playbooks, or `hermes guide <scope>` — never invent `hermes python …` / `hermes db …` / `hermes channels` / unlisted `hermes plugins install <name>`; verify every cited subcommand exists before reporting |

---

## Run log (fill in when you execute)

| Date | Hermes | OS | Pass / Fail | Notes |
|------|--------|-----|-------------|-------|
| 2026-10-13 | v0.21.7+279.g9bda154 | Windows native | Pass — D4 holds | B1-general ×2, P1, P2-attempt-1, all unnamed headless: triage not auto-loaded; free-style answers (8 invented subcommands once, 0 once; P1 answered model_catalog, missed discover_models contract; P2 attempt timed out with no output) |
| 2026-10-13 | v0.21.7+279.g9bda154 | Windows native | Pass — B1 | named invocation: §0b baseline drove `x plugins` routing; 0 invented subcommands; grade A, docked from S only for missing explicit triage citation |
| 2026-10-13 | v0.21.7+279.g9bda154 | Windows native | Pass — C16 with latency note | P2 hook-prompt retry (unnamed): enumerated all 4 hook systems, correct empty-hooks diagnosis, read-only close; 112s first-byte latency, first attempt's timeout was transient |

Failed rows → fix `SKILL.md` flowchart/table (and bump skill version), or document an intentional Expected change in the same PR.
