---
name: diagnosing-bot-mode
description: Diagnose Hermes Bot Mode issues — bots not appearing, profile conflicts, bot-to-bot messaging failures, model/memory/skill routing per bot, and gateway connectivity.
version: 1.0.0
metadata:
  hermes:
    tags: [hermes, bot-mode, troubleshooting]
    related_skills: [hermes-configuration-guide, diagnosing-gateway]
---

# Diagnosing Bot Mode

Goal: reduce any Bot Mode problem to one concrete fix — a profile.yaml field, a gateway restart, or a config.yaml setting. Bot Mode creates named bots with their own model, memory, skills, routines, and chats.

## 1. Configuration shape

```yaml
# ~/.hermes/profiles/<bot-name>/profile.yaml
name: research-bot
model: claude-sonnet-4.5
memory:
  provider: mem0
skills:
  - diagnosing-mcp
  - diagnosing-hooks
routines:
  - cron: "0 9 * * 1-5"
    prompt: "Summarize yesterday's commits"
    deliver: telegram
```

Key fields: `name` (unique identifier), `model` (provider/model string), `memory.provider` (built-in or external), `skills` (list of skill names), `routines` (scheduled tasks with cron/prompt/deliver).

## 2. How to inspect

- `hermes bots list` — show all configured bots and their status
- `hermes gateway status` — verify the gateway is running (bots require it)
- `hermes config path` — locate config.yaml for global bot settings
- `~/.hermes/profiles/<bot-name>/profile.yaml` — per-bot configuration
- `hermes logs --follow` — watch bot activity in real-time

## 3. Pitfalls (symptom → cause → fix)

1. **Bot not appearing in Desktop Bots tab** — (a) profile.yaml missing or invalid YAML; (b) bot not enabled in config.yaml `bots.enabled`; (c) gateway not running; (d) Desktop UI bug (collapse button clicked — see issue #101535). → Validate profile.yaml syntax; check `bots.enabled` in config.yaml; restart gateway; reinstall Desktop if UI bug suspected.
2. **Bot responds but uses wrong model** — `model` field in profile.yaml is empty or invalid, or the provider is not configured. → Set `model` to a valid `provider/model` string; verify provider config.
3. **Bot-to-bot messaging fails** — (a) both bots not in same chat; (b) `ui_meta.hermes-bots: {}` missing from profile.yaml (marks the install as a bot); (c) bot names collide across profiles. → Add `ui_meta.hermes-bots: {}` to profile.yaml; ensure unique bot names; use `@bot-name` mentions.
4. **Bot memory not persisting** — `memory.provider` misconfigured or external provider (Honcho/Mem0) not running. → Check provider config; verify external provider is installed and reachable.
5. **Bot skills not loading** — skill names in profile.yaml don't match installed skills, or skills not installed via tap. → Run `hermes skills list`; install missing skills; verify names match.
6. **Bot routines not firing** — cron expression invalid, deliver target not configured, or scheduler not running. → Validate cron syntax; check `hermes cron status`; verify deliver target (telegram/discord/etc.) is configured.
7. **"Profile already exists" error** — duplicate profile name across different sources. → Use unique names; check `~/.hermes/profiles/` for conflicts.
8. **Bot spawns duplicate backends** — known issue in v0.21.0-v0.21.1 (fixed in v0.21.2). → Upgrade Hermes to v0.21.2+.

## 4. Localization workflow

1. `hermes gateway status` — confirm gateway is running (bots require it).
2. `hermes bots list` — verify the bot appears and is enabled.
3. Check `~/.hermes/profiles/<bot-name>/profile.yaml` — validate YAML, check model/memory/skills fields.
4. `hermes logs --follow` — watch for bot activity and errors.
5. Match the failure: not appearing → pitfall 1; wrong model → pitfall 2; messaging fails → pitfall 3.
6. Apply the fix, restart gateway (`hermes gateway restart`), and verify in Desktop or via `hermes bots list`.

## 5. Cross-references

- `hermes-configuration-guide` — for $HERMES_HOME resolution and config.yaml structure
- `diagnosing-gateway` — for gateway connectivity and platform allowlist issues
- `diagnosing-cron` — for routine/cron job scheduling problems
- `diagnosing-memory` — for memory provider configuration

*Facts re-verified 2026-09-21 against upstream source at commit `cedf4a3d78675283fa93e4e6ea2d6212bf414667`: `hermes_cli/bot_mode.py`, `hermes_cli/profiles.py`; plus the official docs (hermes-agent.nousresearch.com/docs/user-guide/bot-mode). Re-verify before reuse.*
