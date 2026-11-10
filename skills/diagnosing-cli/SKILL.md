---
name: diagnosing-cli
description: "Diagnose and fix Hermes Agent classic CLI issues (prompt_toolkit REPL, cli.py HermesCLI): rendering artifacts, themes/skins, busy indicators, encoding, and launch/resume. Use for hermes --cli, piped input, and the classic spinner."
version: 1.0.0
metadata:
  hermes:
    tags: [hermes, cli, prompt_toolkit, windows, troubleshooting, diagnosing]
    related_skills: [hermes-configuration-guide, diagnosing-path, installing-hermes, diagnosing-tui]
---

# Diagnose Hermes Classic CLI

Playbook for the classic prompt_toolkit CLI: the Python REPL in
`cli.py` class HermesCLI, with layouts in
`hermes_cli/cli_tui_mixin.py`. Use when `hermes --cli`, a piped
`--oneshot`, the classic spinner, or a classic-only rendering
defect is the subject. For the Node Ink TUI, see `diagnosing-tui`.

> **Disambiguation**: if `hermes --tui` or `display.interface: tui`
> is active, that is the Node TUI in `diagnosing-tui`, not this
> skill. If the desktop app (Electron) fails to launch or shows a
> blank window, see `diagnosing-desktop`. If a `/command` is
> missing or overridden, see `diagnosing-commands`.
> `cli_tui_mixin.py` is prompt_toolkit code despite its name; it
> is not the Node TUI.

## 0. Environment baseline (origin machine: one Windows box, re-verified 2026-09-14)

> [!CAUTION]
> This baseline records **one specific Windows machine** — the box this skill was written on. It is **not** a description of your machine. Before applying anything below, confirm the local environment with `hermes config path`, `hermes --version`, and `hermes doctor`; paths, `HERMES_HOME`, shell, and OS differ per machine (on macOS/Linux the **default** home is `~/.hermes` — overridable via `HERMES_HOME` or a named profile; `hermes config path` always prints the active one).

- Hermes Agent **v2026.9.24** on the Windows desktop install (v0.20.4 when this skill was first written, v0.21.1 at the 2026-09-14 re-check); git install: `%LOCALAPPDATA%\hermes\hermes-agent` (on the box this baseline was recorded the in-tree venv was a `.venv/`, not `venv/`; a PM-era install has no in-tree venv at all — see `diagnosing-path` for why that matters)
- `HERMES_HOME = %LOCALAPPDATA%\hermes` (native Windows; `~/.hermes` is NOT the active home)
- OS: Windows 10 Home 22H2 (build 19045.7663)
- Shell: Windows PowerShell 5.1; console host: conhost (classic window) or Windows Terminal 1.24.11911 (present on the reference box; a bare Windows 10 box has **only conhost**)
- Tool shell backend: PortableGit (MinGit, msys2) bash - resolved via `HERMES_GIT_BASH_PATH` or `%LOCALAPPDATA%\hermes\git\usr\bin\bash.exe` (non-busybox variant)
- Ground truth commands: `hermes config path`, `hermes config show`, `hermes --version`, `hermes doctor`

## 1. Launch and resume

```powershell
hermes              # classic CLI by default; launches TUI when display.interface: tui
hermes --cli        # force classic REPL for one invocation
hermes -z "prompt"  # one-shot (--oneshot): run a single prompt with tools, print the answer, exit.
                    #   Non-interactive — ideal for scripts, cron, and CI smoke-tests (e.g. verifying a
                    #   skill is discoverable AND followed: hermes -z "Use the diagnosing-path skill: which
                    #   interpreter should a script in the checkout use?"). Exits non-zero on failure.
```

Frontmatter flags that select the Node TUI are documented
in `diagnosing-tui` section 1. With no overriding frontend flag,
a non-TTY stays classic. Piped hermes chat with a query and
no TUI flag always stays classic. Explicit --tui still routes
to the Node TUI even when input is redirected.

Applied on the origin machine (config.yaml, backup: `config.yaml.bak-20260824-0457`):

```yaml
display:
  interface: tui
  tui_status_indicator: ascii
  mouse_tracking: wheel
  details_mode: collapsed
```

User env vars: `EDITOR=code --wait`, `HERMES_TUI_THEME=dark`.

### Stale update lock wedges every launch

Every `hermes` invocation hanging on `an update is still running` / `finishing an interrupted source update` with no update in progress means a leftover checkout lock (`hermes_cli/update_lock.py::read_live_update` judges it; `hermes_cli/update_lock.py::describe_holder` explains refusals). Two artifacts carry it and they are not interchangeable: the update **marker** at `<root hermes home>/.hermes-update-in-progress` is the holder record (`pid`, `started_at`, `ct:<creation time>`, optional `delegate:<pid> ct:`), while the **checkout lock** at `<git common dir>/hermes-update.lock` (or `<install root>/.hermes-update.lock` for a ZIP install with no `.git`) is a kernel lock (flock / msvcrt) that `hermes update` holds for its whole process tree. Judge liveness the way upstream does: the owner counts live only while its pid runs **and** its recorded creation time still matches (2 s tolerance), so a dead pid is suggestive but a reused pid proves nothing. Three verdicts: live owner → wait (watch the active profile's `logs/update.log` for ongoing update output; `hermes logs` only prints an `agent.log` snapshot and exits), never touch the lock; dead owner and the kernel lock free → the marker is stale and the next `hermes update` reclaims it under the marker mutex, so no human edit is needed (`hermes --version` must then exit 0); dead owner but the kernel lock still held → `held` (a killed updater's completion or build child, or a `git` process, still runs) — wait for it to exit, never delete. **Never unlink the checkout lock**: it is a kernel lock on that inode, so unlinking releases nothing and a second updater can then lock a different inode — upstream refuses to unlink or recreate it because waiters need one stable inode. `hermes guide update` automates the PID-liveness verdict where the install can still launch (fully wedged installs start here by hand). Observed live 2026-10-16: a timeout-killed plugin install left its owner PID dead 6+ min with no update running. When probing liveness by hand, never use `os.kill(pid, 0)` on Windows — it terminates the target there (POSIX-only idiom); use `Get-Process` instead. POSIX reverses the rule: `ps -p <pid>` shows a live owner, and `kill -0 <pid>` exits 0 only while it runs — a probe there, never a signal. Probe errors are unknown — never read them as proof that no child holds the lock.

## 2. How the classic CLI talks to the agent

The classic CLI is gateway-backed. `main.py` `cmd_chat` calls
`cli.main` for the classic path, which constructs HermesCLI with
an agent from `gateway_agent.py`. The agent forwards the turn to
the gateway owner over websocket JSON-RPC via
`gateway_client.py` `rpc` and `gateway_connection.py` `call`.

The spinner thread is `hermes_cli/cli_tui_mixin.py::_tui_spinner_loop`
(line 412). It calls `monitor.tick()`
(`hermes_cli/cli_subagent_monitor.py::tick`, line 127), which calls `refresh`
(`hermes_cli/cli_subagent_monitor.py::refresh`, line 83), which calls
`subagent_rows` (`hermes_cli/gateway_tools.py::subagent_rows`, line 154). That
method calls `connection.call`
(`hermes_cli/gateway_connection.py::call`, line 401), which calls `call_tagged`
(`hermes_cli/gateway_connection.py::call_tagged`, line 497), which waits on
`future.result`. The send itself is `connection.call("subagent.list", timeout=5)`.

Track this path by symbol, not by line number. Every number here is pinned to
`.github/upstream-drift.baseline` (commit `84a0301`), and upstream moves them
between releases: at the pinned revision
`hermes_cli/cli_subagent_monitor.py:83` is `def refresh` and `:85` is its
`subagent_rows` call, while a later revision puts that same `def` at line 80 and
the call at 82. Read the numbers as pointers into the pinned revision, never into
whichever checkout is failing.

### Worked example: spinner keepalive leak

A gateway websocket that times out on keepalive raises
`websockets.exceptions.ConnectionClosedError`. The path leaks it
raw: `rpc` awaits `websocket.send` at `hermes_cli/gateway_client.py:219`
with no conversion, `call_tagged` only converts `TimeoutError`,
and `subagent_rows` only catches `GatewayClientError` and
`RuntimeError`. `ConnectionClosedError` is neither, so the
spinner thread dies with a full traceback. The fix direction is
to convert the transport error to `GatewayClientError` in `rpc`
or `call_tagged`, so the existing catch in `subagent_rows`
logs debug and retains cached rows.

> [!WARNING]
> Do not fix this by catching more broadly in the spinner loop
> alone. The transport conversion belongs where the other
> `TimeoutError` conversion already sits, because every other
> gateway verb shares that path.

## 3. Slash commands that fix rendering (Node TUI unless noted)

These persist to the TUI `display:` block. `/indicator` entered in the
classic CLI still writes `display.tui_status_indicator` — the TUI setting
— even though no TUI is running in that session.

| Command | Effect |
|---|---|
| `/indicator ascii` | Readable busy indicator (default is `kaomoji`, can be hard to read on conhost). Styles: kaomoji, emoji, unicode (braille), ascii. Persist: `display.tui_status_indicator` |
| `/skin <name>` | Live theme preview. Built-ins: default, ares, mono, slate, daylight, warm-lightmode, poseidon, sisyphus, charizard. Persist: `display.skin` |
| `/exit` | Quit; conhost should restore a clean prompt (no residual frame) |

## 4. Skins and themes (style system)

- Skins live at `$HERMES_HOME/skins/<name>.yaml`; user skins inherit missing keys from `default`
- Keys: `colors` (banner_*, ui_*, prompt, input_rule, response_border, session_*, status_bar_bg, voice_status_bg, selection_bg, completion_menu_*), `spinner` (waiting_faces, thinking_faces, thinking_verbs, wings), `branding` (agent_name, response_label, prompt_symbol, help_header...), `tool_prefix`, `tool_emojis`, `banner_logo` / `banner_hero` (Rich markup ASCII art)
- Built-in skins load from `hermes_cli/skin_engine.py`; unknown skins fall back to `default`
- Consoles with poor glyph coverage: prefer ASCII-ish faces (e.g. `(>_<)`, `(^_^)`, `(o_o)`) and box-drawing `tool_prefix` like `|`
- Save skin YAML as UTF-8 WITHOUT BOM (a BOM inside a folded YAML scalar silently breaks parsing)
- Visual editor: `npx -y hermes-mod` (community tool; honors HERMES_HOME)

## 5. Windows-specific troubleshooting

1. **Mojibake / garbled output**: Hermes forces UTF-8 via `hermes_cli/stdio.py::configure_windows_stdio()` (sets CP_UTF8, PYTHONUTF8=1, PYTHONIOENCODING=utf-8). Do NOT set `HERMES_DISABLE_WINDOWS_UTF8`. If tool output from the Git Bash backend is garbled, set `LANG=C.UTF-8` / `LC_ALL=C.UTF-8` for that bash (msys2 reads Windows env). PS 5.1 pipes: `$OutputEncoding = [Text.UTF8Encoding]::new()`.
2. **Missing glyphs / tofu faces**: conhost has no font fallback. Fixes: Windows Terminal + Cascadia Mono, or `/indicator ascii`.
3. **Editor silent (`/edit`, Ctrl-X Ctrl-E)**: Hermes defaults `EDITOR=notepad`. Set `EDITOR=code --wait` (Cursor/VS Code shim works). Never point at an editor that returns immediately without `--wait`.
4. **WinError 193 (%1 is not a valid Win32 application)**: invoking an extensionless shebang script. Always use the `.cmd` shim (`npx.cmd`, not `npx`).
5. **Process liveness**: never `os.kill(pid, 0)` on Windows — upstream's own comment (`hermes_cli/gateway.py`): *"`os.kill(pid, 0)` hard-kills on Windows (TerminateProcess)"*, i.e. the probe kills the process instead of testing it. Use `psutil.pid_exists()` / `gateway.status._pid_exists()`.
6. **Antivirus flags uv.exe**: false positive; whitelist the `%LOCALAPPDATA%\hermes\bin` folder (hash changes each upgrade). Verify authenticity via `gh attestation verify` (see README).
7. **Installer BOM**: `iex (irm ...)` strips BOM; `[scriptblock]::Create((irm ...))` does not.
8. **Config schema drift**: `hermes config set` flags `display.mouse_tracking` and `display.details_mode` as unrecognized - they ARE valid keys (documented); values save and are read anyway. Do not delete them.
9. **Cursor / VS Code integrated-terminal spinner flood + prompt clip (classic CLI)**: In Cursor/VS Code, the classic CLI spinner (`* (¬_¬) ruminating... (0.7s) 🚀 model ~63.2K/1M ...`) floods scrollback — each tick persists as a new line instead of overwriting in place — and the `> ` prompt then clips its first character at the left edge. Root cause (verified in source): `KawaiiSpinner` in `agent/display.py` overwrites with `\r`, but in Cursor/VS Code integrated terminals (narrow bottom panel) the overwrite does not land — the text is rendered through prompt_toolkit's renderer (`FormattedTextControl` under `patch_stdout()`), which repaints instead of overwriting in place; the ~90-col status line exceeds the narrow pane; `shutil.get_terminal_size((80,24))` may over-report width (fallback to 80 cols when size detection fails) — verify the affected terminal's actual width and COLUMNS value before asserting the fallback caused the issue. Warning: terminals honoring CSI 3 J may have existing scrollback erased at startup (even inline); save needed output before launching the Node TUI. Permanent fix on this host is to leave the classic CLI: persist `display.interface: tui`, `display.tui_status_indicator: ascii`, `display.details_mode: collapsed`, `display.mouse_tracking: wheel`, plus `HERMES_TUI_INLINE=1` in `.env` — the Node TUI width-budgets its segments and drops the tail first on tight terminals.

See `references/cursor-vscode-spinner-flood.md` for the full playbook (detection, measurement, escape hatch, apply, verify, rollback, provenance).

## 6. Known upstream issues (check state before re-reporting)

States verified 2026-10-08. `closed` means fixed or declined upstream — check the issue before reinstalling. A linked PR proposes a fix; check its review and release status before relying on it.

| Issue | PR | State | Topic |
|---|---|---|---|
| #37637 | — | closed | `/usage` silent in CLI/TUI (worked via Telegram) |
| #19214 | — | closed | `terminal.cwd` is a foot-gun: CLI/TUI should use the launch directory |
| #14638 | — | closed | Windows: exit 126 with empty output on every command (Git Bash backend) |
| #20782 | — | closed | Windows: `terminal` / `write_file` tools fail (exit 126 / empty file) |
| #83938 | — | open | `test_profiles.py` failures on Windows with a non-UTF-8 codepage |
| #126970 | #126992 | open (PR) | CLI clarify panels stay ~67 columns wide — fix: derive panel width from live terminal width |
| #85278 | — | open | Windows same-surface guard weak + pid_alive blast radius + voice auto-restart bypasses throttle (partially stale; claim 3 still valid) |
| #86204 | — | open | Orphan CLI python.exe children not reaped on Windows — **solution identified**: Job Objects with `KILL_ON_JOB_CLOSE` (automatic crash-safe tree cleanup) |
| #93999 | — | open | KawaiiSpinner floods terminal when message exceeds terminal width |
| Cursor/VS Code classic-CLI flood + clip (local) | — | local fix only | Classic CLI spinner persists per-tick under `StdoutProxy` and the ~90-col status line over-reports width; permanent local fix is Node TUI + `HERMES_TUI_INLINE=1` (§5.9). Upstream issue #149839 was filed 2026-11-06 and closed as not actionable (filed without authorization) — no upstream fix tracked. |
| #129029 | #129052 | open (PR) | CLI input unresponsive after focus loss (macOS) |
| #129418 | #129422 | open (PR) | CLI import resets .env-sourced TERMINAL_DOCKER_VOLUMES |
| #134831 | — | open | CLI oneshot hangs in Honcho shutdown thread join |

## 6b. Temporary workaround vs permanent fix

Label every remedy. A temporary workaround unblocks **now** and is worth undoing once the
real fix lands; a permanent fix changes the host or the config and is worth keeping. Some
permanent fixes are **outside Hermes entirely** — do not report those as Hermes bugs.

| Symptom | Temporary (until a proper fix) | Permanent |
|---|---|---|
| Tofu / unreadable busy face on conhost | `/indicator ascii` (or persist `display.tui_status_indicator: ascii`) | Install **Windows Terminal** (winget: `Microsoft.WindowsTerminal`) + Cascadia Mono, set it as the default terminal — a **non-Hermes** fix for a conhost/PowerShell-5.1 limitation; Hermes itself is fine |
| Garbled tool output from the Git Bash backend | `LANG=C.UTF-8 LC_ALL=C.UTF-8` for that shell | Leave `configure_windows_stdio()` enabled — never set `HERMES_DISABLE_WINDOWS_UTF8`; PS 5.1 pipes: `$OutputEncoding = [Text.UTF8Encoding]::new()` |
| Editor silent on `/edit` | one-off `EDITOR=code --wait` in that session | Persist `EDITOR` in config/env with the same `--wait` |
| `hermes config set` warns on a TUI key such as `display.mouse_tracking` | ignore the notice (the value still saves and is read for the TUI) | Report upstream if a TUI key stays unrecognized long-term; see `diagnosing-tui` for `/mouse` |
| Cursor/VS Code spinner flood + clipped `> ` prompt in classic CLI | `hermes --tui` avoids the flood for one run | Persist `display.interface: tui` + `display.tui_status_indicator: ascii` + `display.details_mode: collapsed` + `display.mouse_tracking: wheel` + `HERMES_TUI_INLINE=1` (see §5.9) |

When a workaround is temporary, say what "done" looks like: the upstream issue to watch, or
the version that carries the fix.

## 6c. Gateway session creation timeout

If `hermes` (classic CLI/agent) reports `Error: Gateway did not answer session.create`,
the gateway RPC exceeded its budget. On a loaded host this is usually host
pressure, not a Hermes defect. On POSIX or WSL, run the `diagnosing-host-pressure`
probe first. If it exits `1`, relieve pressure, re-run the probe, and restart the
gateway only after it exits `0`, then retry. If it exits `0` and Hermes still
fails, the cause is Hermes-side: follow `diagnosing-plugins` or
`diagnosing-gateway`. If it exits `2`, read the partial output; an unavailable
signal does not show a healthy host. On native Windows, the probe does not run;
do not use it. Do not restart the gateway blindly. (Added 2026-11-04 from a live
host finding; not an upstream source recheck.)

## 7. Cross-platform guardrails

- Prefer config/env fixes (work identically on POSIX); keep path logic runtime-resolved via `HERMES_HOME`
- Never hardcode `C:\...` paths in skills/plugins - use `%LOCALAPPDATA%\hermes` on Windows, `~/.hermes` elsewhere
- Shell commands issued by the agent keep POSIX syntax (the Windows backend is Git Bash); mind MSYS2 path translation and `core.autocrlf`
- Skins degrade to `default`; unknown indicator styles fall back; when Node can't be resolved the TUI exits with a `hermes --cli` pointer (no silent fallback) - preserve these behaviors
- Terminal persistence (`persistent_shell`, `TERMINAL_*` env carry) means shell state survives across commands — a "clean shell" repro must start a fresh non-persistent session or the old env leaks in. Local backend: exported-variable carry follows `TERMINAL_LOCAL_PERSISTENT` (default true, `tools/terminal_tool.py`); set it `false` before creating the terminal environment. `persistent_shell` is the config key, not the local switch.
- Dashboard browser-open (`hermes_cli/web_server_lifecycle.py::_maybe_open_browser`) fires `webbrowser.open` (the macOS `open` helper) in a daemon thread 1s after serve, mapping `0.0.0.0`/`::` to `127.0.0.1` and appending `?profile=` when set — open failures are swallowed, so "dashboard served but no browser, no error" means retry the printed URL manually and pass `--no-open` to silence it. The headless-Linux skip (no `DISPLAY`/`WAYLAND_DISPLAY`) never triggers on macOS.

## Verification

```powershell
hermes --version; hermes doctor
hermes config path
hermes config get display
hermes guide update  # only if the hermes-guide plugin is enabled; tap-only installs cannot run it — use the manual stale-lock checks in §1 instead
hermes skills list
# in classic CLI: /indicator ascii; /skin slate; /exit
```

Deep-dive reference: the original investigation with screenshot forensics,
redundancy analysis, and full source evidence lives at
`references/hermes-cli-tui-windows-investigation.md` in this skill's directory.

## Report

This skill diagnoses classic CLI issues — rendering artifacts, themes/skins, busy indicators, encoding, and launch/resume. When you run the diagnostic workflow, present findings in the standard format below.

### Summary
Your classic CLI shows unreadable tofu faces for the busy indicator because conhost has no font fallback for the default kaomoji style. Switching to ASCII indicator style fixes the readability.

### Findings
| Severity | What | Evidence |
|---|---|---|
| MEDIUM | Default kaomoji busy indicator renders as tofu on conhost | Screenshot shows `□□□` instead of animated faces; conhost has no font fallback |

### Recommended Fix
Run `/indicator ascii` in the classic CLI for an immediate fix, then persist by adding `display.tui_status_indicator: ascii` to `config.yaml`.

### References
- `$HERMES_HOME/config.yaml` — the `display:` block
- `hermes_cli/skin_engine.py` — skin loading logic
- `hermes_cli/stdio.py` — `configure_windows_stdio()` UTF-8 handling

---

*Facts re-verified 2026-11-09 against upstream source at commit `f97608f178d1ffeca59860195ab7da295f7c8e5f` (skin_engine.py, config_defaults.py, stdio.py, gateway.py, hermes_cli/cli_tui_mixin.py, hermes_cli/update_cmd.py, hermes_cli/doctor_platform.py, hermes_cli/active_sessions.py, hermes_cli/cli_voice_mixin.py), upstream docs (installation.md), the issue tracker (classic CLI rows, states noted), and the live Windows 10 desktop install (v0.21.1, `.venv`, Windows Terminal 1.24.12741). Classic CLI gateway path verified 2026-11-09 against the runtime checkout (`cli.py` HermesCLI, `gateway_agent.py`, `gateway_connection.py`, `gateway_client.py`): classic CLI is gateway-backed, and the spinner path is `cli_tui_mixin.py` through to `gateway_client.py` `rpc`. Cursor/VS Code spinner-flood playbook carried from diagnosing-cli-tui, re-verified 2026-11-06 against commit `9bda154d`. Split from diagnosing-cli-tui (#467, #468, #469); POSIX procedure expanded from the Windows baseline only where the source paths are the same. Re-verify before reuse.*
