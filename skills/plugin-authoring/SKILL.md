---
name: plugin-authoring
description: "Author Hermes plugins (plugin.yaml + register(ctx)) and skills (SKILL.md) — scaffolding, registration, hooks, commands, capabilities, versioning, provenance, and the read-only contract."
version: 1.5.2
metadata:
  hermes:
    tags: [hermes, plugin, skill, authoring, guide]
    related_skills: [hermes-configuration-guide, diagnosing-plugins, diagnosing-skills]
---

# Authoring Hermes Plugins and Skills

Hermes extensions come in two shapes: **plugins** (Python packages with a
`plugin.yaml` manifest and a `register(ctx)` entry point) and **skills**
(Markdown files with YAML frontmatter, loaded by the skills engine). This
skill covers both — scaffolding, registration, hooks, commands, capabilities,
versioning, and the read-only contract.


## Plugin authoring (summary)

Detailed reference: `references/plugin-authoring.md`

A plugin is a directory with at minimum `plugin.yaml` + `__init__.py` (with
`register(ctx)`). See the reference for full field documentation, examples,
and the read-only contract.

Key points:
- `plugin.yaml`: `name`, `version` (quoted), `manifest_version`/`api_version`
  (both `1`), `requires_hermes`, optional `python_dependencies` (validated
  and surfaced only — never auto-installed), `config_schema` (mismatch
  reporting only — no default merge on install).
- `register(ctx)`: `register_command`, `register_cli_command`, `register_hook`.
- Slash command handler: at `cedf4a3d` (baseline), handlers receive only
  `raw_args: str`. Context keywords (`source`, `session_id`, `session_key`,
  `platform`) were introduced later in `06e8c5bc` — use `**context` to opt
  in, but only on Hermes versions that include that commit.
- `ctx.get_config(key, default)` requires a key. Use
  `hermes_constants.get_hermes_home()` for the home path.
- Capabilities: omit `capabilities:` for read-only. Enforced by CI.
- Hooks: valid events in `VALID_HOOKS` (`hermes_cli/plugins.py`). Timeouts
  (30s default, 600s cap) apply only to bounded allowlist; `on_session_finalize`
  runs synchronously without timeout.
- **Verification checklist:** `references/plugin-authoring.md` contains a
  26-item checklist to verify a plugin meets official Hermes standards
  (manifest, registration, read-only contract, activation).

## Skill authoring (summary)

Detailed reference: `references/skill-authoring.md`

A skill is a directory with a single `SKILL.md`. See the reference for
frontmatter, naming, content rules, provenance, versioning, and routing.

Key points:
- Frontmatter: `name` (must match dir), `description`, `version` (quoted),
  `metadata.hermes.tags` + `related_skills`.
- Provenance footer: final non-empty line dated and upstream-anchored.
- Version bumps: typo → patch, new content → minor, rewrite → major.
- Routing (for `diagnosing-*`): config guide bullet, README table, issue
  template dropdown.
- `render_docs.py --write` refreshes generated inventory blocks.

### Common pitfalls

- **Untracked skill directory breaks pre-commit.** `git add skills/<name>/`
  before committing — the gates read the working tree and an untracked
  directory fails the count and routing gates.
- **Handler signature drift.** `register_command`'s docstring summarizes the
  handler as `fn(raw_args: str)`, but the real contract lives in
  `hermes_cli/plugin_command_dispatch.py::invoke_plugin_command` (introduced
  in `06e8c5bc`) — it passes `raw_args` plus opt-in context keywords
  (`source`, `session_id`, `session_key`, `platform`). At `cedf4a3d`, only
  `raw_args` is passed. A handler that declares `ctx` as a positional
  parameter raises `TypeError` at invocation. Always read the dispatch module
  for the target Hermes revision.
- **render_docs word-list ceiling.** `_word_num()` in `render_docs.py`
  spells numbers up to twenty-eight. Adding a twenty-ninth skill
  deliberately requires extending `_WORDS`. The guard exists so a new skill
  count forces someone to look at the prose rather than silently producing
  a number.
- **README table + issue template parity.** Every shipped skill must
  appear in the README skill table AND the `.github/ISSUE_TEMPLATE/
  skill-drift.yml` dropdown. `tools/test_skill_counts.py` (CI-tier)
  enforces this — run it after adding a skill.
- **Repository-only checks.** `python tools/check_gates.py`,
  `tools/render_docs.py`, and `tools/test_skill_counts.py` are for
  contributions to hermes-guide. External projects use their own CI.
- **Bot review threads.** Qodo runs automatically; CodeRabbit requires
  `@coderabbitai full review`. Resolve every thread with file:line evidence
  before merge — never auto-resolve to unblock. A silent or empty
  CodeRabbit run counts as "not heard", not "clean".
- **Hardcoded hook event names.** The valid set is `VALID_HOOKS` in
  `hermes_cli/plugins.py` and grows across releases. Read the installed source.
- **Hardcoded venv paths.** Use `project_venv_dir()` / `committed_venv()` /
  `project_python()` — never hardcode `venv/` or `.venv/`.
- **CLI commands in skills are validated.** Every backtick command in a
  SKILL.md is checked by `tools/check_cli_surface.py` against the installed
  Hermes CLI. Verify commands with `hermes <cmd> --help` before writing them
  — hermes sessions show does not exist (use hermes sessions list).
- **Secure file permissions in recommendations.** Never recommend `chmod 644`
  on sensitive files like `state.db` — use `chmod 600` to preserve
  owner-only access. Conversation/tool history must not be world-readable.
- **Manual update commands must reinstall deps.** `git pull` alone leaves the
  runtime environment out of sync. Always include `pip install -e .` or
  prefer `hermes update`.
- **Confusing Hermes with Claude Code.** Hermes has no standalone command files
  (commands come from built-ins, skills-as-slash, bundles, and plugins); hooks
  span four separate systems; plugins are `plugin.yaml` + `register(ctx)`, not
  `plugin.json`.
- **Confusing hermes-guide with hermes-agent.** hermes-guide is a diagnostics
  plugin + skills tap that only inspects Hermes. Never edit Hermes source to
  fix a guide finding.
- **Hermes config is YAML, never JSON.**
- **Every diagnosis should end in a concrete action** followed by a `/reload-*`
  or restart.

*Facts verified 2026-10-31 against upstream source: `hermes_cli/plugins.py` at `cedf4a3d` (VALID_HOOKS, register_hook, register_command — documents `fn(raw_args: str)` only); `hermes_cli/plugin_command_dispatch.py` introduced in `06e8c5bc` (context-keyword contract); `hermes_cli/plugins_manifest.py` at `cedf4a3d` (requires_hermes, python_dependencies, config_schema); `hermes_cli/skills_hub.py` at `cedf4a3d` (tap install); `tools/render_docs.py` (_word_num ceiling, selftest guard); `tools/test_skill_counts.py` (README table + issue template parity); and the official docs (hermes-agent.nousresearch.com/docs). Plugin manifest fields and skill frontmatter verified against this repo's own `plugin.yaml` and `skills/*/SKILL.md`. Re-verify before reuse.*
