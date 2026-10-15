---
name: diagnosing-gateway
description: Diagnose Hermes gateway and messaging platform issues — bot not responding, platform allowlist confusion, token validation, gateway connectivity, and multi-platform setup.
version: 1.1.7
metadata:
  hermes:
    tags: [hermes, gateway, messaging, troubleshooting]
    related_skills: [hermes-configuration-guide, diagnosing-auth, diagnosing-bot-mode]
---

# Diagnosing Gateway & Messaging

Goal: reduce any messaging problem to one concrete fix — a gateway restart, a token refresh, or an allowlist entry. The gateway connects Hermes to 20+ messaging platforms.

## 1. Configuration shape

Platform config lives under `gateway.platforms.<name>` in `config.yaml`, but **each platform has its own schema** — there is no universal `token`/`allowlist`/`enabled` shape. Telegram uses polling/webhook with `token`; Discord uses `bot_token` and intents; Matrix uses `homeserver` + `access_token`; WhatsApp uses QR pairing. Always run `hermes gateway setup` for the target platform to see the actual fields.

> Every `$HERMES_HOME/...` path below means the resolved home (`hermes config path`; see config-guide Step 0) — the variable is an override and may be unset, in which case a bare `$HERMES_HOME/logs/...` expands to `/logs/...`.

> [!WARNING]
> Do not copy-paste a `gateway.platforms.<name>` block from one platform to another. Applying a Telegram-shaped block to Discord (or vice versa) silently ignores credentials and the platform will not connect.

## 2. How to inspect

- `hermes gateway status` — gateway process status, platform connections
- `hermes gateway status --deep --full` — detailed diagnostics (macOS: use full PATH)
- `hermes gateway start` / `hermes gateway restart` — manage gateway lifecycle
- `hermes gateway setup` — interactive platform setup wizard (shows actual fields per platform)
- `hermes logs --follow` — watch gateway logs in real-time
- `$HERMES_HOME/logs/gateway.log` — gateway log file (resolve the home first: `hermes config path`)

## 2b. Connectors (named app accounts)

Separately from platforms, Hermes manages named third-party accounts via Nous Portal (`hermes connectors list` — every connector and its state; `accounts [--all]`, `connect` (browser flow), `rename`, `disconnect`). A bot failing only on services backed by a connector (rather than all platforms) points here, not at gateway connectivity: check `hermes connectors list` for state, `accounts` (with `--all` for retired ones) for the account, `connect` to re-link, `rename`/`disconnect` to tidy up.

## 3. Pitfalls (symptom → cause → fix)

1. **Bot not responding to messages** — (a) gateway not running; (b) bot not authorized; (c) user not in allowlist; (d) token expired. → Run `hermes gateway status`; start gateway (`hermes gateway start`); check allowlist in config.yaml; verify token with `hermes gateway setup`.
2. **Messages not delivering** — (a) invalid bot token; (b) platform API down; (c) network issue. → Verify token with `hermes gateway setup`; check platform status page; test network connectivity.
3. **Allowlist confusion — who can talk to the bot?** — (a) user not on platform-specific allowlist; (b) wrong access mode (pairing vs allowlist); (c) first DM already claimed by another user. → Run `hermes gateway setup` to see the actual access-mode options; check `gateway.platforms.<name>` in config.yaml for the platform-specific allowlist field.
4. **Gateway crashes on start** — (a) invalid config.yaml; (b) port already in use; (c) missing dependencies. → Check `$HERMES_HOME/logs/gateway.log`; verify config.yaml syntax; check for port conflicts (`lsof -i :<port>`).
5. **Platform shows as disconnected** — (a) token expired or revoked; (b) platform API changed; (c) network/firewall blocking. → Re-authenticate via `hermes gateway setup`; check platform API status; verify network/firewall rules.
6. **Bot responds twice** — (a) duplicate gateway processes; (b) platform retry on timeout. → Check `launchctl list | grep -i hermes` (macOS); kill duplicate processes; check platform retry settings.
7. **Voice messages not transcribing on Telegram** — ffmpeg unavailable. → See `diagnosing-voice` for the ffmpeg restore (`hermes pm install ffmpeg` on a PM-era install, system package manager on an older checkout); restart the gateway afterward.
8. **Gateway not persisting across reboots** — (a) no launchd/systemd service; (b) gateway not set to auto-start. → Create launchd plist (macOS) or systemd service (Linux) — on Windows use `hermes gateway install` (schtasks ONLOGON; see `diagnosing-cli-tui`); enable auto-start.

## 4. Localization workflow

1. `hermes gateway status` — verify gateway is running and platforms connected.
2. `hermes gateway status --deep --full` — detailed diagnostics.
3. Check `tail -50 "$HERMES_HOME/logs/gateway.log"` — recent errors.
4. Check config.yaml `gateway.platforms.<name>` — verify token, allowlist, enabled.
5. Match the failure: not responding → pitfall 1; not delivering → pitfall 2; allowlist → pitfall 3.
6. Apply the fix, `hermes gateway restart`, and verify with `hermes gateway status`.

## 5. Cross-references

- `hermes-configuration-guide` — for $HERMES_HOME resolution and config.yaml structure
- `diagnosing-auth` — for token validation and OAuth flows
- `diagnosing-bot-mode` — for bot-specific gateway issues
- `diagnosing-voice` — for voice message transcription issues
- `diagnosing-host-pressure` — when several platforms fail at once or adapters are discarded after a load timeout; rule out host pressure before editing tokens or allowlists

## Report

This skill diagnoses gateway and messaging platform issues — bot not responding, platform allowlist confusion, token validation, gateway connectivity, and multi-platform setup. When you run the diagnostic workflow, present findings in the standard format below.

### Summary
Your Telegram bot is not responding to messages because the gateway is not running. The bot token is valid, but the gateway process that polls Telegram for updates is stopped.

### Findings
| Severity | What | Evidence |
|---|---|---|
| HIGH | Gateway process is not running | `hermes gateway status` shows `gateway: not running`; no platform connections listed |
| MEDIUM | Bot token may be expired | `hermes gateway status --deep` shows `telegram: token validation failed` |

### Recommended Fix
Run `hermes gateway start` to start the gateway, then verify with `hermes gateway status`. If the token is expired, run `hermes gateway setup` to re-authenticate, then `hermes gateway restart`.

### References
- `$HERMES_HOME/logs/gateway.log` — gateway log file
- `hermes_cli/gateway.py` — gateway CLI commands
- `hermes_cli/platforms/` — platform-specific adapters

*Facts re-verified 2026-09-28 against upstream source at commit `cedf4a3d78675283fa93e4e6ea2d6212bf414667`: `hermes_cli/gateway.py`, `hermes_cli/platforms/`; plus the official docs (hermes-agent.nousresearch.com/docs/user-guide/messaging/). Connectors section verified 2026-10-15 against the installed CLI (`hermes connectors`: list/accounts/connect/rename/disconnect). Re-verify before reuse.*
