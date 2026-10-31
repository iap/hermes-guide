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
- `python_dependencies` — pip-installable deps; Hermes **validates and
  surfaces** them (never auto-installs). Authors must install deps into the
  plugin venv themselves (e.g. `pip install -r requirements.txt` in the
  plugin directory).

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


# --- Define these callbacks above register() or import them ---
# def _handle_command(raw_args: str, **context) -> str: ...
# def _setup_cli(parser): ...
# def _run_cli(args) -> int: ...
# def _on_start(**context): ...
```

`ctx` exposes:
- `register_command(name, handler, description)` — slash command (CLI + gateway)
- `register_cli_command(name, help, setup_fn, handler_fn)` — `hermes <name>` subcommand
- `register_hook(event, callback)` — plugin hook (CLI + gateway)
- `register_skill(name, path, ...)` — register a bundled skill
- `get_config(key, default)` — read a plugin-relative config value (requires a
  key; there is no bare `get_config()` or `ctx.config` attribute)
- There is no `ctx.hermes_home` attribute; use `hermes_constants.get_hermes_home()`
  (imported from `hermes_constants`) for the active Hermes home path

Handler signatures:
- Slash command: at `cedf4a3d` (baseline), handlers receive only `raw_args: str`. Context keywords (`source`, `session_id`, `session_key`, `platform`) were introduced in `06e8c5bc` — use `**context` to opt in, but only on Hermes versions that include that commit.
- CLI: `handler_fn(args)` returns exit code; `setup_fn(parser)` adds arguments

### Hooks

Valid hook event names live in `hermes_cli/plugins.py::VALID_HOOKS` and grow
across releases. **Always read the installed source** — never hardcode a count
or list. Common hooks: `on_session_start`, `on_session_end`, `pre_tool_call`,
`post_tool_call`, `pre_llm_call`.

Plugin hooks can block (`pre_tool_call`), inject context (`pre_llm_call`), or
continue (`pre_verify`). Callback timeouts: default 30s, hard cap 600s, but only for an **allowlist**
of bounded hooks (e.g. `pre_tool_call`, `post_tool_call`, `pre_llm_call`).
Hooks like `on_session_finalize` run synchronously without this timeout —
authors relying on a universal timeout can leave a session blocked. Policy
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
Hermes uses `config_schema` to report setting mismatches (it does **not**
write defaults into the user's config on install). Authors must supply
defaults when reading settings, e.g. `ctx.get_config("proactive", False)`.
Types: `bool`, `str`,
`int`, `float`, `list`, `dict`.

### Read-only inspection pattern

Read config via `ctx.get_config("key", default)` (requires a key) or
`yaml.safe_load()` on the config path (`hermes_constants.get_hermes_home() /
"config.yaml"`). Read state via `hermes_constants.get_hermes_home() / "..."`.
Never write to these paths.
