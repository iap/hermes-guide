---
name: plugin-authoring
description: "Author Hermes plugins (plugin.yaml + register(ctx)) and skills (SKILL.md) — scaffolding, registration, hooks, commands, capabilities, versioning, provenance, and the read-only contract."
version: 1.1.0
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

## Plugin authoring

A plugin is a directory containing at minimum two files:

```
my-plugin/
├── plugin.yaml       # manifest
└── __init__.py       # register(ctx) entry point
```

### plugin.yaml

```yaml
name: my-plugin
version: "1.0.0"           # quoted string
description: >-
  One or two sentences describing what the plugin does.
manifest_version: 1
api_version: 1
license: MIT
requires_hermes: ">=0.21"
homepage: https://github.com/you/my-plugin
tags: [diagnostics, observability]
python_dependencies:
  - PyYAML>=6.0,<7
config_schema:
  proactive:
    type: bool
    default: false
    description: "Enable proactive checks (opt-in)"
```

Key fields:
- `name` — must match the directory name and the package name.
- `version` — quoted semver string.
- `manifest_version` / `api_version` — both `1` for current Hermes.
- `requires_hermes` — version constraint; unsatisfied builds skip the plugin.
- `capabilities:` — omit entirely or keep empty for read-only plugins. A
  non-empty capabilities block requires user consent at install.
- `python_dependencies` — pip-installable deps; Hermes installs them into the
  plugin's venv.

### register(ctx)

```python
"""my-plugin — one-line description."""

__version__ = "1.0.0"

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def register(ctx):
    ctx.register_command(
        "my-command",
        handler=_handle_command,
        description="What this command does",
    )
    ctx.register_cli_command(
        name="my-cli",
        help="CLI subcommand help text",
        setup_fn=_setup_cli,
        handler_fn=_run_cli,
    )
    # Hooks (optional):
    ctx.register_hook("on_session_start", _on_start)
```

`ctx` exposes:
- `register_command(name, handler, description)` — slash command (CLI + gateway)
- `register_cli_command(name, help, setup_fn, handler_fn)` — `hermes <name>` subcommand
- `register_hook(event, callback)` — plugin hook (CLI + gateway)
- `register_skill(name, path, ...)` — register a bundled skill
- `hermes_home` — `Path` to the active Hermes home
- `config` — loaded config dict
- `get_config(key, default)` — read a config value

Handler signatures:
- Slash command: `handler(raw_args: str, **context) -> str` (context keywords: `source`, `session_id`, `session_key`, `platform`; opt in by name)
- CLI: `handler_fn(args)` returns exit code; `setup_fn(parser)` adds arguments

### Hooks

Valid hook event names live in `hermes_cli/plugins.py::VALID_HOOKS` and grow
across releases. **Always read the installed source** — never hardcode a count
or list. Common hooks: `on_session_start`, `on_session_end`, `pre_tool_call`,
`post_tool_call`, `pre_llm_call`.

Plugin hooks can block (`pre_tool_call`), inject context (`pre_llm_call`), or
continue (`pre_verify`). Callback timeouts: default 30s, hard cap 600s. Policy
hooks (pre_tool_call) fail closed on timeout; others fail open.

### Commands

Commands return a string. The string is displayed to the user. Keep output
concise — hermes-guide's convention is one-line envelopes (`+`/`x`/`~`/`?`).

### Capabilities and the read-only contract

For a read-only plugin (recommended default):
- Omit the `capabilities:` block entirely in `plugin.yaml`.
- Do not mutate config, files, or state.
- Do not call privileged APIs without a concrete need.

`tools/check_no_mutation.py` AST-scans the plugin for mutation patterns and
fails if it finds any. The empty-capabilities convention is enforced by CI.

### Config schema

Declare user-configurable settings under `config_schema:` in `plugin.yaml`.
Hermes merges these into the user's config on install. Types: `bool`, `str`,
`int`, `float`, `list`, `dict`.

### Read-only inspection pattern

Read config via `ctx.get_config()` or `yaml.safe_load()` on the config path.
Read state via `Path(ctx.hermes_home) / "..."`. Never write to these paths.

## Skill authoring

A skill is a directory with a single `SKILL.md`:

```
skills/<name>/
└── SKILL.md
```

### Frontmatter

```yaml
---
name: <name>          # must match directory name
description: "One or two sentences an agent can route on."
version: 1.0.0        # quoted semver string
metadata:
  hermes:
    tags: [hermes, <topic>]
    related_skills: [<other-skill-names>]
---
```

Rules:
- `name` must match the directory name exactly.
- `description` is the only thing a router sees — name the surface and symptom.
- `version` must be a quoted string; any change bumps it (up only).
- `metadata.hermes.tags` and `related_skills` are the current convention.

### Naming conventions

- Diagnostic playbooks: `diagnosing-<surface>` (≤20 chars for new skills)
- Install/config guides: `installing-hermes`, `hermes-configuration-guide`
- Others: `<noun>-<verb>` or `<noun>` (e.g., `plugin-authoring`, `hermes-post-update`)

### Content rules

- Lead with "Use when…" in the description.
- Use `##` headers for sections; imperative tone; no emoji in prose.
- Ground every fact in the installed Hermes source — cite `hermes_cli/`,
  `agent/`, `hermes_constants.py` with commit SHAs.
- Do not hardcode Hermes internals (hook event names, venv paths, CLI output).
- End every diagnosis with a concrete action: a `hermes <subcommand>` or a
  specific file + field edit, followed by a `/reload-*` or restart.

### Provenance footer

The final non-empty line must be dated and upstream-anchored:

```
*Facts (re-)verified YYYY-MM-DD against upstream source at `<rev>` (<files/symbols>).*
```

- Refresh the date when you re-check facts against upstream.
- Leave it alone when you only reworded prose.
- The guard (`check_skill_provenance.py`) requires: final non-empty line, a
  date in `YYYY-MM-DD`, the word "upstream", and a revision reference
  (backticked hex SHA ≥7 chars, or the words `commit`/`baseline`/`main`).

### Version bumps

| Change type | Bump |
|---|---|
| Typo/formatting | patch |
| New content/step | minor |
| Structural rewrite | major |

### Routing (for diagnosing-* skills)

Every new `diagnosing-*` skill needs:
1. A bullet in `hermes-configuration-guide`'s `## Routing` section.
2. An entry in the README table.
3. An entry in `.github/ISSUE_TEMPLATE/skill-drift.yml` dropdown.

`render_docs.py --write` refreshes the generated inventory block in AGENTS.md
and README.md automatically.

### Registration

After adding or editing a skill, run:

```bash
python tools/render_docs.py --write
python tools/check_skill_version_bump.py origin/master
python tools/check_skill_provenance.py
python tools/test_skill_counts.py        # CI-tier: README table + issue template parity
```

### Verification

After creating a new plugin or skill:

```bash
# Plugin: verify it loads
hermes plugins list
# Should show your plugin with status "loaded"

# Skill: verify it's discovered
hermes skills list
# Should show your skill from the intended source

# Run the hermetic gates
python tools/check_gates.py
```

Pass: plugin appears in `hermes plugins list` as loaded; skill appears in
`hermes skills list` from the intended source; all 12 hermetic gates pass.

Fail: plugin not listed — check `plugin.yaml` syntax and that the directory is
on the skills/plugins path; skill not found — check the directory name matches
the `name:` frontmatter field and the path is under `skills/`.

### Common pitfalls

- **Untracked skill directory breaks pre-commit.** `git add skills/<name>/`
  before committing — the gates read the working tree and an untracked
  directory fails the count and routing gates.
- **render_docs word-list ceiling.** `_word_num()` in `render_docs.py`
  only spells numbers up to twenty-two. Adding a twenty-third skill
  deliberately requires extending `_WORDS` AND updating the selftest
  (remove the guard that expects `_word_num(23)` to raise). The guard
  exists so a twenty-third skill forces someone to look at the prose
  rather than silently producing "23".
- **README table + issue template parity.** Every shipped skill must
  appear in the README skill table AND the `.github/ISSUE_TEMPLATE/
  skill-drift.yml` dropdown. `tools/test_skill_counts.py` (CI-tier)
  enforces this — run it after adding a skill.
- **Hardcoded hook event names.** The valid set is `VALID_HOOKS` in
  `hermes_cli/plugins.py` and grows across releases. Read the installed source.
- **Hardcoded venv paths.** Use `project_venv_dir()` / `committed_venv()` /
  `project_python()` — never hardcode `venv/` or `.venv/`.
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

*Facts verified 2026-10-31 against upstream source at commit `cedf4a3d78675283fa93e4e6ea2d6212bf414667`: `hermes_cli/plugins.py` (VALID_HOOKS, register_hook, register_command handler contract), `hermes_cli/plugin_command_dispatch.py` (invoke_plugin_command signature), `hermes_cli/plugins_manifest.py` (requires_hermes), `hermes_cli/skills_hub.py` (tap install), `tools/render_docs.py` (_word_num ceiling, selftest guard), `tools/test_skill_counts.py` (README table + issue template parity), and the official docs (hermes-agent.nousresearch.com/docs). Plugin manifest fields and skill frontmatter verified against this repo's own `plugin.yaml` and `skills/*/SKILL.md`. Re-verify before reuse.*
