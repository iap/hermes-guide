---
name: diagnosing-secrets
description: Diagnose Hermes secret and credential management issues — secret sources not resolving, vault locked, egress firewall blocking, and credential pool failures.
version: 1.0.0
metadata:
  hermes:
    tags: [hermes, secrets, credentials, vault, egress, troubleshooting, diagnosing]
    related_skills: [diagnosing-auth, diagnosing-providers, diagnosing-mcp]
---

# Diagnosing Secrets

Goal: reduce any secret/credential problem to one concrete fix — a source resolution failure, a vault lock, or an egress rule.

## 1. How to inspect

- `hermes secrets bitwarden` / `hermes secrets onepassword` — configure secret sources
- `hermes secrets bitwarden status` / `hermes secrets onepassword status` — check source status
- `hermes vault list` — list vault credentials
- `hermes vault add <name>` — add vault credential
- `hermes vault rm <name>` — remove vault credential
- `hermes egress status` — show egress firewall status
- `hermes egress config` — view egress config
- `hermes doctor` — flags credential issues

## 2. Common failures

### Secret source not resolving

**Symptom:** A secret referenced as `${SECRET_NAME}` in config is empty or causes "secret not found" errors.

**Cause:** Secret source (Bitwarden, 1Password, env) not configured, or secret name doesn't match.

**Fix:**
```bash
hermes secrets list                      # list configured sources
hermes secrets show <name>              # verify secret exists
# Check .env fallback:
cfg=$(hermes config path)
ls "$(dirname "$cfg")/.env"             # .env should be beside config
```

### Vault locked

**Symptom:** `hermes vault list` fails with "vault locked" or "decryption failed".

**Cause:** Vault password not provided, or key file corrupted.

**Fix:**
```bash
hermes vault list                        # triggers unlock prompt
# If password forgotten, vault cannot be recovered — recreate:
hermes vault rm <name>
hermes vault add <name>                  # re-add credentials
```

### Egress firewall blocking

**Symptom:** Tool calls or API requests fail with connection refused or timeout, but work without egress enabled.

**Cause:** Egress iron-proxy rules block the destination host or port.

**Fix:**
```bash
hermes egress status                     # check if egress is active
hermes egress config                     # view proxy config path
# Edit proxy.yaml to add allow rules, then:
hermes egress reload                     # hot-reload rules
```

### Credential pool exhausted

**Symptom:** Provider requests fail with "no available credentials" or "pool empty".

**Cause:** All credentials in the pool are rate-limited, expired, or revoked.

**Fix:**
```bash
hermes auth status                       # check credential pool health
hermes auth add <provider>               # add new credential
# Remove dead credentials:
hermes auth remove <provider> <id>
```

### Secret leaks in logs

**Symptom:** API keys or tokens appear in `~/.hermes/logs/` or session output.

**Cause:** Secret referenced in a command argument or logged by a tool.

**Fix:**
```bash
grep -rn "sk-\|token\|api_key" ~/.hermes/logs/ | head  # scan for leaks
# Rotate leaked credentials immediately
# Use ${SECRET_NAME} references instead of inline values
```

## 3. Verification

```bash
hermes secrets list                      # sources resolve
hermes vault list                        # vault unlocks
hermes egress status                     # firewall state correct
hermes auth status                       # credential pool healthy
hermes doctor                            # no credential errors
```

Pass: all secret sources resolve; vault unlocks; egress rules correct; no leaked credentials.

Fail: secret not found — check source config and .env; vault locked — verify password.

## 4. Related

- `diagnosing-auth` — GitHub auth issues
- `diagnosing-providers` — model provider credential issues
- `diagnosing-mcp` — MCP server OAuth and credential issues

*Facts re-verified 2026-11-01 against upstream source at commit `40804ce4074c561220c4a766e116e07b4873b1c3` (installed Hermes CLI: `hermes secrets --help`, `hermes vault --help`, `hermes egress --help`). Re-verify before reuse.*