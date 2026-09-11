---
name: diagnosing-providers
description: Diagnose model provider issues — custom endpoints flooding the picker with hundreds of models, discover_models misbehaving, persisted catalogs bloating config, and provider/auth failures.
version: 1.0.0
metadata:
  hermes:
    tags: [hermes, configuration, troubleshooting]
    related_skills: [hermes-configuration-guide, diagnosing-auth]
---

# Diagnosing Model Providers

Goal: reduce any model-provider problem to one concrete fix — a `providers:` / `custom_providers:` entry in `$HERMES_HOME/config.yaml` (resolve with `hermes config path`) or a `hermes model` subcommand.

## Step 0 — Resolve the config first

Never edit a path you have not verified. Run `hermes config path` — it prints the active config file. `hermes config show` dumps the merged view; `hermes config set providers.<name>.<key> <value>` edits safely.

## Step 1 — The two discovery modes

Every provider entry accepts `discover_models`, which **defaults to `true`**:

```yaml
providers:
  my-gateway:
    api: https://llm.internal.example.com/v1
    discover_models: true        # default — probes /v1/models, full catalog in picker
    models:
      - my-finetune-v2
```

| `discover_models` | `models:` shape | Picker shows |
|---|---|---|
| `true` (default) | absent or dict | Full endpoint catalog, live probe |
| `false` | list | Only the listed IDs |
| `false` | absent | Only the saved `model:` |

There is no "top N", no "most-used", no auto-narrowing. The switch is binary.

> [!NOTE]
> `discover_models` accepts string values too: `"false"`, `"no"`, `"0"` all mean False.

## Step 2 — The catalog-bloat trap

Hermes persists a discovered catalog under `models:` as a **dict** with `models_discovered: true`. This is **metadata, not a pin** — `model_switch.py:_models_config_is_allowlist` treats a discovered catalog as never-a-pin. It does nothing but bloat `config.yaml`.

A persisted catalog is a copy of the last `/v1/models` response. It is not consulted at runtime; the endpoint is re-probed at every picker build. It drifts from the endpoint and must be hand-maintained if treated as authoritative.

**Fix:** remove the `models:` dict and `models_discovered:` flag. Keep `discover_models: true` for a live probe, or `false` to pin.

**Verify the fix:** `hermes config get providers` shows the entry with no `models:` block, and `wc -l "$(hermes config path)"` drops by roughly one line per persisted model.

## Step 2.5 — Distinguish config bloat from endpoint reality

Before editing anything, confirm the endpoint actually returns that many models. A persisted catalog is a snapshot; the live endpoint may differ:

```bash
PROVIDER_MODELS_COUNT=$(curl -s -H "Authorization: Bearer ${PROVIDER_API_KEY}" "${PROVIDER_BASE_URL}/models" | python -c 'import sys,json; print(len(json.load(sys.stdin)["data"]))')
```

If the live count matches the persisted count, the catalog is current and the bloat is real. If it is much smaller, the persisted catalog is stale — removing it loses nothing.

> [!CAUTION]
> Never paste a real API key into a command line. Keep it in an environment
> variable and reference it as `${PROVIDER_API_KEY}` — that keeps the value out
> of shell history and out of the visible process arguments. The `python`
> pipe does not change that; the exposure is the `-H` argument itself, so the
> variable form is the fix.

## Step 3 — Allowlist vs metadata

`models:` shaped as a **list** is an allowlist that narrows a public endpoint. Shaped as a **dict**, it is per-model metadata and the probe still runs — so a dict never restricts the picker.

To pin a dict catalog, set `discover_models: false` **and** convert `models:` to a list:

```yaml
discover_models: false
models:
  - my-finetune-v2
  - my-finetune-v1
```

## Step 4 — API key resolution

A provider's key comes from two places, checked in order:

1. **Inline `api_key:`** — a literal value or `${VAR}` reference in the entry. Takes precedence.
2. **`key_env:`** — the name of an environment variable. Resolved at runtime from `$HERMES_HOME/.env` and the process environment.

```yaml
providers:
  my-gateway:
    api: https://llm.internal.example.com/v1
    key_env: MY_GATEWAY_API_KEY      # read from .env / environment
    api_key: ${MY_GATEWAY_API_KEY}    # equivalent inline form
```

If both are absent, the provider runs unauthenticated.

### The auto-generated key env var

When you add a provider through the CLI setup wizard (`hermes model`), Hermes derives the env var name from the endpoint's host:port so two servers on one host keep separate credentials. `hermes_cli/config.py:2574`:

```python
def custom_endpoint_key_env(identity: str) -> str:
    slug = re.sub(r"[^A-Z0-9]+", "_", str(identity or "").upper()).strip("_")
    return f"HERMES_CUSTOM_{slug}_API_KEY" if slug else "HERMES_CUSTOM_API_KEY"
```

| Endpoint identity | Generated var |
|---|---|
| `api.example.com` | `HERMES_CUSTOM_API_EXAMPLE_COM_API_KEY` |
| `localhost:8088` | `HERMES_CUSTOM_LOCALHOST_8088_API_KEY` |

The fixed `HERMES_CUSTOM_` prefix is required — it keeps the name POSIX-valid when the slug starts with a digit, since `save_env_value` rejects those.

**You do not need to adopt this convention.** `key_env` accepts any valid env var name; hand-named vars like `MY_GATEWAY_API_KEY` work identically. The generated form is only used by wizard-provisioned endpoints. Mixing the two is fine — what matters is that the var exists in `.env` and matches the `key_env` string.

> [!NOTE]
> Entries relying on `key_env` must not get a synthesized `api_key` written into config — the runtime resolves `key_env` directly, and persisting the value would downgrade credential hygiene.

## Step 5 — Provider/auth failures

- `Could not fetch models from endpoint` at picker time → the endpoint rejected the request. Check `key_env` / inline `api_key`, and whether the endpoint serves `/v1/models` at all (some gateways route only `/chat/completions`).
- `gh` / hub 401 on install → see `diagnosing-auth`.
- A model listed in `models:` but absent from the endpoint stays listed and **fails at request time** — there is no validation against the endpoint.

## Step 6 — Legacy format

Older configs use a top-level `custom_providers:` list with `base_url` instead of `api`. Still supported and auto-migrated to the `providers:` dict on `hermes update` (config v12).

> [!CAUTION]
> **Keep this skill host-agnostic.** Do not reintroduce a real third-party provider
> hostname, base URL, or `key_env` name as a worked example — `api.example.com` and
> `MY_GATEWAY_API_KEY` are the placeholders. A skill whose subject is *model
> providers in general* must not carry the flavor of whatever provider the last
> debugging session happened to touch.

Every diagnosis ends in a concrete action: a `providers:` field edit or a `hermes model` command, then `hermes gateway restart` to apply.