---
name: diagnosing-plugins
description: Diagnose Hermes plugins that do not load or run — the plugins.enabled opt-in gate, capability consent, discovery locations, and sub-category selection keys.
version: 1.2.15
metadata:
  hermes:
    tags: [hermes, plugins, troubleshooting]
    related_skills: [hermes-configuration-guide, diagnosing-host-pressure]
---

# Diagnosing Plugins

A Hermes plugin is a **Python package**: a directory with a `plugin.yaml` manifest and a `register(ctx)` function. The single most common failure: **the plugin is discovered but not enabled** — Hermes deliberately loads nothing from third-party code until you add it to `plugins.enabled`.

> **Disambiguation**: if a provider sub-category (e.g. `context.engine`, `image_gen.provider`) is misconfigured, see `diagnosing-providers` — that is a provider configuration problem, not a plugin-loading problem.

## 1. Discovery locations (later sources override same-name earlier ones)

| Source | Path | Gate |
|---|---|---|
| Bundled | `<install>/plugins/` | Platform/backend sub-plugins auto-load; bundled standalone plugins still need opt-in |
| User | `$HERMES_HOME/plugins/<name>/` | `plugins.enabled` allow-list |
| Project | `<repo>/.hermes/plugins/` | Requires `HERMES_ENABLE_PROJECT_PLUGINS=true` at startup |
| pip | `hermes_agent.plugins` entry points | `plugins.enabled` |
| Nix | `services.hermes-agent.extraPlugins` | Nix config |

`hermes plugins install owner/repo [--ref <40-char SHA>] [--enable|--no-enable]` installs from Git (pinned commits only); `hermes plugins update` refuses to move a pinned plugin. Sub-category directories have their **own loaders and selection keys** — they do not obey `plugins.enabled`. Verified present at current main: `platforms/<name>/` (messaging channels, gated per messaging platform in config), `memory/<name>/` (one active, `memory.provider`), `context_engine/<name>/` (`context.engine`), `model-providers/<name>/` (picked via `--provider`/config), `image_gen/<name>/` (`image_gen.provider`), plus `browser/`, `video_gen/`, `cron_providers/`, `dashboard_auth/`, `web/`, `computer_use/` (`plugins/computer_use/__init__.py`: bundled `plugins/computer_use/<name>/` providers plus the built-in `cua` driver, one active), and `delegation/` (`delegation.backend` selects the bundled strategy; the `default` strategy then reads `delegation.provider` / `model` / `base_url`; `plugins/delegation/default/plugin.yaml`). **`observability/` is not one of these** — it was listed here from v2026.9.11 until 2026-10-19 but `plugins/observability/` exists neither at the pinned baseline nor at upstream main. **Not every bundled entry auto-loads:** upstream's discovery reports disabled bundled plugins as *"not enabled in config (run `hermes plugins enable <key>` to activate)"* (`hermes_cli/plugins_discovery.py`), and bundled Kanban is one of them — check `hermes plugins list` for the real state instead of assuming a bundled directory is live. **The set grows — list `plugins/` in the installed source instead of trusting this list.**

## 2. The enable gate and capabilities

```yaml
plugins:
  enabled: [my-plugin]
  disabled: [noisy-plugin]   # deny-list always wins over enabled
```

Three ways to flip: `hermes plugins` (interactive), `hermes plugins enable <name>`, `hermes plugins disable <name>`. Declared capabilities require a separate one-time consent recorded under `plugins.entries.<id>.granted_capabilities` (legacy `allow_*` keys are still read). Verified capability ids at current main: **`tools.override`** and **`gateway.platform_actions`** — this list is code-defined and grows, so check `plugin_capability_granted()` / `ctx.has_capability()` rather than trusting any doc (an earlier revision of this skill named a `llm.model_override` id that **does not exist**). Two behaviours worth knowing: **bundled plugins are trusted for `tools.override`** (no consent needed), and unknown ids or unreadable consent **fail closed** (False). **Non-interactive installs/enables grant nothing** — the plugin runs with capabilities off and must degrade gracefully (`ctx.has_capability()`).

## 3. How to inspect

- `hermes plugins` — interactive UI (SPACE toggles enabled).
- `hermes plugins list` — enabled / disabled / not-enabled per plugin.
- `hermes plugins capabilities [name]` — declared vs granted.
- `/plugins` in chat — status listing.
- `hermes logs --follow` — a plugin whose `register()` raises is skipped with a logged error (never crashes Hermes), so read the log for load failures.

## 4. Pitfalls (symptom → cause → fix)

1. **Installed but tools/hooks/commands absent** — not in `plugins.enabled` (install defaults to disabled; `--enable` or the post-install prompt is opt-in). → **Permanent:** add it to `plugins.enabled` (`hermes plugins enable <name>`) and restart. **Temporary:** there is no read-only way to load a disabled plugin — enabling is the fix, so do it deliberately rather than working around it. Bundled standalone plugins are opt-in too — only platform/backend sub-plugins auto-load.
2. **Plugin works but a privileged feature is off** — capability declared but never granted (non-TTY install, or declined). → `hermes plugins capabilities <name>`; re-consent via interactive `hermes plugins enable <name>`.
3. **Project plugin ignored** — `.hermes/plugins/` is disabled by default. → Set `HERMES_ENABLE_PROJECT_PLUGINS=true` before starting Hermes, and only for trusted repos.
4. **Plugin in `list` but nothing loads at all** — `register()` raised (bad code, missing dependency). → Check `hermes logs` for the load error; fix the plugin or its requirements. If the log instead says `load timed out after Ns` (optionally followed by `called register_*() after its load timed out; ignored`), the loader's own budget expired before `import()` + `register()` returned. That budget covers the **plugin's** work as much as the host's, so the message alone does not tell you which one was too slow — a slow import or a blocking `register()` reaches the same deadline on a healthy host. Compare the configured `plugins.load_timeout_seconds` against what that plugin's import and `register()` actually do, and run `diagnosing-host-pressure` (`bash skills/diagnosing-host-pressure/scripts/host_pressure_probe.sh`) to rule the host in or out. Only treat it as host pressure once the probe says so. Re-run the same load once before blaming either side: a cold first load — fresh install, pin change, empty caches — can exceed the default on a slow host and pass on immediate retry. The loader's per-plugin budget is configurable: `plugins.load_timeout_seconds` in `config.yaml` (default 10; negatives and non-numbers fall back to 10 with a warning; values above 600 clamp to 600; `0` disables the deadline and loads the plugin inline) — raise it or set it to `0` only once the probe or a repeated pattern establishes the cause, then restart.
5. **Edits to a bundled plugin don't apply** — a same-name user plugin at `$HERMES_HOME/plugins/<name>/` overrides the bundled copy. → Edit the user copy (the one that actually wins) or remove it.
6. **`hermes plugins update` refuses** — the install is pinned to an exact commit SHA. → Choose a new commit explicitly: `hermes plugins install <source> --force --ref <new-sha>`.
7. **Plugin edits after install lost on update** — updates autostash and re-apply local edits, but conflicts can drop them. → Keep plugin customizations in your own fork/repo and install from that.
8. **It's not really a plugin** — TTS/STT command providers are config-driven (`tts.providers.<name>` / `stt.providers.<name>` with `type: command`); MCP integrations are `mcp_servers:` entries; gateway hooks are directories. → Route to the right surface: **`diagnosing-mcp`**, **`diagnosing-hooks`**, or the config docs.
9. **Core plugin gone after update (e.g. Spotify)** — some bundled plugins moved to the catalog; an enabled entry with no matching directory is not a broken install. → `hermes plugins install <name>` from the catalog (or remove it from `plugins.enabled`).
10. **Installed directory exists but the plugin is never listed** — discovery could not read the directory, so it skipped it and moved on: `Skipping unreadable plugin directory <path>: [WinError 5] Access is denied` (Windows) or `Permission denied` (POSIX). `hermes plugins list` simply omits the plugin, and `hermes update` / `hermes pm install` adds `Could not inspect plugin manifest <path>/plugin.yaml`. → Check the ACL: `icacls <path>` failing with `Access is denied`, or on Windows `dir /q` showing an owner other than you, means the DACL grants your account no read (an orphaned owner SID does this). Fix from an **elevated** prompt — `takeown /f <path> /r /d Y` then `icacls <path> /grant "<you>:(OI)(CI)F" /T` — or delete the directory and reinstall the plugin, then confirm it appears in `hermes plugins list`. Skipping one unreadable directory is deliberate: it must not abort discovery for every other plugin (`hermes_cli/plugins_discovery.py::scan_directory`; `hermes_cli/config.py::_platform_plugin_manifests`).
11. **`hermes plugins update` blocked by security scan** — community plugins with many LOW findings (e.g., persistence warnings) get a "Blocked (community source + caution verdict)" decision. → **Fix 1:** for an unpinned plugin, run `hermes plugins update <name> --force` to accept a caution verdict while keeping dangerous findings blocked. **Fix 2:** if the plugin is pinned to an exact SHA, use `hermes plugins install <source> --force --ref <new-sha>` (pitfall 6). If you temporarily set `plugins.scan_on_install: false`, restore it to `true` after the update.

## 5. Localization workflow

1. `hermes plugins list` — is it discovered? No → wrong location / not installed (§1 table; project plugins → pitfall 3).
2. Discovered but "not enabled" → pitfall 1 (`hermes plugins enable`).
3. Enabled but broken → `hermes logs` for a `register()` failure (pitfall 4) or a capability gap (pitfall 2). A **load-timeout** message alone does not tell you which side was slow — check pitfall 4 and run `diagnosing-host-pressure` (`bash skills/diagnosing-host-pressure/scripts/host_pressure_probe.sh`) to rule the host in or out; only treat it as host pressure once the probe says so.
4. Sub-category plugin (memory/context/model-provider/platform) → check its selection key in config, not `plugins.enabled`.
5. Restart the session/gateway and verify: tools appear in `/tools list`, commands in `/` autocomplete, hooks via `hermes hooks list`.
6. Re-run the detector: `hermes guide plugins` headless or `/hermes-doctor plugins` in-session; `+` means healthy, `~` means informational, and `x`/`?` means unresolved.

## Report

This skill diagnoses plugins that do not load or run — the plugins.enabled opt-in gate, capability consent, discovery locations, and provider sub-categories. When you run the diagnostic workflow, present findings in the standard format below.

### Summary
Your plugin is installed but its tools and commands are absent because it is not in the `plugins.enabled` allowlist. Hermes deliberately loads nothing from third-party code until you explicitly enable it.

### Findings
| Severity | What | Evidence |
|---|---|---|
| HIGH | Plugin not in `plugins.enabled` | `hermes plugins list` shows `my-plugin: not enabled`; no tools or commands from the plugin appear in the session |
| MEDIUM | Plugin discovered but not enabled after install | `hermes plugins list` shows the plugin under "Installed" but not under "Enabled" |

### Recommended Fix
Run `hermes plugins enable my-plugin`, then restart the session. Verify with `hermes plugins list` (should show "Enabled") and check that the plugin's tools appear in `/tools list`.

### References
- `$HERMES_HOME/config.yaml` — `plugins.enabled` list
- `hermes_cli/plugins.py` — `plugins.enabled` handling
- `hermes_cli/plugins_discovery.py` — plugin discovery and "not enabled" message

---

*Facts re-verified 2026-10-26 against upstream source at commit `edfa1c2a135532a8b64f7825c0ac0af6cfe73d4d`: `has_capability` now lives on `hermes_cli/plugins_capability_ctx.py::PluginCapabilityCtxMixin` (it moved out of `hermes_cli/plugins.py` in upstream `a8db834`, 2026-10-23); the capability set and fail-closed behaviour are unchanged. Earlier entry, 2026-09-28 at `46a0daee58abbc1b07f84f505a5ba90f1958295c` (corrective pass): entry-point group `hermes_agent.plugins` and the project-plugins gate `HERMES_ENABLE_PROJECT_PLUGINS` (`plugins/memory/__init__.py`, `hermes_cli/plugin_dev.py`); the capability set and fail-closed behaviour (`hermes_cli/plugins_capability_ctx.py::has_capability`, `plugin_capability_granted`); `plugins.enabled` handling (`hermes_cli/plugins.py`); the sub-category directory list (`plugins/`, narrowed in the corrective pass — bundled Kanban is gated by `plugins.enabled`, per `hermes_cli/plugins_discovery.py`); selection keys `context.engine` (`hermes_cli/web_server_config.py`) and `image_gen.provider` (`agent/image_gen_*.py`). One claim was corrected (the nonexistent `llm.model_override` id). Spotify core-to-catalog move verified 2026-10-15 against the installed source at `9bda154d` (v0.21.7): absent from bundled `plugins/`, present as official catalog entry (`spotify` 2.0.0); migration in `hermes_cli/left_core_migration.py`. Sub-category directory list re-verified 2026-10-19 against upstream main (`git ls-tree -d` on `plugins/`, and `plugins/computer_use/__init__.py`): the guide's pin gained `computer_use/` -- a provider directory with no `plugin.yaml` of its own and its own selection key -- and lost `observability/`, which was never an upstream directory (absent at baseline `d97007c`, at upstream main, and at every fetched commit). Upstream `plugins/` lists the same 22 directories at both ends of the window, so the 44->46 `VALID_HOOKS` growth and the `post_compaction` / `on_session_delete` additions need no change here -- those names are read from the installed source, never enumerated. Re-verified 2026-10-20 against the installed source at `dd519c74` (v0.22.2+1915): the per-plugin load deadline is configurable via `plugins.load_timeout_seconds` — default 10s, negatives and non-numbers fall back to 10 with a warning, `>600` clamps to 600, `0` disables the deadline and loads inline (`hermes_cli/plugins_loader.py::_resolve_plugin_load_timeout`, `hermes_cli/plugins_loader.py::run_with_load_deadline`); matching observation on this host: one cold first load after a fresh pin-install timed out on the default and the immediate retry passed (`hermes plugins doctor hermes-guide --ci`: rc=1 once, then rc=0 twice). Corrected 2026-10-20: the budget is per plugin, not global, and it is set only in config -- no plugin's `__init__.py` carries a load-timeout figure. Re-verified 2026-10-20 against the installed source at `9bda154d`: an unsearchable plugin directory is skipped with a warning and the plugin is absent from discovery (`hermes_cli/plugins_discovery.py::scan_directory`), and the platform-manifest scan records the skip (`hermes_cli/config.py::_platform_plugin_manifests`); observed on this host (Windows, WinError 5) on a directory owned by an unresolved SID. Re-checked 2026-10-23 against upstream main: `plugins/delegation/<name>/` plugins are `kind: backend`, selected by `delegation.backend`; the bundled `default` strategy then reads `delegation.provider` / `model` / `base_url` (`agent/delegation_registry.py`, `plugins/delegation/default/plugin.yaml`, `website/docs/developer-guide/delegation-provider-plugin.md`). Upstream discovery scans `plugins/delegation/` (it is not in the excluded-category set), so it is documented here but deliberately not in `constants.PLUGIN_SUBCATEGORY_DIRS`, which drives the guide's discovery skip. Re-verify before reuse.*
