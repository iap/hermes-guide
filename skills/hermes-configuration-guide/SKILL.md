---
name: hermes-configuration-guide
description: Map of Hermes Agent configuration â€” where MCP servers, skills, commands, hooks, and plugins live, and which diagnostic skill to load when something does not work.
version: 1.3.3
metadata:
  hermes:
    tags: [hermes, configuration, troubleshooting]
    related_skills: [installing-hermes, diagnosing-mcp, diagnosing-skills, diagnosing-commands, diagnosing-hooks, diagnosing-plugins, diagnosing-path, diagnosing-cli-tui, diagnosing-memory, diagnosing-desktop, diagnosing-providers, diagnosing-bot-mode, diagnosing-browser, diagnosing-cron, diagnosing-gateway, diagnosing-voice]
---

# Hermes Configuration Guide

This skill is the **map**: where each Hermes extension surface is configured, how conflicts resolve, and which `diagnosing-*` skill to load when something breaks. Hermes is configured in **YAML** (`config.yaml`), not JSON â€” if you are migrating from Claude Code or Cursor, `mcpServers` becomes `mcp_servers:` and `hermes import-agent claude-code` migrates servers, skills, and instructions automatically.

## Step 0 â€” Resolve $HERMES_HOME first

Never guess where Hermes reads its files. The home directory differs by platform and profile:

- **POSIX / WSL**: `~/.hermes`
- **Native Windows**: `%LOCALAPPDATA%\hermes` (e.g. `C:\Users\<you>\AppData\Local\hermes`) â€” `~/.hermes` may also exist there and is NOT the active home
- **Named profiles**: each profile has its own home; `hermes -p <profile> ...` and `HERMES_HOME=<dir>` override it
- **Two different things are called "platform" in this guide set**: the **operating system** (POSIX vs Windows â€” as above, and the `platforms:` frontmatter field in skills) and the **chat/messaging platform** (Telegram, Discord, Slack â€” in slash-command permissions and plugin `platforms/` sub-categories). Check which one a sentence means before acting.
- **Ground truth**: run `hermes config path` â€” it prints the active config file's full path. `hermes config show` dumps the merged config; `hermes config set <section.key> <value>` edits it safely.

## The five surfaces at a glance

| Surface | Configured in | Inspect with |
|---|---|---|
| **MCP servers** | `$HERMES_HOME/config.yaml` â†’ `mcp_servers:` (stdio: `command`/`args`/`env`; http: `url`/`headers`) | `hermes mcp`, `/reload-mcp` |
| **Skills** | `$HERMES_HOME/skills/<category>/<name>/SKILL.md` (source of truth); extra dirs via `skills.external_dirs`; hub installs via `hermes skills` | `hermes skills list`, `/skills list`, `/reload-skills` |
| **Slash commands** | No standalone command files. Built-in registry + every installed skill (`/<skill-name>`) + skill bundles (`$HERMES_HOME/skill-bundles/*.yaml`) + plugin commands | Type `/` for autocomplete, `hermes bundles list` |
| **Hooks** | Four systems: gateway hooks (`$HERMES_HOME/hooks/<name>/HOOK.yaml` + `handler.py`, gateway-only); plugin hooks (`ctx.register_hook()`); shell hooks (`hooks:` block in config.yaml); outbound webhooks (`hooks.outbound:`) | `hermes hooks list / test / doctor` |
| **Plugins** | `$HERMES_HOME/plugins/<name>/` with `plugin.yaml` + `register(ctx)`; **opt-in** via `plugins.enabled` | `hermes plugins`, `/plugins` |

## Instruction files (a separate system)

- `SOUL.md` (`$HERMES_HOME/SOUL.md`) â€” agent persona, always loaded as prompt slot #1. You edit it.
- `USER.md` / `MEMORY.md` (`$HERMES_HOME/memories/`) â€” agent-written memory, injected as a **frozen snapshot at session start**; mid-session saves appear only next session. This is the usual cause of "it forgot what I just told it."
- Project context â€” each source is looked up **differently**, and the difference decides where you must put the file (`agent/prompt_builder.py::discover_context_files`, verified):

| Source | Where it is read from |
|---|---|
| `.hermes.md` / `HERMES.md` | walked from cwd **up to the git root**; cwd only when there is no git root (`agent/prompt_builder.py::_find_hermes_md` â€” so a file planted in a parent like `/tmp` cannot be picked up) |
| `AGENTS.md` (`AGENTS.override.md` wins, `agents.md` accepted) | **merged directory chain, git root â†’ cwd** â€” every directory's file is injected, deeper wins |
| `CLAUDE.md` | **cwd only** |
| `.cursorrules` (+ `.cursor/rules/*.mdc`) | **cwd only**, concatenated |

The practical consequence: `CLAUDE.md`/`.cursorrules` at a repository root are **ignored** when you launch from a subdirectory, while `AGENTS.md` is not. Exactly one source wins per session, first match in the order above.

## Key $HERMES_HOME inventory

`config.yaml` (main config + `platforms:`/`gateway:` messaging settings) Â· `.env` (secrets; documented vars override config) Â· `gateway.json` (legacy gateway fallback) Â· `skills/` Â· `skill-bundles/` Â· `hooks/` (gateway hooks) Â· `agent-hooks/` (shell-hook script convention) Â· `plugins/` Â· `shell-hooks-allowlist.json` (shell-hook consent) Â· `mcp-tokens/` (OAuth caches) Â· `logs/` Â· `state.db` (sessions).

## Orphaned & legacy settings

Config keys that Hermes **silently stopped reading** are inert: they look meaningful in `config.yaml`, but no code consumes them â€” and their presence proves nothing. **Temporary:** the suspected key may stay while you confirm it is inert â€” but do not treat its presence as evidence that Hermes reads it, and do not leave it in place during an active diagnosis (an inert `disabled: true` on an MCP server reads as "server off" while the loader keeps it **on**). **Permanent:** move to the live replacement below and delete the dead key so it misleads neither the current investigation nor the next reader. Before trusting a key, verify it against the installed source: search for actual readers (e.g. `grep -rn 'get("profile")' <hermes-agent-source>`), and check whether it appears in the shipped `cli-config.yaml.example` (the documented schema). Known cases, last checked against the installed source at commit `8d3745a99b` (present in history; 2026-09-04). **Re-check before quoting a key as orphaned** â€” the honest test is a reader grep plus the shipped `cli-config.yaml.example`; a key absent from that example and with no reader is inert, but a key that has gained a reader since this list was written is live again:

| Setting | Status | Live replacement |
|---|---|---|
| `profile:` block in `config.yaml` (e.g. `profile.description`) | **Orphaned** â€” written by an older scheme, zero readers today | Per-profile `profile.yaml` metadata: `hermes profile describe <name> --text "â€¦"` |
| `mcpServers` (top-level, Claude-Code-style paste) | Silently not read | `mcp_servers:` |
| `disabled:` inside an MCP server entry | Silently ignored (server stays enabled) â€” the loader reads `enabled` only (`hermes_cli/mcp_config.py`) | `enabled: false` |

Notes:

- `hermes migrate` covers **retired models and deprecated settings** (currently the xAI migration); the sibling `hermes config migrate` applies new config options. Neither detects arbitrary orphaned keys â€” audit for those by hand.
- Profile descriptions reach a model in only two contexts: kanban task routing (the decomposer's profile roster) and dispatch guidance. Normal sessions and `hermes guide`/`hermes doctor` never see them.
- When a diagnosis behaves as if part of `config.yaml` is invisible, audit for orphans before suspecting the model: inert keys produce exactly that symptom.

## Routing â€” when something is wrong
- Vague description ("something is wrong", "it's slow", "it crashed") without naming a subsystem → **`diagnosing-triage`** (meta-skill that routes to the correct diagnostic skill)

- MCP server not connecting, tools missing, OAuth failing â†’ **`diagnosing-mcp`**
- A skill not discovered, not triggering, shadowed, or stuck "user-modified" â†’ **`diagnosing-skills`**
- A `/command` missing, wrong, or overridden â†’ **`diagnosing-commands`**
- A hook not firing, blocked consent, or behaving unexpectedly â†’ **`diagnosing-hooks`**
- A plugin not loading, not enabled, or missing capabilities â†’ **`diagnosing-plugins`**
- Auth/API failures on hub installs (`Could not fetch from any source`, GitHub 401, rate-limit 403) â†’ **`diagnosing-auth`**
- Memory not persisting ("it forgot"), an external memory provider silently unavailable, or `MEMORY.md`/`USER.md` errors â†’ **`diagnosing-memory`**
- Desktop app build/launch failures, wrong backend, or blank window â†’ **`diagnosing-desktop`**; terminal/TUI rendering issues are `diagnosing-cli-tui`, not desktop
- Model provider issues â€” custom endpoints flooding the picker with hundreds of models, `discover_models` misbehaving, persisted catalogs bloating `config.yaml`, or provider/auth failures â†’ **`diagnosing-providers`**
- Script/path/venv problems (wrong interpreter â€” on PM-era installs the launcher runs the PM-store Python, not the shell's; on older checkouts `venv/bin/python` missing or the dual `.venv`/`venv` layout) â†’ **`diagnosing-path`**
- Terminal/TUI issues on **native Windows** (misrendering, themes, indicators, launch failures) â†’ **`diagnosing-cli-tui`**; on POSIX/WSL there is no dedicated skill yet â€” start with `hermes doctor` and the `display:` block of `config.yaml`
- A bot/agent profile not answering, a per-bot `config.yaml` problem, or a routine not firing for a bot â†’ **`diagnosing-bot-mode`**
- Browser automation not connecting, Chrome/CDP version problems, or a missing Playwright â†’ **`diagnosing-browser`**
- A scheduled job not firing, running at the wrong time, or failing to deliver â†’ **`diagnosing-cron`**
- Messaging-platform connectivity, allowlists, or a platform not receiving replies â†’ **`diagnosing-gateway`**
- Several surfaces failing at once, or adapters discarded after a load timeout â€” suspect host resource pressure before per-surface config â†’ **`diagnosing-host-pressure`**
- Voice mode not transcribing or replying, or voice-message handling problems â†’ **`diagnosing-voice`**

### Disambiguation â€” when two skills can claim the same symptom

- **Skill not discovered vs `/command` missing**: if the skill itself is missing from the index, see `diagnosing-skills`; if the skill is present but its `/command` is missing or shadowed, see `diagnosing-commands`.
- **MCP server up but no tools vs provider configured but unavailable**: if the MCP server connects but exposes no tools, see `diagnosing-mcp`; if a model provider is configured but silently unavailable, see `diagnosing-providers`.
- **Plugin not loading vs provider sub-category**: if a plugin is discovered but not enabled, see `diagnosing-plugins`; if a provider sub-category (e.g. `context.engine`, `image_gen.provider`) is misconfigured, see `diagnosing-providers`.
- **Memory not persisting vs provider store unavailable**: if built-in `MEMORY.md`/`USER.md` has errors, see `diagnosing-memory`; if an external memory provider is configured but silently unavailable, see `diagnosing-memory` (it owns external-memory diagnosis).
- **Several faults at once, intermittently**: suspect host resource pressure before per-surface config â€” see `diagnosing-host-pressure`.
- **Launch/UI failure vs command surface vs app build**: if the desktop app fails to launch or shows a blank window, see `diagnosing-desktop`; if the TUI misrenders or shows unreadable indicators on native Windows, see `diagnosing-cli-tui`; if a `/command` is missing or overridden, see `diagnosing-commands`.
- **Which venv/home applies where**: if the wrong Python interpreter is active or the dual-venv layout is confusing, see `diagnosing-path`; if the desktop app's backend resolution is wrong, see `diagnosing-desktop`; if the install itself is broken, see `installing-hermes`.

Every diagnosis should end in a concrete action: a `hermes <subcommand>` command or a specific file + field edit, then a restart or `/reload-*` to apply.

---

*Facts re-verified 2026-09-15 against upstream source at the declared baseline `cedf4a3d78675283fa93e4e6ea2d6212bf414667`: the earlier-cited commit `8d3745a99b` exists in history (2026-09-04); the `profile:` block has no config reader (the `profile` hits in the tree are session records, not this block); an MCP entry's `disabled:` key is unread â€” `enabled` is the control (`hermes_cli/mcp_config.py`); **project context is looked up per source, not by one rule** â€” `.hermes.md`/`HERMES.md` walk cwdâ†’git root (`agent/prompt_builder.py::_find_hermes_md`), `AGENTS.md` is a merged chain git rootâ†’cwd, and `CLAUDE.md`/`.cursorrules` are cwd-only (`agent/prompt_builder.py::discover_context_files`, `_hermes_md_candidates`/`_find_hermes_md`); the former bare line citation for project-context discovery was re-pointed to those symbols at `2f6170bf` (2026-09-22, drift #103); `mcp-tokens/`, `profile describe`, and `import-agent` all exist. Re-verify before reuse.*
