---
name: diagnosing-browser
description: Diagnose Hermes browser automation issues — CDP connection failures, attach problems, agent-browser/build-gate history, and browser tool errors across the pre-v52 built-in tools and the v52 browser_exec surface.
version: 1.1.0
metadata:
  hermes:
    tags: [hermes, browser, cdp, playwright, troubleshooting]
    related_skills: [hermes-configuration-guide, diagnosing-plugins]
---

# Diagnosing Browser Automation

Goal: reduce any browser problem to one concrete fix — a CDP endpoint, a Chromium install, or a version ruling. Two upstream browser surfaces exist:

- **Pre-v52 installed surface (through v0.22.2, what this guide runs against)**: built-in `browser_*` tools (`browser_snapshot`, …) and `browser.backend: cdp | playwright | browser_use`.
- **Config v52+ (upstream `5894e750`)**: agent-browser and the built-in `browser_*` tools are removed; `browser_exec` (`tools/browser_use_cli.py::browser_exec`) is the only core browser; `browser.backend` is dropped (51→52 migration, `hermes_cli/config_migrations_browser.py`) and agent-browser's `AGENT_BROWSER_*` .env keys move to the `browser.*` keys below.

Detect the surface: the v52 run prints a one-time notice naming the dropped `browser.backend` key (step 51→52, `hermes_cli/config_migrations_browser.py`), and pre-v52 installs still accept that key — do not rely on key rejection; pin it with `hermes --version`.

## 1. Configuration shape

Pre-v52 (installed through v0.22.2; `$HERMES_HOME` is `~/.hermes` on POSIX and `%LOCALAPPDATA%\hermes` on native Windows — `hermes config path` prints it):

```yaml
# $HERMES_HOME/config.yaml
browser:
  backend: "cdp"              # cdp | playwright | browser_use
  cdp:
    endpoint: "http://127.0.0.1:9222"
    user_data_dir: "$HERMES_HOME/chrome-debug"
  playwright:
    browser: "chromium"       # chromium | firefox | webkit
    headless: true
```

v52+ (`hermes_cli/config_defaults.py` at `5894e750`):

```yaml
# $HERMES_HOME/config.yaml
browser:
  cdp_url: "http://127.0.0.1:9222"   # attach to an existing Chromium; "" = local launch
  engine: "auto"                     # auto | lightpanda ("chrome" reads as auto)
  executable_path: ""                # "" = pm's chromium (`hermes pm install chromium`)
  user_data_dir: ""                  # persistent profile dir; "" = fresh throwaway profile
  use_real_profile: false            # consent-gated: browse with a snapshot of the real profile
```

## 2. How to inspect

- `/browser status` — show current browser connection state
- `/browser connect` — auto-launch/connect to a local Chromium-family browser
- `/browser connect ws://host:port` — connect to a specific CDP endpoint (loopback only — unencrypted)
- `/browser disconnect` — detach and return to cloud/local mode
- `hermes browser close-profile` — (Windows only) kill the profile's browser tree so a new real-profile snapshot can copy cookies
- `hermes logs --follow` — watch for browser-related errors
- `google-chrome --version` / `brave-browser --version` — check browser version

> [!WARNING]
> CDP is a privileged browser-control interface. `ws://` is unencrypted — reserve it for loopback (`127.0.0.1`). For remote CDP, use `wss://` (TLS) or an authenticated tunnel (e.g. SSH). Exposing CDP over cleartext on an untrusted network lets attackers observe or inject browser-control traffic.

## 3. Pitfalls (symptom → cause → fix)

1. **Browser not connecting** — (a) browser not started with `--remote-debugging-port=9222`; (b) port 9222 not open; (c) wrong endpoint URL. → Launch browser with `--remote-debugging-port=9222 --user-data-dir="$HERMES_HOME/chrome-debug"` (POSIX; native Windows: `%LOCALAPPDATA%\hermes\chrome-debug`); verify port is open (`curl http://127.0.0.1:9222/json/version`); check the endpoint in config.yaml (`browser.cdp.endpoint` pre-v52, `browser.cdp_url` v52+).
2. **Chrome 144+ CDP tools fail despite successful connect** — historically #12912 (now closed): Chrome 144+ built-in remote debugging reported success but CDP tools failed. → First re-check current behavior before downgrading — the upstream gate has since been reworked; only downgrade to <144 if a current failure reproduces, and check `hermes_cli/browser_connect.py` (loopback attach + real-profile snapshot helpers) for how the endpoint is discovered and normalized.
3. **Playwright not found (pre-v52 surface)** — (a) Playwright not installed; (b) browser binaries not downloaded. → On a PM-era install run `hermes pm install playwright` (these components are PM-managed opt-outs; a bare `pip install` targets your shell's Python, not Hermes's); on an older checkout `pip install playwright && playwright install chromium`; verify through Hermes's own interpreter, not the shell's — `python -c "import playwright"` can report the module missing even after `hermes pm install playwright` succeeded, sending you back to a repair you already did (there is no `python` shim on a PM-era install). Use `hermes doctor` or check the committed environment directly. On v52+ the `browser:` block has no Playwright keys — the local runtime path is `browser_exec` plus Chromium (`hermes pm install chromium`); pin the surface before installing anything named Playwright.
4. **agent-browser gate blocks CDP (pre-v52 surface, historically #15952, now closed)** — old builds required agent-browser even with a CDP endpoint configured, and the gate later moved to a routed requirements check in `tools/browser_tool.py`. v52 removed agent-browser and with it this gate; `tools/browser_tool.py` and `tools/browser_tool_install.py` survive only as frozen compatibility stubs (`tools/browser_tool.py::warm_agent_browser_npx_cache`) for pre-PM update runs. → Try `/browser connect` first. If the current error names agent-browser, the running build predates v52: install it (`hermes pm install agent-browser`) or update Hermes. On v52+ an agent-browser error cannot occur.
5. **Browser tools return empty or timeout** — (a) browser crashed or closed; (b) page not loaded; (c) selector not found. → Check `/browser status`; verify page loaded; inspect the DOM with `browser_exec` (v52+) or `browser_snapshot` (pre-v52).
6. **Camofox backend unsupported** — Camofox is REST-only, no CDP surface, and it left core (v52+ reads catalog-plugin values from the free-form `browser.camofox` mapping). → Switch to CDP or the local `browser_exec` runtime.
7. **Browser profile conflicts** — multiple Hermes instances using same user-data-dir. → Use separate `user_data_dir` per profile; close other browser instances.
8. **Sub-agent can't use main agent's CDP browser** — keychain access error on macOS. → Grant keychain access to the terminal app; or use a separate CDP endpoint per agent.

## 4. Localization workflow

1. `/browser status` — check current connection state.
2. `google-chrome --version` — verify browser version (historical gate was <144 for CDP; only constrain the build if a current failure reproduces — see pitfall 2).
3. `curl http://127.0.0.1:9222/json/version` — verify CDP endpoint is reachable (pre-v52 `backend: cdp`, or v52+ with `cdp_url` set; other runtimes verify their own path — see step 7).
4. Check config.yaml `browser:` block — pre-v52: backend and endpoint; v52+: `cdp_url`, `engine`, `executable_path`.
5. Match the failure: not connecting → pitfall 1; Chrome-version-gated tools → pitfall 2 (only if reproduced now); Playwright missing → pitfall 3 (pre-v52); gated although configured → pitfall 4 (only if the current error names agent-browser on a pre-v52 build).
6. Apply the fix, `/browser connect`, and verify with `/browser status`.
7. Headless: `/browser*` steps need a live session. Check the `browser:` block in `config.yaml`. Pre-v52: if `browser.backend` is `cdp`, verify the configured endpoint and browser build. v52+: verify `cdp_url` (or the local launch path) and `engine`.

## 5. Cross-references

- `hermes-configuration-guide` — for $HERMES_HOME resolution and config.yaml structure
- `diagnosing-plugins` — for plugin loading and capability issues
- `diagnosing-cli-tui` — for Windows-specific browser issues

## Report

This skill diagnoses browser automation issues — CDP connection failures, attach problems across the pre-v52 built-in tools and the v52 `browser_exec` surface, and browser tool errors. When you run the diagnostic workflow, present findings in the standard format below.

### Summary
Your browser automation fails — browser tools return empty or timeout, the CDP attach fails, or the gate names a missing requirement. First record the surface you are on (`hermes --version`, plus the v52 notice if present) and the `/browser status` output; connection state is evidence, not an assumption. Historically Chrome 144+ built-in remote debugging or agent-browser gating broke attach — both were reworked, and config v52 upstream removed agent-browser plus the built-in `browser_*` tools entirely.

### Findings
| Severity | What | Evidence |
|---|---|---|
| HIGH | CDP tools fail or return empty | `/browser status` output for the actual connection state; the DOM read (`browser_exec` v52+, `browser_snapshot` pre-v52) reproduces the failure; `google-chrome --version` records the browser build |
| MEDIUM | Pre-v52 agent-browser gate blocks an otherwise configured setup | Log names the missing requirement, and `/browser status` plus the version pin have pre-v52 in evidence; install only what the current error names |
| MEDIUM | Pre-v52 config keys (`backend`, `cdp:`, `playwright:`) on a v52+ install | Migration notice names the dropped keys; keys are ignored |

### Recommended Fix
Reproduce first: confirm the failure on the current browser build and read the routed error. Only downgrade Chrome below 144 if a current failure implicates the build, and only install agent-browser (`hermes pm install agent-browser`, pre-v52 only) if the current error names it. On v52+ route all browser work through `browser_exec` and `/browser connect` — never the retired built-in tool names. Then run `/browser connect` and verify with `/browser status`.

### References
- `$HERMES_HOME/config.yaml` (`hermes config path` prints it) — the `browser:` block (pre-v52 `backend` + `cdp:`/`playwright:` sub-blocks; v52+ `cdp_url`/`engine`/`user_data_dir` keys)
- `hermes_cli/browser_connect.py` — shared helpers for attaching to a loopback CDP port and snapshotting the real profile
- `tools/browser_use_cli.py::browser_exec` — the only core browser (v52+)
- `hermes_cli/config_migrations_browser.py` — the v52 (51→52) migration that drops `browser.backend` and moves `AGENT_BROWSER_*`
- `tools/browser_supervisor.py` + `tools/browser_supervisor_capture.py` + `tools/browser_supervisor_dialogs.py` + `tools/browser_supervisor_frames.py` — browser supervision logic

*Facts re-verified 2026-09-21 against upstream source at commit `cedf4a3d78675283fa93e4e6ea2d6212bf414667`: `hermes_cli/browser_connect.py`, `hermes_cli/browser_supervisor.py`; plus the official docs (hermes-agent.nousresearch.com/docs/user-guide/features/browser). Re-checked 2026-10-12 against upstream main (`53bc70c5`): supervision logic lives under `tools/browser_supervisor.py` with `capture`/`dialogs`/`frames` split files (`tools/browser_supervisor_capture.py`, `tools/browser_supervisor_dialogs.py`, `tools/browser_supervisor_frames.py`); #12912 and #15952 closed, downgrade/agent-browser directives reframed as historical. Re-checked 2026-10-24 against upstream main (`5894e750`): config step 51→52 (`hermes_cli/config_migrations_browser.py`) removes agent-browser and the built-in `browser_*` tools; `browser_exec` (`tools/browser_use_cli.py::browser_exec`) is the only core browser and its `browser:` defaults (`cdp_url`, `engine`, `executable_path`, `user_data_dir`, `use_real_profile`, `dialog_policy`) carry no Playwright keys; `/browser status|connect|disconnect` remain — CLI path `hermes_cli/cli_commands_mixin.py::_BROWSER_SUBCOMMANDS` (with `::_browser_status`) and gateway path `hermes_cli/cli_browser_gateway.py::gateway_browser` (the `browser.manage` RPC with `_normalize_cdp_url`); `tools/browser_tool.py` and `tools/browser_tool_install.py` are frozen stubs (`tools/browser_tool.py::warm_agent_browser_npx_cache`); `hermes_cli/browser_connect.py` resolves/launches a debug browser on a loopback CDP port (dual-stack IPv4/IPv6) and snapshots the real profile for `browser.use_real_profile`; `tools/browser_supervisor.py`, `tools/browser_supervisor_capture.py`, `tools/browser_supervisor_dialogs.py`, and `tools/browser_supervisor_frames.py` still exist. The installed host surface (v0.22.2, upstream `dd519c74`) predates v52 — the pre-v52 wording covers it. Re-verify before reuse.*
