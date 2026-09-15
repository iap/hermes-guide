---
name: hermes-configuration-guide
description: Map of Hermes Agent configuration — where MCP servers, skills, commands, hooks, and plugins live, and which diagnostic skill to load when something does not work.
version: 1.2.1
metadata:
  hermes:
    tags: [hermes, configuration, troubleshooting]
    related_skills: [installing-hermes, diagnosing-mcp, diagnosing-skills, diagnosing-commands, diagnosing-hooks, diagnosing-plugins, diagnosing-path, diagnosing-cli-tui, diagnosing-memory, diagnosing-desktop, diagnosing-providers, hermes-agent]
---

# Hermes Configuration Guide

This skill is the **map**: where each Hermes extension surface is configured, how conflicts resolve, and which `diagnosing-*` skill to load when something breaks. Hermes is configured in **YAML** (`config.yaml`), not JSON — if you are migrating from Claude Code or Cursor, `mcpServers` becomes `mcp_servers:` and `hermes import-agent claude-code` migrates servers, skills, and instructions automatically.

## Step 0 — Resolve $HERMES_HOME first

Never guess where Hermes reads its files. The home directory differs by platform and profile:

- **POSIX / WSL**: `~/.hermes`
- **Native Windows**: `%LOCALAPPDATA%\hermes` (e.g. `C:\Users\<you>\AppData\Local\hermes`) — `~/.hermes` may also exist there and is NOT the active home
- **Named profiles**: each profile has its own home; `hermes -p <profile> ...` and `HERMES_HOME=<dir>` override it
- **Two different things are called "platform" in this guide set**: the **operating system** (POSIX vs Windows — as above, and the `platforms:` frontmatter field in skills) and the **chat/messaging platform** (Telegram, Discord, Slack — in slash-command permissions and plugin `platforms/` sub-categories). Check which one a sentence means before acting.
- **Ground truth**: run `hermes config path` — it prints the active config file's full path. `hermes config show` dumps the merged config; `hermes config set <section.key> <value>` edits it safely.

## The five surfaces at a glance

| Surface | Configured in | Inspect with |
|---|---|---|
| **MCP servers** | `$HERMES_HOME/config.yaml` → `mcp_servers:` (stdio: `command`/`args`/`env`; http: `url`/`headers`) | `hermes mcp`, `/reload-mcp` |
| **Skills** | `$HERMES_HOME/skills/<category>/<name>/SKILL.md` (source of truth); extra dirs via `skills.external_dirs`; hub installs via `hermes skills` | `hermes skills list`, `/skills list`, `/reload-skills` |
| **Slash commands** | No standalone command files. Built-in registry + every installed skill (`/<skill-name>`) + skill bundles (`$HERMES_HOME/skill-bundles/*.yaml`) + plugin commands | Type `/` for autocomplete, `hermes bundles list` |
| **Hooks** | Four systems: gateway hooks (`$HERMES_HOME/hooks/<name>/HOOK.yaml` + `handler.py`, gateway-only); plugin hooks (`ctx.register_hook()`); shell hooks (`hooks:` block in config.yaml); outbound webhooks (`hooks.outbound:`) | `hermes hooks list / test / doctor` |
| **Plugins** | `$HERMES_HOME/plugins/<name>/` with `plugin.yaml` + `register(ctx)`; **opt-in** via `plugins.enabled` | `hermes plugins`, `/plugins` |

## Instruction files (a separate system)

- `SOUL.md` (`$HERMES_HOME/SOUL.md`) — agent persona, always loaded as prompt slot #1. You edit it.
- `USER.md` / `MEMORY.md` (`$HERMES_HOME/memories/`) — agent-written memory, injected as a **frozen snapshot at session start**; mid-session saves appear only next session. This is the usual cause of "it forgot what I just told it."
- Project context — each source is looked up **differently**, and the difference decides where you must put the file (`agent/prompt_builder.py:1588`, verified):

| Source | Where it is read from |
|---|---|
| `.hermes.md` / `HERMES.md` | walked from cwd **up to the git root**; cwd only when there is no git root (`agent/coding_context.py::_find_hermes_md` — so a file planted in a parent like `/tmp` cannot be picked up) |
| `AGENTS.md` (`AGENTS.override.md` wins, `agents.md` accepted) | **merged directory chain, git root → cwd** — every directory's file is injected, deeper wins |
| `CLAUDE.md` | **cwd only** |
| `.cursorrules` (+ `.cursor/rules/*.mdc`) | **cwd only**, concatenated |

The practical consequence: `CLAUDE.md`/`.cursorrules` at a repository root are **ignored** when you launch from a subdirectory, while `AGENTS.md` is not. Exactly one source wins per session, first match in the order above.

## Key $HERMES_HOME inventory

`config.yaml` (main config + `platforms:`/`gateway:` messaging settings) · `.env` (secrets; documented vars override config) · `gateway.json` (legacy gateway fallback) · `skills/` · `skill-bundles/` · `hooks/` (gateway hooks) · `agent-hooks/` (shell-hook script convention) · `plugins/` · `shell-hooks-allowlist.json` (shell-hook consent) · `mcp-tokens/` (OAuth caches) · `logs/` · `state.db` (sessions).

## Orphaned & legacy settings

Config keys that Hermes **silently stopped reading** are inert: they look meaningful in `config.yaml`, but no code consumes them — and their presence proves nothing. **Temporary:** the suspected key may stay while you confirm it is inert — but do not treat its presence as evidence that Hermes reads it, and do not leave it in place during an active diagnosis (an inert `disabled: true` on an MCP server reads as "server off" while the loader keeps it **on**). **Permanent:** move to the live replacement below and delete the dead key so it misleads neither the current investigation nor the next reader. Before trusting a key, verify it against the installed source: search for actual readers (e.g. `grep -rn 'get("profile")' <hermes-agent-source>`), and check whether it appears in the shipped `cli-config.yaml.example` (the documented schema). Known cases, last checked against the installed source at commit `8d3745a99b` (present in history; 2026-09-04). **Re-check before quoting a key as orphaned** — the honest test is a reader grep plus the shipped `cli-config.yaml.example`; a key absent from that example and with no reader is inert, but a key that has gained a reader since this list was written is live again:

| Setting | Status | Live replacement |
|---|---|---|
| `profile:` block in `config.yaml` (e.g. `profile.description`) | **Orphaned** — written by an older scheme, zero readers today | Per-profile `profile.yaml` metadata: `hermes profile describe <name> --text "…"` |
| `mcpServers` (top-level, Claude-Code-style paste) | Silently not read | `mcp_servers:` |
| `disabled:` inside an MCP server entry | Silently ignored (server stays enabled) — the loader reads `enabled` only (`hermes_cli/mcp_config.py`) | `enabled: false` |

Notes:

- `hermes migrate` covers **retired models and deprecated settings** (currently the xAI migration); the sibling `hermes config migrate` applies new config options. Neither detects arbitrary orphaned keys — audit for those by hand.
- Profile descriptions reach a model in only two contexts: kanban task routing (the decomposer's profile roster) and dispatch guidance. Normal sessions and `hermes guide`/`hermes doctor` never see them.
- When a diagnosis behaves as if part of `config.yaml` is invisible, audit for orphans before suspecting the model: inert keys produce exactly that symptom.

## Routing — when something is wrong

- MCP server not connecting, tools missing, OAuth failing → **`diagnosing-mcp`**
- A skill not discovered, not triggering, shadowed, or stuck "user-modified" → **`diagnosing-skills`**
- A `/command` missing, wrong, or overridden → **`diagnosing-commands`**
- A hook not firing, blocked consent, or behaving unexpectedly → **`diagnosing-hooks`**
- A plugin not loading, not enabled, or missing capabilities → **`diagnosing-plugins`**
- Auth/API failures on hub installs (`Could not fetch from any source`, GitHub 401, rate-limit 403) → **`diagnosing-auth`**
- Memory not persisting ("it forgot"), an external memory provider silently unavailable, or `MEMORY.md`/`USER.md` errors → **`diagnosing-memory`**
- Desktop app build/launch failures, wrong backend, or blank window → **`diagnosing-desktop`**; terminal/TUI rendering issues are `diagnosing-cli-tui`, not desktop
- Model provider issues — custom endpoints flooding the picker with hundreds of models, `discover_models` misbehaving, persisted catalogs bloating `config.yaml`, or provider/auth failures → **`diagnosing-providers`**
- Script/path/venv problems (wrong interpreter, `venv/bin/python` missing, the dual `.venv`/`venv` layout) → **`diagnosing-path`**
- Terminal/TUI issues on **native Windows** (misrendering, themes, indicators, launch failures) → **`diagnosing-cli-tui`**; on POSIX/WSL there is no dedicated skill yet — start with `hermes doctor` and the `display:` block of `config.yaml`

Every diagnosis should end in a concrete action: a `hermes <subcommand>` command or a specific file + field edit, then a restart or `/reload-*` to apply.

---

*Facts re-verified 2026-09-14 against upstream source at current main: the cited commit `8d3745a99b` exists in history (2026-09-04); the `profile:` block has no config reader (the `profile` hits in the tree are session records, not this block); an MCP entry's `disabled:` key is unread — `enabled` is the control (`hermes_cli/mcp_config.py`); project-context discovery is `.hermes.md`/`HERMES.md` → `AGENTS.md` → `CLAUDE.md` → `.cursorrules`, cwd-upward with a git-root stop (`agent/coding_context.py`, `agent/prompt_builder.py`); `mcp-tokens/`, `profile describe`, and `import-agent` all exist. Re-verify before reuse.*

---

*Re-verified 2026-09-14 (corrective pass) against upstream source at commit `46a0daee58abbc1b07f84f505a5ba90f1958295c`: the per-file project-context lookup table comes from `agent/prompt_builder.py:1588` and `agent/coding_context.py::_find_hermes_md`.*
