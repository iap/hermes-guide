---
name: diagnosing-bot-mode
description: Diagnose Hermes Bot Mode issues — bots not appearing, profile conflicts, bot-to-bot messaging failures, model/memory/skill routing per bot, and gateway connectivity.
version: 1.0.1
metadata:
  hermes:
    tags: [hermes, bot-mode, troubleshooting]
    related_skills: [hermes-configuration-guide, diagnosing-gateway]
---

# Diagnosing Bot Mode

Goal: reduce any Bot Mode problem to one concrete fix — a profile config.yaml field, a gateway restart, or an enable toggle. Bot Mode creates named bots (profiles) with their own model, memory, skills, and gateway routing.

## 1. Configuration shape

```yaml
# ~/.hermes/profiles/<bot-name>/config.yaml  (operational settings)
model:
  default: claude-sonnet-4.5
  provider: anthropic
memory:
  provider: built-in           # built-in | mem0 | honcho
ui_meta:
  hermes-bots: {}              # marks this profile as a bot
```

> [!IMPORTANT]
> `profile.yaml` (`~/.hermes/profiles/<bot-name>/profile.yaml`) is **metadata only** — description and display name. Operational settings (model, memory, skills) belong in the profile's `config.yaml`. Editing `profile.yaml` for model/memory changes has no effect.

## 2. How to inspect

- `hermes profile list` — list all profiles (bots are profiles marked with `ui_meta.hermes-bots`)
- `hermes gateway status` — verify the gateway is running (bots require it)
- `hermes config path` — locate the active config.yaml
- `~/.hermes/profiles/<bot-name>/config.yaml` — per-bot operational config
- `hermes logs --follow` — watch bot activity in real-time

## 3. Pitfalls (symptom → cause → fix)

1. **Bot not appearing in Desktop Bots tab** — (a) profile config.yaml missing or invalid; (b) `ui_meta.hermes-bots` missing from profile config; (c) gateway not running; (d) Desktop UI bug (collapse button clicked — see issue #101535). → Validate profile config.yaml syntax; add `ui_meta.hermes-bots: {}` to the bot's config.yaml; restart gateway; reinstall Desktop if UI bug suspected.
2. **Bot responds but uses wrong model** — `model.default` in profile config.yaml is empty or invalid, or the provider is not configured. → Set `model.default` to a valid model string and `model.provider`; verify provider config in the default profile.
3. **Bot-to-bot messaging fails** — (a) both bots on different machines without peer setup; (b) bot profiles don't exist or aren't running; (c) target bot's gateway not reachable. → Use `hermes peer` for cross-machine bot communication; verify both bots' profiles exist (`hermes profile list`); ensure both gateways are running.
4. **Bot memory not persisting** — `memory.provider` in profile config.yaml misconfigured or external provider (Honcho/Mem0) not running. → Check `memory.provider` in the bot's config.yaml; verify external provider is installed and reachable.
5. **Bot skills not loading** — skill names don't match installed skills, or skills not installed for that profile. → Run `hermes skills list -p <bot-name>`; install missing skills for the profile; verify names match.
6. **Bot cron jobs not firing** — cron expression invalid, deliver target not configured, or scheduler not running. → Validate cron syntax; check `hermes cron status`; verify deliver target (telegram/discord/etc.) is configured.
7. **"Profile already exists" error** — duplicate profile name. → Use unique names; check `~/.hermes/profiles/` for conflicts.
8. **Bot spawns duplicate backends** — known issue in v0.21.0-v0.21.1 (fixed in v0.21.2). → Upgrade Hermes to v0.21.2+.

## 4. Localization workflow

1. `hermes gateway status` — confirm gateway is running (bots require it).
2. `hermes profile list` — verify the bot profile exists and is running.
3. Check `~/.hermes/profiles/<bot-name>/config.yaml` — validate YAML, check `model`, `memory`, `ui_meta.hermes-bots`.
4. `hermes logs --follow` — watch for bot activity and errors.
5. Match the failure: not appearing → pitfall 1; wrong model → pitfall 2; messaging fails → pitfall 3.
6. Apply the fix, restart gateway (`hermes gateway restart`), and verify via `hermes profile list`.

## 5. Cross-references

- `hermes-configuration-guide` — for $HERMES_HOME resolution and config.yaml structure
- `diagnosing-gateway` — for gateway connectivity and platform allowlist issues
- `diagnosing-cron` — for routine/cron job scheduling problems
- `diagnosing-memory` — for memory provider configuration

*Facts re-verified 2026-09-21 against upstream source at commit `cedf4a3d78675283fa93e4e6ea2d6212bf414667`: `hermes_cli/bot_mode.py`, `hermes_cli/profiles.py`; plus the official docs (hermes-agent.nousresearch.com/docs/user-guide/bot-mode). Re-verify before reuse.*
