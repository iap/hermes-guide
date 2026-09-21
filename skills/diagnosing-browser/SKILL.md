---
name: diagnosing-browser
description: Diagnose Hermes browser automation issues — CDP connection failures, Chrome 144+ compatibility, Playwright setup, agent-browser gating, and browser tool errors.
version: 1.0.0
metadata:
  hermes:
    tags: [hermes, browser, cdp, playwright, troubleshooting]
    related_skills: [hermes-configuration-guide, diagnosing-plugins]
---

# Diagnosing Browser Automation

Goal: reduce any browser problem to one concrete fix — a CDP endpoint, a Chrome version, or a Playwright installation. Browser automation uses CDP (Chrome DevTools Protocol) or Playwright to control a real browser.

## 1. Configuration shape

```yaml
# ~/.hermes/config.yaml
browser:
  backend: "cdp"              # cdp | playwright | browser_use
  cdp:
    endpoint: "http://127.0.0.1:9222"
    user_data_dir: "$HOME/.hermes/chrome-debug"
  playwright:
    browser: "chromium"       # chromium | firefox | webkit
    headless: true
```

## 2. How to inspect

- `/browser status` — show current browser connection state
- `/browser connect` — auto-launch/connect to a local Chromium-family browser
- `/browser connect ws://host:port` — connect to a specific CDP endpoint
- `/browser disconnect` — detach and return to cloud/local mode
- `hermes logs --follow` — watch for browser-related errors
- `google-chrome --version` / `brave-browser --version` — check browser version

## 3. Pitfalls (symptom → cause → fix)

1. **Browser not connecting** — (a) browser not started with `--remote-debugging-port=9222`; (b) port 9222 not open; (c) wrong endpoint URL. → Launch browser with `--remote-debugging-port=9222 --user-data-dir=$HOME/.hermes/chrome-debug`; verify port is open (`curl http://127.0.0.1:9222/json/version`); check endpoint in config.yaml.
2. **Chrome 144+ CDP tools fail despite successful connect** — known issue (#12912): Chrome 144+ built-in Remote debugging reports success but CDP tools fail. → Downgrade Chrome to <144 or use `--remote-debugging-port` flag explicitly; check `hermes_cli/browser_connect.py` for endpoint normalization.
3. **Playwright not found** — (a) Playwright not installed; (b) browser binaries not downloaded. → Run `pip install playwright && playwright install chromium`; verify with `python -c "from playwright.sync_api import sync_playwright; print('ok')"`.
4. **agent-browser gating blocks CDP** — known issue (#15952): `check_fn` requires agent-browser even when CDP endpoint is configured. → Install agent-browser (`pip install agent-browser`) or use `/browser connect` directly.
5. **Browser tools return empty or timeout** — (a) browser crashed or closed; (b) page not loaded; (c) selector not found. → Check `/browser status`; verify page loaded; use `browser_snapshot` to inspect DOM.
6. **Camofox backend unsupported** — Camofox is REST-only, no CDP surface. → Switch to CDP or Playwright backend.
7. **Browser profile conflicts** — multiple Hermes instances using same user-data-dir. → Use separate `user_data_dir` per profile; close other browser instances.
8. **Sub-agent can't use main agent's CDP browser** — keychain access error on macOS. → Grant keychain access to the terminal app; or use a separate CDP endpoint per agent.

## 4. Localization workflow

1. `/browser status` — check current connection state.
2. `google-chrome --version` — verify browser version (must be <144 for CDP).
3. `curl http://127.0.0.1:9222/json/version` — verify CDP endpoint is reachable.
4. Check config.yaml `browser:` block — verify backend and endpoint.
5. Match the failure: not connecting → pitfall 1; Chrome 144+ → pitfall 2; Playwright missing → pitfall 3.
6. Apply the fix, `/browser connect`, and verify with `/browser status`.

## 5. Cross-references

- `hermes-configuration-guide` — for $HERMES_HOME resolution and config.yaml structure
- `diagnosing-plugins` — for plugin loading and capability issues
- `diagnosing-cli-tui` — for Windows-specific browser issues

*Facts re-verified 2026-09-21 against upstream source at commit `cedf4a3d78675283fa93e4e6ea2d6212bf414667`: `hermes_cli/browser_connect.py`, `hermes_cli/browser_supervisor.py`; plus the official docs (hermes-agent.nousresearch.com/docs/user-guide/features/browser). Re-verify before reuse.*
