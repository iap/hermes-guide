# AGENTS.md

Instructions for AI coding agents working in this repository.

## Project Overview

**hermes-guide** is a [Hermes Agent](https://github.com/NousResearch/hermes-agent) **plugin + skills tap**. The plugin (`plugin.yaml` + `__init__.py`/`checks.py`/`constants.py`) exposes read-only diagnostics (`/hermes-doctor` and `hermes guide`), and the `skills/` directory bundles thirteen SKILL.md files that teach agents and users how to configure and troubleshoot MCP servers, skills, commands, hooks, plugins, hub auth, memory, paths/venvs, the Windows CLI/TUI, the desktop app, and model providers.

Two install paths: the plugin (`hermes plugins install iap/hermes-guide --enable`, or a git clone into `$HERMES_HOME/plugins/hermes-guide/` + `hermes plugins enable hermes-guide`) and the tap (`hermes skills tap add iap/hermes-guide`). On native Windows `$HERMES_HOME` is `%LOCALAPPDATA%\hermes`; on POSIX it is `~/.hermes`. Confirm with `hermes config path`.

## Repository Structure

| Path | Purpose |
|---|---|
| `plugin.yaml` | Plugin manifest (name, version, config schema) |
| `__init__.py` | Plugin entrypoint — registers `/hermes-doctor` and `hermes guide` (the thirteen skills ship separately via the skills tap) |
| `checks.py` | The seven read-only health checks (config/mcp/skills/commands/hooks/plugins/memories) |
| `constants.py` | Single source of truth for names/values that drift across Hermes versions |
| `skills/*/SKILL.md` | Thirteen skills: one config map (`hermes-configuration-guide`), one install guide (`installing-hermes`), eleven `diagnosing-*` |
| `tools/` | Guard linters (no-mutation, self-claim, version bump, provenance, citation integrity, upstream drift) + regression tests, all run by CI |
| `README.md` | Plugin + tap overview, install instructions, skill table |
| `AGENTS.md` | This file — agent instructions for working on the repo |
| `CLAUDE.md` | `@AGENTS.md` import (Claude Code entry point) |
| `.github/workflows/ci.yml` | CI — py_compile, mypy, `hermes plugins doctor . --ci`, guard linters, regression tests, citation integrity vs the upstream baseline, skill provenance, bandit |
| `.github/workflows/upstream-drift.yml` | Weekly upstream drift watch (`tools/check_upstream_drift.py`) — opens an issue when Hermes changes watched schema files or drift-prone facts |
| `CONTRIBUTING.md` | Contribution guidelines (branches, commits, PRs, writing style) |
| `SECURITY.md` | Security policy |
| `LICENSE` | MIT License |

## Multi-environment maintenance

This repo is maintained in parallel from **different host environments** (native Windows, macOS/POSIX), each with its own checkout and its own installed Hermes. Scope your work to the environment you are running in, and remember it across your sessions:

- **Verify platform-dependent facts only on your own machine.** `$HERMES_HOME` resolution (`%LOCALAPPDATA%\hermes` vs `~/.hermes`), CLI/TUI behavior, installers, paths, shells. Never assert a platform fact you could not verify here — the session running on that platform owns its verification (e.g. the Windows-native agent owns `diagnosing-cli-tui` and the Windows sides of `diagnosing-path`/`diagnosing-desktop`; the POSIX agent owns `~/.hermes` behavior).
- **Cross-platform changes** (CI, `constants.py`, shared skill text) must say which platform verified them, and leave platform-specific wording the other environment can adjust.
- **Expect parallel sessions.** Rebase before pushing, and check open PRs before starting overlapping work — duplicate fixes have collided before (see #54/#55).

## Guidelines

### What belongs in git

Publish only the plugin + tap surface and the maintainer harness that CI runs. Everything else stays local unless the user explicitly asks to commit it.

| Commit | Do not commit |
|---|---|
| `plugin.yaml`, `__init__.py`, `checks.py`, `constants.py` | Secrets and env files (`.env`, tokens, credentials) — already gitignored; never force-add |
| `skills/*/SKILL.md` | Local agent/verification scratch: `.cluster/`, `.verify/`, root `tmp*.json` / `q*.json` |
| `tools/check_*.py`, `tools/test_*.py`, `.github/workflows/` | IDE/OS junk, venvs, caches, logs, archives (see `.gitignore`) |
| `README.md`, `AGENTS.md`, `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE` | Unsolicited new top-level files or directories — ask first |
| Intentional `.gitignore` updates when a recurring private path appears | Personal notes, one-off probes, or “just in case” dumps |

Rules of thumb:

- **Default deny for new paths.** If a file is not required for someone else to install the plugin, use the skills, or run CI, leave it untracked (and add a `.gitignore` pattern when the path will keep coming back).
- **Ignore is the durable control; AGENTS.md is the reminder.** Prefer extending `.gitignore` over relying on “remember not to `git add`.”
- **Never commit secrets**, even if the user pastes them into the workspace. Warn and keep them out of the index.
- **Do not `git add -A` / `git add .`** in this repo — stage named paths so scratch and secrets cannot ride along.
- **User intent wins.** If they explicitly want a previously private path published, stage that path on purpose and say so in the commit message; do not silently broaden the ignore rules afterward without asking.

### What to edit

| Change | Touch |
|---|---|
| Upstream name/value drift | `constants.py` (not hard-coded strings in `checks.py`) |
| New or changed health surface | `checks.py` + `_CHECKS`, then matching skill text if users need a fix path |
| How-to / troubleshooting | `skills/<name>/SKILL.md` + bump `version` + refresh provenance footer |
| Repo CI / guard / regression | `tools/check_*.py` or `tools/test_*.py` (+ wire the step in `.github/workflows/` when it must gate PRs) |

Keep the layout stable: plugin Python at repo root (`plugin.yaml`, `__init__.py`, `checks.py`, `constants.py`), skills under `skills/<name>/SKILL.md`, harness scripts only under `tools/`. Do not add ad-hoc scripts at the root or under `skills/` that CI or agents are expected to run.

### Layers and output contracts

This repo has **three audiences**. Do not mix their output shapes, exit codes, or wording:

| Layer | Lives in | Audience | Contract |
|---|---|---|---|
| Hermes CLI | Upstream `hermes …` | End users / agents diagnosing a live install | Whatever Hermes prints; this repo may *parse* it inside checks but must not rebrand or rewrite Hermes messages as if they were ours |
| Plugin UX | `__init__.py` + `checks.py` | `/hermes-doctor` and `hermes guide` | Check **envelopes** (`status` / `reason` / `detail`); render with `+/x/~/?`; `hermes guide` exits `0` healthy/informational, `1` broken/unknown, `2` bad scope. Proactive mode logs via the logger — no stdout report |
| Repo harness | `tools/` | CI and maintainers | Machine-friendly guard/test output (`OK:` / `FAIL` / `error:` on stderr); exit `0` clean, non-zero on failure. Optional `--selftest` / `--warn` stay harness-only flags |

Rules of thumb:

- **Checks return data; the plugin formats UX.** A check must not `print` a doctor-style report or invent a second exit-code scheme — return an envelope and let `_format_result` / `_run_cli` own presentation.
- **Harness scripts must not impersonate the plugin.** No `+/x/~/?` doctor lines, no `hermes guide`-style scope UX, no check envelopes as the primary CLI product. Speak as a repo guard (`OK: …`, `FAIL: …`, `error: …`).
- **When a check shells out to Hermes**, keep Hermes stdout/stderr as evidence inside `detail` / `reason` — do not reformat Hermes output into harness `OK:`/`FAIL` lines, and do not pipe harness chatter into `/hermes-doctor`.
- **New tool?** Prefer `tools/check_<concern>.py` (linter/guard) or `tools/test_<concern>.py` (regression). Mirror neighbors: argparse or argv flags, `--selftest` when the detector needs its own fixture, stderr for errors, a one-line pass/fail summary, and a non-zero exit on failure.
- **Skills teach Hermes + plugin behavior** to users; they are not a place to document harness CLI flags unless a maintainer must run that tool to keep the skill honest (provenance / citation).

### Authoring skills

- Each skill lives in its own directory under `skills/<name>/SKILL.md`.
- **Naming convention**:
  - `diagnosing-<surface>` for diagnostic skills (e.g. `diagnosing-mcp`, `diagnosing-path`) — kebab-case, lowercase, ≤20 characters.
  - `hermes-` prefix reserved for the configuration map (`hermes-configuration-guide`; 26 chars, predates the limit, exempt).
  - `installing-hermes` is the install guide — do not rename it to `diagnosing-*`.
- Frontmatter requires `name` (slug), `description` (keep it short), and `version` (semver).
- Content must be **verified against the Hermes source this environment runs** (local checkout or install) — specifically `website/docs/` for documentation and `hermes_cli/` / `agent/` / `hermes_constants.py` for source truth. Do not rely solely on web search; the installed copy is authoritative for the version in use.
- Every `SKILL.md` must end with a **provenance footer** on the final non-empty line: `Facts (re-)verified YYYY-MM-DD … upstream …` plus a revision (a backticked hex sha, or the words `commit` / `baseline` / `main`). `tools/check_skill_provenance.py` enforces the shape.
- File/symbol citations (`path.py::symbol`, `path.py:123`) must resolve against the revision in `.github/upstream-drift.baseline`. CI runs `tools/check_citation_integrity.py`; locally pass `--src` to a Hermes checkout (or set `HERMES_AGENT_SRC`).
- Hermes configuration is **YAML** (`config.yaml`), not JSON. Never reference JSON config syntax.
- `$HERMES_HOME` resolves to `~/.hermes` on POSIX but `%LOCALAPPDATA%\hermes` on native Windows. Teach `hermes config path` as the ground-truth command.
- Every diagnosis must resolve to a concrete action: a `hermes <subcommand>` command or a specific file + field edit, then a `/reload-*` or restart to apply.
- When Hermes behavior changes, update the affected skill(s) and bump their `version`.

### Authoring plugin code

- `constants.py` is the single source of truth for names/values that drift across Hermes versions; update it (not `checks.py`) when an upstream name changes.
- Checks in `checks.py` must stay **read-only** — resolve paths, read files, parse, and shell out to read-only `hermes ...` commands. Never mutate config or auto-fix.
- A new check: add the function to `checks.py` and register it in the `_CHECKS` list. It must return an envelope (`status`, `reason`, `detail`) and tolerate malformed input without crashing.
- `plugin.yaml` `capabilities:` stays empty on purpose (zero privileged capabilities); don't add capabilities without a concrete need.
- Presentation and exit codes stay in the plugin layer — see **Layers and output contracts** above.

### Style

- Name the exact `hermes` command (e.g. `hermes config path`), not a generic description ("run the config command").
- Tables for structured data (pitfall catalogs, system comparisons). Bullet lists for steps.
- Keep each SKILL.md focused on one surface (one of: config map, install, mcp, skills, commands, hooks, plugins, path, cli-tui, auth, memory, desktop, providers).
- **Describe behavior — don't assert quality.** Say what the plugin and skills do, not how good they are. CI enforces this via `tools/check_self_claim.py` (deny-list in that script).
- Use GitHub alert callouts where they genuinely help:
  > [!NOTE] — context not to miss
  > [!TIP] — optional shortcut
  > [!IMPORTANT] — required for success
  > [!WARNING] — breakage/data loss risk
  > [!CAUTION] — irreversible action

### Common pitfalls to avoid

> [!WARNING]
> **Don't mix output layers.** Harness scripts (`tools/`) must not print `/hermes-doctor` reports or speak as Hermes; checks must not print harness `OK:`/`FAIL` lines; skills must not invent a fourth CLI. Keep Hermes stdout as evidence inside envelopes, plugin marks (`+/x/~/?`) for user diagnostics, and `OK:`/`error:` for CI.

> [!WARNING]
> **Don't confuse Hermes with Claude Code or ZCode**. Hermes has no standalone command files (commands come from built-ins, skills-as-slash, bundles, and plugins). Hooks have four separate systems, not one. Plugins use `plugin.yaml` + `register(ctx)`, not `plugin.json`.

> [!WARNING]
> **Don't copy zcode-guide patterns blindly** — Hermes differs structurally (commands, hooks, and plugin format are all different).

> [!IMPORTANT]
> **Don't guess hook event names**. The valid set lives in `hermes_cli/plugins.py:VALID_HOOKS` and grows across releases — verify against the installed source rather than a hardcoded count.

> [!NOTE]
> **Don't hardcode venv paths**. Hermes has a dual-venv layout: `venv/` (created by installers) and `.venv/` (uv's default) can coexist. Upstream's `project_venv_dir()` in `hermes_constants.py` resolves `venv` first — when both exist, `venv` wins. Resolve via `project_venv_dir()` / `venv_bin_dir()` from `hermes_constants.py`, or mirror that order; never assume either name. See the `diagnosing-path` skill for detection patterns, canonical resolution order, and cross-platform best practices.

### Testing and validation

CI enforces a syntax check, mypy, the plugin self-check, the `tools/` guard linters (including provenance and citation integrity), and the `tools/` regression suite. Before declaring work complete:

**Always (plugin or shared code):**

1. Run `python -m py_compile __init__.py checks.py constants.py`.
2. Run `hermes plugins doctor . --ci` from the repo root.
3. Run `python tools/check_no_mutation.py --selftest && python tools/check_no_mutation.py && python tools/check_self_claim.py`, then every `python tools/test_*.py`.

**When a `SKILL.md` changes (also):**

4. Bump its `version` frontmatter (`tools/check_skill_version_bump.py` enforces this against the merge base).
5. Confirm YAML frontmatter parses cleanly (three dashes, valid keys, no tab indentation in YAML).
6. Refresh the provenance footer date/revision; run `python tools/check_skill_provenance.py`.
7. Cross-check every `hermes <subcommand>` reference against the installed Hermes docs or `--help` output.
8. If you added or changed file/symbol citations and have a Hermes checkout: `python tools/check_citation_integrity.py --src <hermes-checkout>` (revision defaults to `.github/upstream-drift.baseline`). Skip only when no checkout is available — state that skip.
9. Verify `$HERMES_HOME` path wording for both POSIX and Windows when the skill mentions home paths.
10. State what was checked, what passed, and what was skipped.

Beyond the CI gates, smoke-test the *model-facing* behavior with a one-shot run — this verifies discovery AND that the skill's instructions are actually followed:

```bash
hermes -z "Use the diagnosing-path skill: which interpreter should a script in the Hermes checkout use?"
```

Run it **without** `--skills` preloading when the skill is discoverable from `$HERMES_HOME/skills/` — preloading masks trigger failures, and the description routing on its own is the most common real-world defect. Verify both layers: the deterministic check first (`hermes guide <scope>` for plugin-covered surfaces), then the model-facing run.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full contribution workflow, branch naming, commit message format, and content guidelines.
