# Cursor / VS Code spinner flood + prompt clip (classic CLI)

Detailed playbook for section 5.9 of `diagnosing-cli`.

## Detection

Note: `display.interface: cli` alone does not establish that the classic CLI ran — `--tui` and `HERMES_TUI=1` both select the TUI before the config value is checked. Verify launch flags and env vars before assuming the classic CLI ran.

Apply this playbook when all three symptoms below are present. On a wider pane the flood alone suffices — the clipped prompt may not appear there.
- launches from Cursor/VS Code's bottom panel
- repeated `ruminating...`/`brainstorming...` lines persisting in scrollback
- first char missing from the next `> ` prompt

Config check: `hermes config get display.interface` returns `cli` (or the key is absent — Hermes may default to the classic CLI in that case; verify against the installed source before relying on this default).

Also check: the launch uses `hermes --cli` (which selects the classic CLI even when config specifies `tui`).

## Measurement

Record the affected pane width and behavior (spinner ticks persist as new lines; next prompt loses its first char). Check width — Git Bash: `tput cols` or `echo $COLUMNS`; PowerShell 5.1: `$Host.UI.RawUI.WindowSize.Width`. Time the phases instead of shrinking the plugin — clone is ~4s (already `--depth 1`), scan is ~17s, an out-of-sync venv sync is ~90s (full `uv lock` + network retries). Dropping bundled assets (already 59K WebP) saves nothing measurable; the fix is the interface switch, not a smaller tree.

## One-run escape hatch (temporary)

**Scrollback note**: When native and Termux modes are off, the Node TUI may emit CSI 3 J (erase scrollback) at startup, even in inline mode. It may also emit this sequence during resize or offscreen full-reset paths. In terminals that honor it, this can erase existing scrollback. Save needed output before launching.

Run with `--tui` for that invocation instead of the classic CLI (preserve `-p` profile and other required args, changing only `--cli` to `--tui`) — the Node TUI does not flood scrollback. `HERMES_SPINNER_PAUSE=1` only pauses the TTY `KawaiiSpinner` animation path and has no effect when the classic CLI drives the spinner through a prompt-toolkit widget (the Cursor/VS Code case), so it is not a reliable escape hatch there. Do not persist `HERMES_SPINNER_PAUSE` — it is not a reliable escape hatch in the Cursor/VS Code case.

## Apply the permanent fix

Before editing, record the original state: the current launcher command, the current `display.interface` value, and whether `HERMES_TUI_INLINE` already exists in `.env`. This lets Roll back restore the launcher and prior state.

After applying the fix, remove `--cli` from any launcher, alias, or script that invokes Hermes — that flag overrides `display.interface: tui` and keeps the classic CLI active. If the alias cannot be edited for this invocation, bypass it (e.g., `command hermes` or backslash-hermes in Git Bash) so the config value takes effect.

```yaml
# config.yaml — merge into the existing display: mapping (do not create a duplicate):
display:
  interface: tui
  tui_status_indicator: ascii
  details_mode: collapsed
  mouse_tracking: wheel
```

```bash
# .env — add once; if HERMES_TUI_INLINE already exists, edit it in place (do not append a duplicate):
HERMES_TUI_INLINE=1
```

Back up the active config first. If the config does not exist yet, create it with `hermes config edit` before backing up, and record that it was originally absent (the qualified rollback rule later governs whether the file may be removed). Note: Hermes treats the entire `EDITOR` value as the executable name (so quoted args or `--wait` flags will not work) — when `EDITOR` includes arguments, record the original value, temporarily set it to a single executable before creating the config, then restore the original `EDITOR` value after config creation. Continue with the existing backup and rollback steps. If it already exists: Git Bash: `cp "$(hermes config path)" "$(hermes config path).bak-$(date +%Y%m%d-%H%M%S)-cli-tui-fix"`; PowerShell: `Copy-Item (hermes config path) "$(hermes config path).bak-$(Get-Date -Format yyyyMMdd-HHmmss)-cli-tui-fix"`. Then, before editing, locate the active config with `hermes config path` (do not assume `config.yaml` in the current directory). Use the same profile throughout — carry its option through `config path`, backup, `env-path`, and verification commands so they all target the same active configuration. Check for duplicate keys — Git Bash/MSYS: `grep -nE "(interface|tui_status_indicator|details_mode|mouse_tracking)" "$(hermes config path)"`; Windows PowerShell 5.1: `Select-String -Path (hermes config path) -Pattern "interface|tui_status_indicator|details_mode|mouse_tracking"` — a duplicate `display.*` key makes Hermes reject the whole file and fall back to last-good config with a warning (new values never apply); remove the duplicate, then `hermes config check`.

## Verify

`hermes config get display` shows all four keys; `hermes config check` is clean (no duplicate-key error).

launch `hermes` **inside the integrated terminal of either Cursor or VS Code** and confirm no scrollback flood, no clipped `> ` prompt, and the status line fits the pane width. Verify all four display values match the prescribed settings (`interface: tui`, `tui_status_indicator: ascii`, `details_mode: collapsed`, `mouse_tracking: wheel`) and check `HERMES_TUI_INLINE` separately (account for `HERMES_TUI=1` if set). PowerShell: check for a wrapper before trusting a bare `hermes` — `Get-Command hermes | Format-List` (a function/alias that adds `--cli` wins); invoke the underlying launcher by full path without that flag, keeping the profile and other required args. Use that same bypass invocation in Verify below when the wrapper would restore the classic CLI. If launching the Node TUI fails with "Node.js is required for the TUI but `node` was not found" (from `_tui_node_bin`), see `diagnosing-tui` §0 (PM-resolved Node) — do not fall back to `hermes --cli` in Cursor.

## Roll back

Do NOT restore the whole backup (it would clobber settings changed after applying the fix). Instead, restore the four `display.*` keys (`interface`, `tui_status_indicator`, `details_mode`, `mouse_tracking`) to their backed-up values and remove any of those keys that were absent from the backup. If the config was originally absent, remove the file only when no unrelated settings have been added or changed since its creation; otherwise retain it to preserve those settings. Record the original launcher command before editing and restore it during rollback (preserves original `--cli` behavior when `display.interface` was already `tui`); for `HERMES_TUI_INLINE` in `.env` (locate via `hermes config env-path`), restore the *previous* value if this section changed an existing setting — `1` is the ConPTY workaround value (see `diagnosing-tui` §5), `0` is a manual opt-out, never the workaround — or remove only the line this section appended if it was newly added — never delete a pre-existing line. Leave the variable in place if any other consumer (diagnosing-tui ConPTY workaround, manual setting) still requires it. Verify rollback: when the variable was absent before the change and no other consumer needs it, zero lines may remain (expected); otherwise exactly one line with the restored value must remain. If `EDITOR` was temporarily overridden during config creation, restore the original value. Re-run `hermes config check`.

## Provenance

Section 5.9 verified 2026-11-05 against installed Hermes source at commit 9bda154d (agent/display.py KawaiiSpinner, shutil.get_terminal_size usage in cli_render.py); timings (clone ~4s, scan ~17s, venv sync ~90s) are single-host measurements from the origin machine, not universal benchmarks.
