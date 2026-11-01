---
name: diagnosing-secrets
description: Diagnose Hermes secret and credential management issues — secret sources not resolving, vault locked, egress firewall blocking, and credential pool failures.
version: 1.0.1
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
- `hermes vault list` — list vault credentials (locked managers are skipped)
- `hermes vault add <name>` — add vault credential
- `hermes vault rm <name>` — remove vault credential
- `hermes egress status` — show egress firewall status
- `hermes egress config` — view proxy config path
- `hermes doctor` — flags credential issues

## 2. Common failures

### Secret source not resolving

**Symptom:** A secret referenced as `${SECRET_NAME}` in config is empty or causes "secret not found" errors.

**Cause:** Secret source (Bitwarden, 1Password) not configured, or secret name doesn't match.

**Fix:**
```bash
hermes secrets bitwarden status           # check Bitwarden source
hermes secrets onepassword status         # check 1Password source
# Check .env fallback:
cfg=$(hermes config path)
ls "$(dirname "$cfg")/.env"             # .env should be beside config
```

### Vault locked

**Symptom:** `hermes vault list` skips locked managers or reports "vault locked".

**Cause:** Vault password not provided, or key file corrupted. External managers (1Password, Bitwarden) are skipped when locked; unlock happens when the agent needs a login.

**Fix:**
```bash
hermes vault list                        # lists unlocked items; locked managers skipped
hermes vault key                          # show where vault key is stored
# If local vault key is lost, recreate:
hermes vault rm <name>
hermes vault add <name>                  # re-add credentials
```

Note: `hermes vault list` does not trigger an unlock prompt. Unlocking happens lazily when the agent needs a credential.

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
hermes auth status <provider>            # check credential pool health
hermes auth list <provider>              # list credentials with indices
# Remove expired credential by index:
hermes auth remove <provider> <index>
# Add new credential:
hermes auth add <provider>
```

### Secret leaks in logs

**Symptom:** API keys or tokens appear in `~/.hermes/logs/` or session output.

**Cause:** Secret referenced in a command argument or logged by a tool.

**Fix:**
```bash
# Check for potential leaks (filenames only, no values):
grep -rl "api_key\|token\|secret" ~/.hermes/logs/ 2>/dev/null | head
# Rotate leaked credentials immediately
# Use ${SECRET_NAME} references instead of inline values
```

## 3. Verification

```bash
hermes secrets bitwarden status           # source resolves
hermes secrets onepassword status         # source resolves
hermes vault list                        # vault items listed
hermes egress status                     # firewall state correct
hermes auth status <provider>            # credential pool healthy
hermes doctor                            # no credential errors
```

Pass: all secret sources resolve; vault lists items; egress rules correct; no leaked credentials.

Fail: secret not found — check source config and .env; vault locked — verify key storage.

After applying fixes, restart the session to pick up restored credentials.

## 4. Related

- `diagnosing-auth` — GitHub auth issues
- `diagnosing-providers` — model provider credential issues
- `diagnosing-mcp` — MCP server OAuth and credential issues

*Facts re-verified 2026-11-01 against upstream source at commit `40804ce4074c561220c4a766e116e07b4873b1c3` (hermes_cli/subcommands/secrets.py, hermes_cli/vault.py, hermes_cli/subcommands/auth.py). Re-verify before reuse.*