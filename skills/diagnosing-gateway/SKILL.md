---
name: diagnosing-gateway
description: Diagnose Hermes gateway and messaging platform issues — bot not responding, platform allowlist confusion, token validation, gateway connectivity, and multi-platform setup.
version: 1.0.0
metadata:
  hermes:
    tags: [hermes, gateway, messaging, troubleshooting]
    related_skills: [hermes-configuration-guide, diagnosing-auth, diagnosing-bot-mode]
---

# Diagnosing Gateway & Messaging

Goal: reduce any messaging problem to one concrete fix — a gateway restart, a token refresh, or an allowlist entry. The gateway connects Hermes to 20+ messaging platforms.

## 1. Configuration shape

```yaml
# ~/.hermes/config.yaml
gateway:
  platforms:
    telegram:
      enabled: true
      token: "${TELEGRAM_BOT_TOKEN}"
      allowlist: ["123456789"]      # user IDs allowed to interact
    discord:
      enabled: true
      token: "${DISCORD_BOT_TOKEN}"
      allowlist: []
    slack:
      enabled: false
      token: "${SLACK_BOT_TOKEN}"
```

Platform modes: `allowlist` (only listed user IDs), `dm_pairing` (first DM claims access), `open` (anyone can interact — not recommended for production).

## 2. How to inspect

- `hermes gateway status` — gateway process status, platform connections
- `hermes gateway status --deep --full` — detailed diagnostics (macOS: use full PATH)
- `hermes gateway start` / `hermes gateway restart` — manage gateway lifecycle
- `hermes gateway setup` — interactive platform setup wizard
- `hermes logs --follow` — watch gateway logs in real-time
- `~/.hermes/logs/gateway.log` — gateway log file
- `cat ~/.hermes/logs/gateway.log | tail -50` — recent gateway errors

## 3. Pitfalls (symptom → cause → fix)

1. **Bot not responding to messages** — (a) gateway not running; (b) bot not authorized; (c) user not in allowlist; (d) token expired. → Run `hermes gateway status`; start gateway (`hermes gateway start`); check allowlist in config.yaml; verify token with `hermes gateway setup`.
2. **Messages not delivering** — (a) invalid bot token; (b) platform API down; (c) network issue. → Verify token with `hermes gateway setup`; check platform status page; test network connectivity.
3. **Allowlist confusion — who can talk to the bot?** — (a) user ID not in allowlist; (b) wrong mode configured; (c) DM pairing claimed by another user. → Check `gateway.platforms.<name>.allowlist` in config.yaml; verify mode (allowlist/dm_pairing/open); for DM pairing, first user to message claims access.
4. **Gateway crashes on start** — (a) invalid config.yaml; (b) port already in use; (c) missing dependencies. → Check `~/.hermes/logs/gateway.log`; verify config.yaml syntax; check for port conflicts (`lsof -i :<port>`).
5. **Platform shows as disconnected** — (a) token expired or revoked; (b) platform API changed; (c) network/firewall blocking. → Re-authenticate via `hermes gateway setup`; check platform API status; verify network/firewall rules.
6. **Bot responds twice** — (a) duplicate gateway processes; (b) platform retry on timeout. → Check `launchctl list | grep -i hermes` (macOS); kill duplicate processes; check platform retry settings.
7. **Voice messages not transcribing on Telegram** — ffmpeg not installed. → Install ffmpeg (`sudo apt install ffmpeg` / `brew install ffmpeg`); restart gateway.
8. **Gateway not persisting across reboots** — (a) no launchd/systemd service; (b) gateway not set to auto-start. → Create launchd plist (macOS) or systemd service (Linux); enable auto-start.

## 4. Localization workflow

1. `hermes gateway status` — verify gateway is running and platforms connected.
2. `hermes gateway status --deep --full` — detailed diagnostics.
3. Check `~/.hermes/logs/gateway.log | tail -50` — recent errors.
4. Check config.yaml `gateway.platforms.<name>` — verify token, allowlist, enabled.
5. Match the failure: not responding → pitfall 1; not delivering → pitfall 2; allowlist → pitfall 3.
6. Apply the fix, `hermes gateway restart`, and verify with `hermes gateway status`.

## 5. Cross-references

- `hermes-configuration-guide` — for $HERMES_HOME resolution and config.yaml structure
- `diagnosing-auth` — for token validation and OAuth flows
- `diagnosing-bot-mode` — for bot-specific gateway issues
- `diagnosing-voice` — for voice message transcription issues

*Facts re-verified 2026-09-21 against upstream source at commit `cedf4a3d78675283fa93e4e6ea2d6212bf414667`: `hermes_cli/gateway.py`, `hermes_cli/platforms/`; plus the official docs (hermes-agent.nousresearch.com/docs/user-guide/messaging/). Re-verify before reuse.*
