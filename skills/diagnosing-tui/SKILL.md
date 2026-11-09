---
name: diagnosing-tui
description: "Diagnose and fix Hermes Agent Node TUI issues (ui-tui Ink app): themes, mouse modes, launch/resume, and rendering on Windows and POSIX. Use for hermes --tui and display.interface: tui."
version: 1.0.2
metadata:
  hermes:
    tags: [hermes, tui, ink, node, windows, troubleshooting, diagnosing]
    related_skills: [hermes-configuration-guide, diagnosing-path, installing-hermes, diagnosing-cli]
---

# Diagnose Hermes Node TUI

Playbook for the modern Node TUI: the React and Ink app in `ui-tui`,
launched as a subprocess of the Python CLI. Use when `hermes --tui`
or `display.interface: tui` is active, or when the Node app
misrenders, truncates, loses mouse, or fails after launch. For
the classic prompt_toolkit CLI, see `diagnosing-cli`.

> **Disambiguation**: if bare `hermes` stayed classic, or `--cli`
> was passed, that is `diagnosing-cli`, not this skill. If the
> desktop app (Electron) fails to launch or shows a blank window,
> see `diagnosing-desktop`. If a `/command` is missing or
> overridden, see `diagnosing-commands`.
> `cli_tui_mixin.py` is prompt_toolkit code and belongs to
> `diagnosing-cli`. This skill owns `main_tui_launch.py` and
> `ui-tui/`.

## 0. Environment baseline (origin machine: one Windows box, re-verified 2026-09-14)

> [!CAUTION]
> This baseline records **one specific Windows machine** — the box this skill was written on. It is **not** a description of your machine. Before applying anything below, confirm the local environment with `hermes config path`, `hermes --version`, and `hermes doctor`; paths, `HERMES_HOME`, shell, and OS differ per machine (on macOS/Linux the **default** home is `~/.hermes` — overridable via `HERMES_HOME` or a named profile; `hermes config path` always prints the active one).

- `HERMES_HOME = %LOCALAPPDATA%\hermes` (native Windows; `~/.hermes` is NOT the active home)
- Shell: Windows PowerShell 5.1; console host: conhost (classic window) or Windows Terminal 1.24.11911 (present on the reference box; a bare Windows 10 box has **only conhost**)
- TUI frontend: Node app `hermes-tui` (React 19 + custom Ink fork), launched as a subprocess of the Python CLI. Node resolution (2026-09): **through PM** — `hermes_cli/main_tui_launch.py::_tui_node_bin` prefers an explicit `HERMES_NODE` binary, else PM's locked Node (**26.7.0** in `pm/lock.json`); a system Node on PATH is deliberately **not** used to run Hermes's JS (`hermes_cli/main_tui_launch.py::_tui_node_bin`, asserted by the path-shape e2e tests). If no Node can be resolved, `hermes --tui` exits with a pointer to `hermes --cli`.
- Ground truth commands: `hermes config path`, `hermes config show`, `hermes --version`, `hermes doctor`

## 1. Launch and resume

```powershell
hermes              # classic CLI by default; launches TUI when display.interface: tui
hermes --tui        # force TUI
hermes --tui -c     # resume latest TUI session (or HERMES_TUI_RESUME=1 / display.tui_auto_resume_recent: true)
hermes --cli        # force classic REPL for one invocation; see diagnosing-cli
```

`display.tui_auto_resume_recent` is **false** (fresh session per launch). If `hermes` ever opens a previous chat instead of a fresh session, check that key or `HERMES_TUI_RESUME=1`; resume on demand with `hermes --tui -c` (`--resume <id>` for a specific session).

User env vars: `EDITOR=code --wait`, `HERMES_TUI_THEME=dark`.

Startup decides with `hermes_cli/main_tui_launch.py::_resolve_use_tui`:
CLI wins, then TUI flags, then no TTY is classic, then env,
then config interface. `_launch_tui` builds argv with
`_make_tui_argv`, runs it with `subprocess.call`, prints a
shell-visible epilogue on exit codes 0 and 130, and exits with
42 to relaunch as `hermes update`.

If the checkout is inconsistent, the launcher reports the
missing workspace. Save local tracked edits first, because
restoring discards them. Only restore when the user approves:

```powershell
git -C <hermes-checkout> status --porcelain -- ui-tui
git -C <hermes-checkout> diff --binary -- ui-tui > $env:TEMP\ui-tui-local.patch
if (-not (Test-Path $env:TEMP\ui-tui-local.patch)) { throw 'backup patch missing' }
git -C <hermes-checkout> restore -- ui-tui
hermes --tui
```

The launcher rebuilds the workspace through PM source build
when it is missing or stale. Git restoration is best-effort
repair of tracked sources: if the restore leaves the directory
still missing, the launcher stops with recovery steps before
the PM build, so a failed restore does not rebuild missing
sources. Do not use a bare npm from PATH on
a PM-era install; the launcher resolves Node through PM.

For a still inconsistent checkout, run `hermes update --force`.

Every `hermes` invocation hanging on an update lock is the
classic CLI stale lock note. See `diagnosing-cli` section 1.
`hermes guide update` automates the PID-liveness verdict where
the install can still launch.

## 2. Slash commands that fix rendering

| Command | Effect |
|---|---|
| `/mouse wheel` | Mouse preset 1000+1006 (scroll + click, no hover). `all` includes 1003 hover - unsupported on conhost. Persist: `display.mouse_tracking` |
| `/details collapsed` | Quiet feed: fold thinking/tools under chevrons. Persist: `display.details_mode` or `display.sections.<section>: collapsed` |
| `/usage` | Token/cost panel. If silent in TUI, see upstream #37637 |
| `/exit` | Quit; conhost should restore a clean prompt (no residual frame) |

## 3. Light and dark detection

Light/dark detection order (upstream `ui-tui/src/theme.ts`, verified 2026-09-14):

1. `HERMES_TUI_LIGHT` — `1/true/yes/on` = light, `0/false/no/off` = dark. **Wins over everything.**
2. `HERMES_TUI_THEME` — named only: `light` or `dark`.
3. `HERMES_TUI_BACKGROUND` — 3- or 6-digit hex (with or without `#`); luminance decides.
4. `COLORFGBG` last field (XFCE / rxvt / Terminal.app profiles).
5. `TERM_PROGRAM` light-default allow-list (currently `Apple_Terminal`).
   Anything undecidable stays **dark**. There is **no OSC 11 probe** — the hex env var is named `HERMES_TUI_BACKGROUND` so a future OSC 11 client could feed it, nothing more. Note `hermes_cli/tips.py` advertises `HERMES_TUI_THEME=light|dark|<hex>`, which the TUI code does not implement; trust the code, and set hex via `HERMES_TUI_BACKGROUND`.)

## 4. Build, install, and resize

- Prebuilt bundle: `HERMES_TUI_DIR` with `dist/entry.js` runs
  directly, with no workspace build.
- Source build: the launcher calls PM source build. Do not use a
  host npm that is not PM-resolved.
- Heap: the launcher sets a generous Node heap below the
  container limit. A flat 8 GB heap past a smaller cgroup limit
  is reaped by OOM with no breadcrumb.
- Resize corruption: a closed upstream issue tracks layout
  corruption on resize. Stable row keys are the proposed fix
  shape; check the linked issue state before re-reporting.

## 5. Windows-specific troubleshooting

1. **WinError 193 (%1 is not a valid Win32 application)**: invoking an extensionless shebang script. Always use the `.cmd` shim (`npx.cmd`, not `npx`).
2. **Config schema drift**: `hermes config set` flags `display.mouse_tracking` and `display.details_mode` as unrecognized - they ARE valid TUI keys (documented); values save and are read anyway. Do not delete them.
3. **ConPTY mouse/selection loss (Windows Terminal)**: Windows Terminal uses ConPTY, which never delivers DEC mouse sequences (confirmed by MSFT maintainer Dustin Howett, microsoft/terminal#376). The TUI's AlternateScreen + mouse tracking swallows the wheel and native text selection. PR #97663 defaults `hermes --tui` to inline mode (primary buffer) on native Windows ConPTY — the same fallback Termux uses. Git Bash/MSYS mintty outside WT is unaffected. Workaround until merge: `HERMES_TUI_INLINE=1`. Opt out with `HERMES_TUI_INLINE=0`. **Additional risk**: microsoft/terminal#19674 documents console mode corruption when mouse tracking + `SetConsoleMode` are combined — no confirmed workaround beyond inline mode.
4. **Ink inline mode**: `HERMES_TUI_INLINE=1` forces the primary buffer. Use it when AlternateScreen plus mouse tracking breaks wheel or selection. Opt out with `HERMES_TUI_INLINE=0`.
5. **Washed-out colors**: chalk falls back to 256-color when `COLORTERM` is unset. Only when the terminal supports truecolor, set it and relaunch (PowerShell: `$env:COLORTERM="truecolor"; hermes --tui`). Do not claim truecolor on a terminal that does not support it.
6. **WSL2 differences**: WSL reports `platform === 'linux'`, so mouse sequences do reach the Linux PTY. The ConPTY workaround is for native Windows only. Do not apply it inside WSL.

## 6. Known upstream issues (check state before re-reporting)

States verified 2026-10-08. `closed` means fixed or declined upstream — check the issue before reinstalling. A linked PR proposes a fix; check its review and release status before relying on it.

| Issue | PR | State | Topic |
|---|---|---|---|
| #25418 | — | closed (not planned) | Terminal resize corrupts TUI layout (Ghostty, iTerm2, ...) — tracked by #24164 |
| #19216 | — | closed | TUI: resize causes infinite scroll/render loop (flicker, duplicated status bar) |
| #12130 | — | open | TUI v2 feature-parity gaps vs the classic CLI (overlays, slash commands, @ refs) |
| #53301 | #53346 | open | TUI pet colors washed out on WSL/Windows Terminal — **cause is chalk falling back to 256-color when `COLORTERM` is unset** (not a Kitty-graphics issue; fix the env, e.g. `COLORTERM=truecolor`) |
| #37637 | — | closed | `/usage` silent in CLI/TUI (worked via Telegram) |
| #86571 | #97663 | open (PR) | TUI mouse wheel + selection fail under Windows Terminal/ConPTY — fix: default inline mode on native Windows ConPTY |
| #96372 | #96410 | open (PR) | TUI chat history clears on terminal resize — fix: stable row keys independent of `cols` |
| #67151 | #128225 | open (PR) | Unicode glyphs render as tofu on conhost/Consolas — fix: degrade glyphs safely on legacy Windows console |

## 6b. Temporary workaround vs permanent fix

| Symptom | Temporary (until a proper fix) | Permanent |
|---|---|---|
| Washed-out colors (#53301) | none needed | Export a truthful `COLORTERM` (e.g. `truecolor`) so chalk stops downgrading to 256-color |
| `hermes config set` warns on a TUI key | ignore the notice (the value still saves and is read) | Report upstream if a key the TUI honors stays unrecognized long-term |
| Mouse wheel dead under Windows Terminal/ConPTY | `HERMES_TUI_INLINE=1` for one run | Keep inline mode on native Windows ConPTY; opt out with `HERMES_TUI_INLINE=0` |

When a workaround is temporary, say what "done" looks like: the upstream issue to watch, or
the version that carries the fix.

## 7. Cross-platform guardrails

- Prefer config/env fixes (work identically on POSIX); keep path logic runtime-resolved via `HERMES_HOME`
- Never hardcode `C:\...` paths in skills/plugins - use `%LOCALAPPDATA%\hermes` on Windows, `~/.hermes` elsewhere
- Shell commands issued by the agent keep POSIX syntax (the Windows backend is Git Bash); mind MSYS2 path translation and `core.autocrlf`
- When Node can't be resolved the TUI exits with a `hermes --cli` pointer (no silent fallback) - preserve this behavior
- Terminal persistence (`persistent_shell`, `TERMINAL_*` env carry) means shell state survives across commands — a "clean shell" repro must start a fresh non-persistent session or the old env leaks in. Local backend: exported-variable carry follows `TERMINAL_LOCAL_PERSISTENT` (default true, `tools/terminal_tool.py`); set it `false` before creating the terminal environment. `persistent_shell` is the config key, not the local switch.

## Verification

```powershell
hermes --version; hermes doctor
hermes config path
hermes config get display
hermes --tui
hermes skills list
# in TUI: /mouse wheel; /details collapsed; /usage; /exit
```

Exit code 42 from the TUI means the launcher hands off to
`hermes update`. A missing or out-of-sync Node install is the
other launch failure: the launcher prints the PM pointer and
exits, do not expect a prompt.

## Report

This skill diagnoses modern Node TUI issues — themes, mouse modes, launch/resume, and rendering. When you run the diagnostic workflow, present findings in the standard format below.

### Summary
Your TUI shows washed-out colors because `COLORTERM` is unset and chalk falls back to 256-color. Setting a truthful `COLORTERM` fixes the readability.

### Findings
| Severity | What | Evidence |
|---|---|---|
| LOW | Washed-out colors on Windows Terminal | `COLORTERM` is unset; chalk falls back to 256-color (issue #53301) |

### Recommended Fix
Export `COLORTERM=truecolor` in your environment for the color issue.

### References
- `$HERMES_HOME/config.yaml` — the `display:` block
- `ui-tui/src/theme.ts` — light/dark detection logic
- `hermes_cli/main_tui_launch.py` — TUI launch and Node resolution

---

*Facts re-verified 2026-11-09 against upstream source at commit `f97608f178d1ffeca59860195ab7da295f7c8e5f` (ui-tui/src/theme.ts, ui-tui/src/app/useMainApp.ts, hermes_cli/main_tui_launch.py, tui_gateway/server.py), upstream docs (installation.md), the issue tracker (TUI rows, states noted), and the live Windows 10 desktop install (v0.21.1, `.venv`, Windows Terminal 1.24.12741); Node resolution re-checked 2026-09-29 at `5000e2993` (TUI node resolves through PM; `pm/lock.json` pins Node 26.7.0). Split from diagnosing-cli-tui (#467, #468, #469); classic prompt_toolkit material moved to diagnosing-cli. Re-verify before reuse.*
