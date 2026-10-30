---
name: installing-hermes
description: Install, reinstall, upgrade, and uninstall Hermes Agent — the four install routes (Standard POSIX/WSL2 including NixOS, Desktop app, Nix flake, PyPI), what each creates on disk, config bootstrap, and the gotchas that bite.
version: 1.1.4
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
| Standard (POSIX/WSL2) | two-step installer — download, review, then run (below) | `$HERMES_HOME/hermes-agent` (checkout; older installs carry an in-tree `venv/`, PM-era installs use `$HERMES_HOME/tools`) | `~/.local/bin/{hermes,hermes-agent,hermes-acp}` | `main` (`hermes update`; installer re-run = repair) |
| Desktop app (macOS/Win) | download from hermes-agent.nousresearch.com | `%LOCALAPPDATA%\hermes\hermes-agent` (Win; PM-era installs use `$HERMES_HOME/tools`) | app-managed | app releases |
| Nix flake | `nix run` / `nix profile install`, or the NixOS module | `/nix/store/...-hermes-agent-<ver>` (immutable) | profile-managed | flake pin |
| PyPI | `uv tool install hermes-agent` / `pip install hermes-agent` | uv/pip tool dir | tool bin dir | PyPI release (stale at 0.19.0 — not a supported distribution route; use Standard) |

The Standard route as a reviewable two-step — same installer, but you read the script before it executes:

```bash
installer=$(mktemp)                # private temp file - no other local user can touch it
curl -fsSL https://hermes-agent.nousresearch.com/install.sh -o "$installer"
less "$installer"                  # review what will run - this step gates the next one
bash "$installer" && rm -f "$installer"
```

Upstream documents the same installer as a single piped one-liner (curl into bash); the two-step is equivalent, reviewable before execution, and safe on multi-user hosts. `less` is not in the prerequisite list - if it is missing, review with `cat` instead; do not skip the review step.

All routes share one data home: `$HERMES_HOME` (POSIX default `~/.hermes`; native
Windows `%LOCALAPPDATA%\hermes`). The installer treats `$HERMES_HOME` as data —
a re-install or upgrade does not touch `config.yaml`, memories, sessions, or plugins.

## What the standard route creates

```
~/.hermes/
├── hermes-agent/          # git checkout of the source (tracks main); PM removes a
│                          # legacy in-tree venv/ once a generation is committed
├── tools/                 # PM's tool store: python-*/node-*/uv-* slots
├── installs/              # PM's dependency environments (one per checkout) + facts.json
├── config.yaml            # default template at install time (see config bootstrap)
├── plugins/  skills/  hooks/  cron/  memories/  sessions/  logs/
└── gateway_state.json     # appears once a gateway has run
~/.local/bin/{hermes,hermes-agent,hermes-acp}   # shims → the durable launcher in
                                                # hermes-agent/.hermes/bin, bound to
                                                # the PM-store Python
```

Prerequisites: `git` and `curl` on the PATH (`xz` is no longer needed — PM
extracts archives with stdlib `tarfile`). On minimal glibc hosts the bundled
Node.js may also need `libatomic.so.1`, on musl `libstdc++` — a Node.js launch
failure right after install points there, not at Hermes (Python-side failures
have other causes). The installer stages
a pinned `uv`
(from `pm/lock.json`, sha256-verified), bootstraps a tool-only Python, then hands the
checkout to **pm**, which installs the locked runtime (Python **3.14.7**, Node.js
**26.7.0**, ripgrep, ffmpeg; browsers and the computer-use driver are opt-out at
install, re-enabled with `hermes pm install <name>`). Native Windows uses
`install.ps1` instead; the Desktop installer bundles the CLI and is the recommended
route on macOS/Windows. `${HERMES_RUNTIME_DIR}`, when set, redirects the tool
store away from `$HERMES_HOME/tools` — resolve it before assuming paths.

## Config bootstrap — and how the tree diverges

The installer writes `config.yaml` as a **default template** (schema marker
`_config_version`, most sections present as commented documentation) at install
time, and lays out runtime directories (`cron/`, `sessions/`, `logs/`,
`pairing/`, `hooks/`, `image_cache/`, `audio_cache/`, `memories/`, `skills/`)
plus `.env` (mode 600) then — not on first run. From there the tree diverges per user action:

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

> **Plugin verification on NixOS WSL**: see `references/nixos_wsl_plugin_verification.md` for the plugin install target checklist, `requires_hermes` enforcement, and the standard-vs-Nix install plugin target difference.

1. **Node builds run with `CI=1` by design now.** The pre-pm installer's npm
   workspace step — whose postinstall could open `/dev/tty` and hang a
   non-interactive shell — is gone: PM owns node builds and
   `hermes_cli/npm_engine.py` sets `CI=1` itself. The old
   `timeout 600` / `CI=1 npm install --workspace …` workaround and the
   "npm install failed or timed out" error string no longer exist at `5000e2993` —
   if a build still hangs, capture the log and report upstream.
2. **No `g++` on NixOS.** Native module builds fail without a compiler; the prebuilt
   `uv`/Python/Node binaries staged from `pm/lock.json` run fine under `nix-ld`. Enable
   `programs.nix-ld` and, if a build step still needs a compiler, prefer the Nix flake
   route over installing a toolchain ad hoc.
3. **The Nix route is best-effort upstream** — the docs recommend the standard paths
   (or Docker) for supported setups and offer a dedicated flake with default and
   smaller package outputs. A Nix-built bundle is an excellent *fallback* binary
   (immutable, independent of the venv), not the primary install path.
4. **Nix uses uv2nix (build-time only)** — "there is no runtime pip, no venv
   activation, no npm install." Plugin management on the **NixOS module** is
   **declarative** via `extraPlugins`/`extraPythonPackages` (CLI config commands
   are blocked by the `HERMES_MANAGED` guard and runtime `uv.lock` sync is
   unavailable). Nix flake installs (`nix run` / `nix profile install`) DO
   support the standard CLI including `hermes plugins install/update`. Standard
   installer is recommended for plugin development.
5. **WSL VM may need restart** — `WSAETIMEDOUT` on any `wsl -d nixos` command
   means the VM hasn't booted: run `wsl --shutdown` on the Windows host, wait
   5 seconds, then `wsl -d nixos` to start fresh.
6. **Existing fork checkout can become a standard install** — if `~/.hermes/hermes-agent`
   is already a git checkout (e.g., your fork), the standard installer refuses to
   overwrite it. Instead of moving it aside, set up the venv manually using the
   Nix Python 3.14: `cd ~/.hermes/hermes-agent && ~/.nix-profile/bin/python3 -m venv .venv && .venv/bin/pip install -e . && source .venv/bin/activate` (or use `.venv/bin/hermes` directly)
   This gives proper version reporting (from git), `uv.lock` access, and working
   `hermes plugins install/update` — without losing your fork's custom changes.
7. **tirith is gone.** The pre-exec security scanner (`tools/tirith_security.py`) was removed upstream in 2026-10; its config block is replaced by a generic `Security` section plus LSP post-write lint (enabled by default). A `tirith`-era install may still carry `.tirith-install-failed` and stale `tirith_*` keys — harmless leftovers, not active config.

## Dual-install coexistence

A Nix bundle and a standard checkout can coexist. Resolution rules that keep them
from fighting:

- Shims live in `~/.local/bin` and point at exactly one install — check what they exec
  before assuming `hermes` maps to the install you mean.
- The Nix bundle's launcher scrubs `PYTHONPATH`/`PYTHONHOME` — do not copy its env
  handling into the standard install's context (and vice versa).
- Keep the venv layout rules from `diagnosing-path` in mind: on checkouts that carry
  both, `venv/` (pre-pm installer) and `.venv/` (uv) can coexist and `venv/` wins.
- Data is shared through `$HERMES_HOME` regardless of route — a plugin or skill
  installed under one binary is visible to the other.

## Update, uninstall, rollback

- **Update (standard route):** `hermes update` — pulls the latest changes and
  reinstalls dependencies (`--check` previews availability, `--plan` shows the
  per-service restart plan without changing anything). Re-run the installer only
  as repair (broken shims, missing runtime) — it reuses the existing checkout
  (preserving `.git`) and re-syncs PM's dependency environment; data stays untouched.
  If every launch replays the update tail without clearing, the completion
  marker (`$HERMES_HOME/installs/<key>/source-completion-pending`) is still owed —
  retries are capped with backoff, then it waits for an explicit `hermes update`.
  `HERMES_DISABLE_LAZY_INSTALLS=1` skips the tail for diagnosis. Never repair a
  broken dependency by `pip install` into the PM store or a committed environment:
  versions drift from the resolved `uv.lock` and PM reports the environment
  not-current. Resync through PM (`hermes pm install`).
- **Uninstall:** `hermes uninstall` (modes: default keeps config/data; `--full` removes
  everything including `$HERMES_HOME`; `--data` erases only user data — the one mode
  that works on Nix / bundled-app / Docker installs; `--dry-run` previews). Code-side
  removal covers the checkout, the `~/.local/bin` shims, PATH entries, and installer
  tooling. PM's runtime (`$HERMES_HOME/tools` — the shared tool store;
  `$HERMES_HOME/installs` — one dependency environment per checkout) is tooling, not
  data: remove those two directories manually only when no other checkout shares this
  home — deleting the store breaks every install that references it. `--full` takes
  them with the home.
- **Rollback:** back up `$HERMES_HOME` before upgrades; the code directory is
  disposable, the data directory is not.

## Report

This skill diagnoses installation and upgrade failures — broken installs, wrong venv layout, missing prerequisites, and config bootstrap issues. When you run the diagnostic workflow, present findings in the standard format below.

### Summary
Your Hermes install is broken because the PM dependency environment is missing. The `hermes` shim exists but fails to launch because the PM-managed Python runtime is not installed. This happens when the install was interrupted or the PM store was corrupted.

### Findings
| Severity | What | Evidence |
|---|---|---|
| HIGH | PM dependency environment missing | `hermes --version` fails with `RuntimeError: no committed environment`; `$HERMES_HOME/installs/` is empty |
| MEDIUM | In-tree venv may be stale or missing | `ls -d venv .venv` shows neither directory exists on a PM-era install |

### Recommended Fix
Re-run the installer to rebuild the PM dependency environment using the two-step reviewable version above (download to a temp file, review, then execute). The installer reuses the existing checkout and re-syncs PM's runtime. Verify with `hermes --version` and `hermes doctor`.

### References
- `$HERMES_HOME/tools/` — PM's tool store
- `$HERMES_HOME/installs/` — PM's dependency environments
- `scripts/install.sh` — the standard installer
- `hermes_cli/npm_engine.py` — PM npm resolution

---

*Facts re-verified 2026-09-21 against upstream source at commit `cedf4a3d78675283fa93e4e6ea2d6212bf414667`: `scripts/install.sh` (the four-route layout, `$HERMES_HOME` as data — re-install/upgrade preserves `config.yaml`/memories/sessions; `HERMES_HOME` default resolution; the piped one-liner the two-step mirrors; `xz` prerequisite — .tar.xz extraction requires it, #11197; `PYTHON_VERSION="3.11"`; `NODE_VERSION="26"` — corrected this pass: the skill previously said Node.js v22, the installer pins 26 with 22.22+/24.11+/26+ supported; managed uv into `$HERMES_HOME/bin`; git auto-provision attempt) and `scripts/install.ps1` (the native-Windows route); both describe the pre-pm installer. Re-checked 2026-09-29 at `5000e2993`: `PYTHON_VERSION`/`NODE_VERSION` no longer exist in `install.sh`; it stages pinned `uv` into the store slot (`${HERMES_RUNTIME_DIR:-$HERMES_HOME/tools}/uv-<version>-<target>/`, sha256-verified), bootstraps a tool-only Python, then `pm.cli install` owns the exact runtime pin — Python **3.14.7**, Node **26.7.0**, ripgrep **15.2.0**, ffmpeg **9.0.1**; PM-era layout (no in-tree venv — a legacy one is removed once a generation is committed; shims bind the store Python) and the pre-pm npm workspace step retired (`source_build_env` sets `CI=1`). Re-checked 2026-10-12 against upstream main (`53bc70c5`): `tirith_security.py` gone (generic `Security` section + opt-in `lsp.trusted_workspaces` instead); prerequisites are `git` + `curl` only (`stage_prerequisites`, "prerequisites ok (git, curl)") with musl-`libstdc++` / glibc-`libatomic.so.1` gates for the bundled Node.js; `config.yaml` + `.env` (600) install-time bootstrap; `facts.json` under `installs/<key>/`; PyPI stale at 0.19.0. LSP post-write lint enabled by default (`hermes_cli/config_defaults.py`, `lsp.enabled: True`); `trusted_workspaces` extends trust beyond launched/session workspaces (`agent/lsp/manager.py`). Re-checked 2026-10-29 against live NixOS WSL install (Hermes v0.0.0 Nix flake, nix-ld enabled, hermes-guide v0.8.12 at $HERMES_HOME/plugins/hermes-guide/): install sync fixed via `nix profile upgrade` + `hermes pm install` (ffmpeg 9.0.1, node 26.12.1, ripgrep 15.2.0); plugin target verified as `$HERMES_HOME/plugins/` (mutable, correct); version patch tested and confirmed insufficient (uv.lock missing in Nix store); standard install set up at `~/.hermes/hermes-agent/` with venv (Python 3.14) and `pip install -e .`; `hermes plugins update hermes-guide` reaches security scan (139 LOW findings, community source). Nix setup docs (upstream `edfa1c2a`) confirm: NixOS module blocks CLI config commands via `HERMES_MANAGED` guard; Nix flake (`nix run`/`nix profile install`) supports standard CLI including catalog plugins; `requires_hermes_error()` uses simplified 3-segment integer tuple (not PEP 440), unparseable versions are permissive. Re-verify before reuse.*
