---
name: installing-hermes
description: Install, reinstall, upgrade, and uninstall Hermes Agent on Linux/WSL2 (NixOS included) — the four install routes, what each creates on disk, config bootstrap, and the gotchas that bite.
version: 1.0.0
metadata:
  hermes:
    tags: [hermes, installation, wsl2, nixos, upgrade]
    related_skills: [hermes-configuration-guide, diagnosing-path, diagnosing-cli-tui]
---

# Installing Hermes

The four install routes for Hermes Agent on POSIX/WSL2 machines — what each creates
on disk, how the layout evolves after first run, and the failure modes that bite
(worked example: NixOS WSL2). For diagnosing a *broken* install afterwards, pair with
`diagnosing-path` (venv resolution) and `hermes doctor`. `hermes config path` resolves the active
config file. For the code location, check what the `hermes` shim execs, or run
`hermes --version` — it prints the install directory and method.

## The four routes

| Route | Command | Code lands in | Shims/PATH | Tracks |
|---|---|---|---|---|
| Standard (POSIX/WSL2) | `curl -fsSL https://hermes-agent.nousresearch.com/install.sh \| bash` | `$HERMES_HOME/hermes-agent` (checkout + venv) | `~/.local/bin/{hermes,hermes-agent,hermes-acp}` | `main` (installer re-run = update) |
| Desktop app (macOS/Win) | download from hermes-agent.nousresearch.com | `%LOCALAPPDATA%\hermes\hermes-agent` (Win) | app-managed | app releases |
| Nix flake | `nix run` / `nix profile install`, or the NixOS module | `/nix/store/...-hermes-agent-<ver>` (immutable) | profile-managed | flake pin |
| PyPI | `uv tool install hermes-agent` / `pip install hermes-agent` | uv/pip tool dir | tool bin dir | PyPI release |

All routes share one data home: `$HERMES_HOME` (POSIX default `~/.hermes`; native
Windows `%LOCALAPPDATA%\hermes`). The installer treats `$HERMES_HOME` as data —
a re-install or upgrade does not touch `config.yaml`, memories, sessions, or plugins.

## What the standard route creates

```
~/.hermes/
├── hermes-agent/          # git checkout of the source (tracks main) + venv/
│   └── venv/bin/python    # the interpreter the shims exec
├── config.yaml            # default template on first run (see config bootstrap)
├── plugins/  skills/  hooks/  cron/  memories/  sessions/  logs/
└── gateway_state.json     # appears once a gateway has run
~/.local/bin/{hermes,hermes-agent,hermes-acp}   # shims → the venv interpreter
```

Prerequisites: `git`, `curl`, `xz` on the PATH — the installer auto-provisions
everything else (uv, Python 3.11, Node.js v22, ripgrep, ffmpeg). Native Windows uses
`install.ps1` instead; the Desktop installer bundles the CLI and is the recommended
route on macOS/Windows.

## Config bootstrap — and how the tree diverges

First run writes `config.yaml` as a **default template** (schema marker
`_config_version`, most sections present as commented documentation) and lays out
runtime directories lazily. From there the tree diverges per user action:

| User action | What it creates/mutates |
|---|---|
| Auth apps / pairing | `pairing/` entries, provider credentials (tokens live in `.env` or the platform auth store) |
| Gateway setup | `config.yaml` gateway/platform sections, `gateway_state.json` (code_version, platforms, session_store) |
| Memory | `memories/` content, `logs/curator/` |
| Third-party services | new `config.yaml` sections + provider env keys |
| Skills / plugins / cron / hooks | `skills/`, `plugins/` (+ `.install-metadata.json`), `cron/`, `hooks/` |

Treat every layout description as a snapshot: record the Hermes version, install
method, and date when documenting an install, and re-check against `hermes config
path` before trusting it.

## NixOS / WSL2 gotchas (worked example)

1. **npm step can hang on a non-interactive shell.** The `ui-tui`/`web` workspace
   install pulls in a dependency whose postinstall opens `/dev/tty` to run a cosmetic
   spinner — with no real terminal that write blocks forever. The installer wraps the
   step in `timeout 600`, so it silently times out, retries, and eventually prints
   `✗ npm install failed or timed out; Node.js dependencies were not installed` while
   still exiting 0. Fix: re-run the npm step with `CI=1` — the
   postinstall short-circuits on that variable and the install completes (the npm
   cache makes the retry fast):

   ```bash
   cd "${HERMES_HOME:-$HOME/.hermes}/hermes-agent"
   CI=1 npm install --workspace ui-tui --workspace web --include-workspace-root --silent
   ```

   Always grep the install log for the failure line before declaring success.
2. **No `g++` on NixOS.** Native module builds fail without a compiler; the installer's
   prebuilt `uv`/Python/Node binaries run fine under `nix-ld`. Enable `programs.nix-ld`
   and, if a build step still needs a compiler, prefer the Nix flake route over
   installing a toolchain ad hoc.
3. **The Nix route is best-effort upstream** — the docs recommend the standard paths
   (or Docker) for supported setups and offer a dedicated flake with default and
   smaller package outputs. A Nix-built bundle is an excellent *fallback* binary
   (immutable, independent of the venv), not the primary install path.
4. **tirith is optional.** The pre-exec security scanner is enabled by default in
   config but needs its binary on the PATH; when its install fails the agent records
   the miss (`.tirith-install-failed`) and runs without pre-exec scanning.

## Dual-install coexistence

A Nix bundle and a standard checkout can coexist. Resolution rules that keep them
from fighting:

- Shims live in `~/.local/bin` and point at exactly one install — check what they exec
  before assuming `hermes` maps to the install you mean.
- The Nix bundle's launcher scrubs `PYTHONPATH`/`PYTHONHOME` — do not copy its env
  handling into the standard install's context (and vice versa).
- Keep the venv layout rules from `diagnosing-path` in mind: `venv/` (installer) and
  `.venv/` (uv) can coexist, `venv/` wins.
- Data is shared through `$HERMES_HOME` regardless of route — a plugin or skill
  installed under one binary is visible to the other.

## Update, uninstall, rollback

- **Update (standard route):** re-run the installer — it reuses the existing checkout
  (preserving `.git`) and refreshes the venv; data stays untouched.
- **Uninstall:** remove `$HERMES_HOME/hermes-agent` and the `~/.local/bin` shims;
  `$HERMES_HOME` data is separate — delete it only if you mean to lose sessions,
  memories, and credentials.
- **Rollback:** back up `$HERMES_HOME` before upgrades; the code directory is
  disposable, the data directory is not.
