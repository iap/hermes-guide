# NixOS WSL Plugin Verification

This reference covers verifying Hermes plugin installations on NixOS WSL2 — the
differences from standard installs, the Nix bundle vs standard installer plugin
targets, and the diagnostic checklist.

## NixOS WSL Hermes Install Types

| Type | Code Location | Plugin Target | Mutable? |
|---|---|---|---|
| **Standard (reviewable two-step)** | `$HERMES_HOME/hermes-agent/` (git checkout) | `$HERMES_HOME/plugins/` | ✅ Yes |
| **Nix flake / NixOS module** | `/nix/store/...-hermes-agent-<ver>/` (immutable) | `$HERMES_HOME/plugins/` | ❌ Nix store code is immutable, but plugin dir is mutable |

**Key finding**: On a Nix-installed Hermes, `hermes plugins install` writes to `$HERMES_HOME/plugins/` (mutable, correct target) — NOT the Nix store. The `--dry-run` flag does NOT exist for `hermes plugins install`; use `hermes plugins list` and `ls -la "$HERMES_HOME/plugins/"` to verify the target instead.

## Verification Checklist

```bash
# 1. Start WSL if not running
wsl -d nixos

# 2. Check Hermes version and install method
hermes --version
# Look for: "Install method: nix" vs "Install method: standard"
# Note: Nix install reports version 0.0.0 — this is expected, not an error

# 3. Check plugin requirements vs Hermes version
hermes plugins list
# Check plugin.yaml requires_hermes floor
# WARNING: Nix Hermes reports 0.0.0, which fails requires_hermes >=0.21 checks
# in the plugin catalog. Plugin loading still works (plugin.yaml override),
# but `hermes plugins update` is blocked by the catalog version check.

# 4. Verify plugin install target (no --dry-run flag exists)
hermes plugins list | grep <plugin-name>
ls -la "$HERMES_HOME/plugins/<plugin-name>"/
# Target should be $HERMES_HOME/plugins/ (mutable, correct)
# If it's in /nix/store/, that's the catalog metadata only — not the actual plugin

# 5. Check install sync status
hermes doctor
# If "install out of sync" (ffmpeg/node/ripgrep):
#   Nix route: nix profile upgrade hermes-agent && hermes pm install
#     (hermes pm install downloads ffmpeg/node/ripgrep to ~/.hermes/tools/)
#     (Python venv sync may fail on Nix — uv.lock not in Nix store — but external tools install fine)
#   Standard route: hermes self-update --reinstall-tools

# 6. Verify plugin loads
hermes <plugin-command>  # e.g., hermes guide
```

## Plugin Requirements Check

Plugin `plugin.yaml` fields that matter:
- `requires_hermes`: Loader-enforced floor (pre-import skip if unsatisfied)
  - On NixOS WSL, Hermes reports 0.0.0 — plugin.yaml can comment this out as a dev override,
    but the plugin catalog (remote) still enforces it, blocking `hermes plugins update`
- `python_dependencies`: Must be pure Python wheels or available in PM store
- `capabilities`: Declared capabilities must be supported by Hermes version

**Enforcement point**: `hermes_cli/plugins_manifest.py::requires_hermes_error()`
compares running version using a simplified three-segment integer tuple
(not PEP 440); unparseable versions are permissive. Unsatisfied → plugin skipped
before import, error recorded.

## NixOS WSL Specific Gotchas

1. **WSL VM must be running** — `WSAETIMEDOUT` means `wsl -d nixos` hasn't booted
2. **nix-ld required** for any native module loads (`programs.nix-ld.enable = true`)
3. **Python version mismatch** — shell shows system Python (3.13.12), Hermes uses nix-packaged (3.14.6) — PM-era isolation handles this, do NOT force-align
4. **No compiler by default** — native builds fail; use prebuilt wheels or Nix flake overlay
5. **Dual install coexistence** — Windows standard install + NixOS Nix install share `$HERMES_HOME` but have separate code/checkouts; shims in `~/.local/bin` point to one
6. **Nix version reporting** — Hermes reports 0.0.0 on Nix, which fails plugin catalog version checks but doesn't block plugin loading (plugin.yaml override works)
7. **`hermes pm install` on Nix** — installs external tools (ffmpeg, node, ripgrep) to PM store successfully, but fails at Python venv sync because `uv.lock` is not in the read-only Nix store. External tools are installed; sync warning is cleared.

## Version Override Mechanism (tested, insufficient)

The Nix wrapper sets `HERMES_INSTALL_ROOT` to `/nix/store/.../share/hermes-agent/`,
where `install-stamp.json` lives with `baseVersion: "0.0.0"`. Overriding this env var
to point at a writable directory with a patched stamp makes `hermes --version` report
the patched version (e.g., 0.21.0). However, this alone does NOT fix `hermes plugins update`:

- **Version check**: ✅ Passes with patched stamp
- **Plugin catalog check**: ✅ Passes (no more "needs >=0.21" error)
- **Python venv sync**: ❌ Still fails — `uv.lock` not in Nix store (read-only)

**Conclusion**: Version patching is a partial fix that creates a maintenance burden.
The standard installer is the only clean solution for plugin development on WSL.

## What the Official Docs Say About Nix and Plugins

From the Hermes Nix setup docs (Tier 2 platform — "For a supported setup, use one of the standard installation paths"):

- **uv2nix, not runtime uv**: "every Python dependency is a Nix derivation built by uv2nix... There is no runtime pip, no venv activation, no npm install."
- **Plugin management on NixOS module is declarative**: the NixOS module uses `extraPlugins` and `extraPythonPackages` — NOT `hermes plugins install/update` CLI — because CLI config commands are blocked by the `HERMES_MANAGED` guard. The CLI flow also requires runtime venv sync via `uv.lock`, which the Nix build doesn't ship.
- **Nix flake installs (`nix run` / `nix profile install`) DO support the standard CLI**: after install, `hermes plugins install <name>` works for catalog plugins, and `hermes plugins update` works for unpinned plugins. The NixOS module is the only path where the CLI is blocked.
- **Container mode** (`container.enable = true`): Runs in an Ubuntu container where apt/pip/npm self-installs persist across restarts — an alternative for plugin development if you stay on Nix.
- **No compiler by default**: Native builds fail; use prebuilt wheels or Nix flake overlay.

This confirms: on the **NixOS module** (not Nix flake), `hermes plugins install/update` cannot work because the PM system's Python venv sync requires `uv.lock` in the repo root (not shipped in the read-only Nix store) and CLI config commands are blocked by the `HERMES_MANAGED` guard. The version check (0.0.0) is a secondary blocker. For Nix flake installs, the standard CLI works normally.

## Recommended Workflow for Plugin Development on NixOS WSL

If developing plugins (iterating on a repo like `hermes-guide`):

1. **Prefer standard installer in WSL** for mutable plugin development:
   ```bash
   # Two-step (reviewable): download, review, then run
   installer=$(mktemp)
   curl -fsSL https://hermes-agent.nousresearch.com/install.sh -o "$installer"
   less "$installer"
   bash "$installer" && rm -f "$installer"
   ```
   This gives `~/.hermes/plugins/` that `hermes plugins install/update` writes to,
   with proper version reporting (satisfies requires_hermes >=0.21).

2. **Symlink your dev repo** into `~/.hermes/plugins/<name>/` for live iteration

3. **Or use Nix flake overlay** for declarative plugin management (reproducible, but slower iteration)

4. **If staying on Nix**: update plugins via a pinned declarative source in your Nix config (`extraPlugins` with `pkgs.fetchFromGitHub` pinned to a `rev` + `hash`), then `nixos-rebuild switch`. Direct `git pull` in `~/.hermes/plugins/<name>/` is an explicit **development-only** path that bypasses the install/update security scan and re-pinning controls.

## Debugging Failed Plugin Loads

| Symptom | Likely Cause | Fix |
|---|---|---|
| Plugin installed but not loading | `requires_hermes` floor not met | Upgrade Hermes or check version |
| `hermes plugins update` blocked | NixOS module (HERMES_MANAGED + no uv.lock) | Use pinned declarative source + `nixos-rebuild switch`; or switch to standard install for plugin dev |
| `hermes pm install` Python venv sync fails | uv.lock not in Nix store (read-only) | External tools still install; sync warning cleared |
| Native dep build fails | No compiler available | Add to nix-ld libs or use prebuilt wheel |
| WSAETIMEDOUT on any command | WSL VM not started | `wsl -d nixos` on Windows host |

## Cross-Reference

- `installing-hermes` SKILL.md — NixOS/WSL2 gotchas section
- `diagnosing-path` — PM-era venv layout, `project_venv_dir()`
- `hermes-configuration-guide` — plugin configuration, `hermes config path`
- Upstream: `hermes_cli/plugins_manifest.py` (loader), `hermes_cli/version_info.py` (version)

---

*Verified 2026-10-29 against live NixOS WSL install (Hermes v0.0.0 Nix flake, nix-ld enabled, hermes-guide v0.8.12 active at ~/.hermes/plugins/hermes-guide/, install sync fixed via nix profile upgrade + hermes pm install; version patch tested and confirmed insufficient)*