---
name: diagnosing-path
description: "Diagnose Hermes Agent path issues — the dual-venv layout (.venv/venv), how to detect which venv is active, the canonical resolution order, and best practices for code, scripts, and documentation that reference paths, including the PM-era no-in-tree-venv case."
version: 1.5.9
metadata:
  hermes:
    tags: [hermes, path, venv, python, troubleshooting, guide]
    related_skills: [hermes-configuration-guide, diagnosing-cli-tui, installing-hermes]
---

# Hermes Agent Path Diagnostics

This guide explains the dual-venv layout in Hermes Agent, how to detect which virtual environment is active, and the canonical resolution order. It applies to any code, script, or documentation that needs to reference paths in a Hermes Agent checkout.

> **Disambiguation**: if the desktop app's backend resolution is wrong (not a venv/interpreter issue), see `diagnosing-desktop`. If the install itself is broken (not just a path reference), see `installing-hermes`.

## The Situation

Hermes Agent has a **dual-venv layout**: two directories can exist at the project root, both valid, and resolution is inconsistent across call sites because not every site uses the resolver.

| Directory | Origin | Python | Who writes it |
|---|---|---|---|
| `venv/` | `python -m venv venv`; the pre-pm curl installer | 3.11.x on pre-pm installs (observed: 3.11.15 on a Linux/WSL install); PM-era installs keep the dependency environment outside the checkout (locked Python 3.14.7) | The pre-pm installers — the resolver winner when an in-tree venv exists |
| `.venv/` | `uv venv` (uv's default) | Whatever `uv` provisions — verified 3.13.14 (uv 0.11.21) on a Windows desktop-app install | uv / uv-based tooling |

The Python version does **not** identify the layout: upstream supports `requires-python = ">=3.11,<3.15"` (the ceiling was raised from `<3.14` during the 2026-09 bundled-runtime work), and `uv` resolves its own interpreter, so a `.venv` can span 3.11–3.14 depending on `uv`'s configuration. Both layouts were observed in the wild in the same week (mid-2026, before the pm rework): the installer wrote `venv/` (Python 3.11.15) on a Linux/WSL host while the desktop app shipped `.venv/` (Python 3.13.14) on Windows. PM-era installs don't keep an in-tree venv at all: the dependency environment lives outside the checkout (locked Python 3.14.7) and PM removes a legacy in-tree venv once a generation is committed — the in-tree rules below matter for dev checkouts and pre-pm installs.

Both can coexist. When they do, **`venv` wins**: upstream's own resolver picks it first, "matching what the installers write." Note the trap: "current tooling" (`uv` → `.venv`) and "resolver winner" (`venv`) are *different* directories — a script that scans `.venv` first can therefore resolve a different interpreter than Hermes core does on the same checkout.

**Why this happened:** Older installs and some documentation used `python -m venv venv`. When uv became the default package manager, `uv venv` created `.venv`. Migration scripts didn't remove the old `venv/`, so both persist.

**Current state upstream:** a resolver exists — `hermes_constants.py::project_venv_dir(project_root)` (added 2026-08-19, commit `7a94b1f`, verified in upstream history). For a checkout with an in-tree venv it resolves `venv` **before** `.venv`; the docstring still reads *"``venv`` wins when both exist, matching what the installers write."* and the candidate scan checks `is_dir()` only (no `pyvenv.cfg` validation). It also covers **out-of-tree installs** (`$HERMES_HOME/venvs/<name>`, the layout the shipped Windows launchers assume): with no in-tree directory it falls back to the **running interpreter's venv** — only when this module was loaded from that checkout, the prefix is a venv whose python exists, and the venv's own `hermes-agent` distribution records the checkout as its install source (`direct_url.json`; added 2026-09-25, commit `f9f235e` — *never adopt another install's venv for a checkout*). A foreign root still resolves to `None`.

**The failure mode is call sites that bypass that resolver, not the absence of one.** Before `7a94b1f`, exactly **11** sites in `hermes_cli/` hardcoded `PROJECT_ROOT / "venv"` (`update_cmd.py` 7, `gateway.py` 2, `main.py` 2 — counted from the parent commit). Two canonical bypasses have since been retired upstream: `hermes_cli/main_install_repair.py::_venv_scripts_dir()` now resolves through `project_venv_dir()` + `venv_bin_dir()` and finds both layouts, and the service-unit PATH builder — `hermes_cli/gateway_service_unit.py::_build_service_path_dirs` — no longer persists venv paths at all ("Python and dependency executable paths are selected at boot, not persisted"; post-tag the builder moved to hermes_cli/gateway.py). The canonical tracker for this class was **#79542** (*"`_venv_scripts_dir()` only checks venv, not .venv, causing all Windows update protections to silently skip"*), closed after the resolver fix landed in main.

## Detection — Is a venv active?

When Python is running inside a virtual environment:

```python
import sys

def is_venv():
    """Return True if running inside a virtual environment."""
    return (
        hasattr(sys, "real_prefix")  # virtualenv
        or (hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix)  # venv
    )

def active_venv_path():
    """Return the path to the active venv, or None if not in a venv."""
    if not is_venv():
        return None
    return sys.prefix
```

Shell detection:

```bash
# POSIX
if [ -n "$VIRTUAL_ENV" ]; then
    echo "Active venv: $VIRTUAL_ENV"
else
    echo "No active venv"
fi

# Windows PowerShell
if ($env:VIRTUAL_ENV) {
    Write-Output "Active venv: $env:VIRTUAL_ENV"
} else {
    Write-Output "No active venv"
}
```

## Detection — Which venv directories exist?

```python
from pathlib import Path

def find_venv_dirs(project_root: Path) -> list[Path]:
    """Return existing venv directories in resolution order.

    Stricter than the upstream resolver: this lists only *valid* venvs
    (pyvenv.cfg required), while project_venv_dir() accepts is_dir() alone.
    """
    candidates = [project_root / "venv", project_root / ".venv"]
    return [c for c in candidates if c.is_dir() and (c / "pyvenv.cfg").exists()]
```

## Resolving a venv — two different questions

These are **not** one resolution order. Keep them separate; conflating them is how scripts and models end up describing behavior upstream does not have.

### A. Which venv is ACTIVE? (for code running under an interpreter)

1. **`VIRTUAL_ENV`** env var — if set, that is the active venv.
2. **`sys.prefix`** vs `sys.base_prefix` — if they differ, Python is running inside a venv.

This is detection, not project resolution. Upstream's `project_venv_dir()` never reads `VIRTUAL_ENV`; it consults `sys.prefix` only in its out-of-tree fallback (B.3) — for an ordinary in-tree checkout the two questions stay independent.

### B. Which venv DIRECTORY does the project have? (upstream's resolver)

`project_venv_dir(project_root)` — import it; do not re-implement:

1. **`venv/`** — checked first.
2. **`.venv/`** — only when `venv/` is absent.
3. **The running interpreter's venv** — out-of-tree installs only (`$HERMES_HOME/venvs/<name>`): the module must have been loaded from that checkout, the prefix must be a venv with a usable python, and the venv's `hermes-agent` distribution must record the checkout as its install source (`direct_url.json`) — this stops a dev checkout's update from rewriting another install's venv (upstream commit `f9f235e`).
4. **`None`** — no venv found anywhere. Callers decide if that is an error.

The in-tree candidate scan is `is_dir()` only — no `pyvenv.cfg` validation, no `VIRTUAL_ENV` lookups; the out-of-tree fallback is the provenance-checked branch above.

### C. Script that needs the best available answer

Active venv first (§A), then the project's candidate dirs (§B) — copy
`references/resolve_venv.py` (a superset of upstream for script use; prefer
importing `project_venv_dir()` when Hermes core is importable).

### D. PM-era installs: ask the package manager

On a **PM-era install (2026-09 onward)** there is no in-tree venv:
`project_venv_dir()` can return `None` while a dependency environment exists
under `$HERMES_HOME/installs/<key>/environments/`. Ask PM instead —
`committed_venv(root)` for the directory (or `None`), `project_python(root)`
for the executable (never `None`; not interchangeable, and the latter can name
a path that does not exist). Full table, traps, and the three-outcome handling:
`references/pm_era_venvs.md`.

## Cross-platform path construction

**Never hardcode `venv/bin/` or `venv/Scripts/`.** Use `venv_bin_dir()` from `hermes_constants.py`:

```python
from hermes_constants import venv_bin_dir, project_venv_dir

venv = project_venv_dir(Path("/path/to/hermes-agent"))
if venv:
    python_path = venv_bin_dir(venv) / "python"
    # POSIX: /path/to/hermes-agent/venv/bin/python    (pre-pm installer layout)
    #         /path/to/hermes-agent/.venv/bin/python  (uv layout, when venv/ absent)
    # Windows: C:\path\to\hermes-agent\venv\Scripts\python.exe
```

Upstream's helpers take a `windows=` keyword (`venv_bin_dir(venv_dir, *, windows=None)`, `venv_python_path(venv_dir, *, windows=None)`) so Windows paths can be exercised on any host — and they return a path **unconditionally**: a missing venv is the caller's decision, not the helper's. If `venv_bin_dir` is not available (outside Hermes core), replicate the logic:

```python
from pathlib import Path
import sys

def venv_bin_dir(venv_path: Path) -> Path:
    """Return the binary directory for a venv (Scripts/ on Windows, bin/ elsewhere)."""
    return venv_path / ("Scripts" if sys.platform == "win32" else "bin")
```

## Platform Reference

| Platform | Venv directory | Binary subdirectory | Python executable |
|---|---|---|---|
| macOS / Linux | `venv/` or `.venv/` | `bin/` | `python` |
| Windows | `venv/` or `.venv/` | `Scripts/` | `python.exe` |

## Best Practices

### For scripts

```python
# GOOD: resolve dynamically
from pathlib import Path
import sys

def get_venv_python(project_root: Path) -> Path | None:
    venv = resolve_venv(project_root)
    if venv is None:
        return None
    bin_dir = venv / ("Scripts" if sys.platform == "win32" else "bin")
    return bin_dir / ("python.exe" if sys.platform == "win32" else "python")

# BAD: hardcoded path
python = project_root / "venv" / "bin" / "python"  # Breaks on Windows, breaks on .venv-only checkouts
```

### For documentation

- **Do:** Reference `hermes config path` as the ground-truth command.
- **Do:** On a checkout that carries an in-tree venv, resolve via `project_venv_dir()` from `hermes_constants.py` (it picks `venv/` before `.venv/`). That resolver only looks in the project root and `sys.prefix`, so on a PM-era install it returns `None` — see **D. PM-era installs** for the PM API to call instead (`committed_venv()` vs `project_python()`, and the `RuntimeError` that means corrupt state rather than a missing one).
- **Do:** Mention both layouts — `venv/` (installers) and `.venv/` (uv).
- **Don't:** Hardcode either name alone, or document an activation path without noting the other layout.

```bash
# GOOD: probe order in documentation — venv first, matching project_venv_dir()
source venv/bin/activate 2>/dev/null || source .venv/bin/activate 2>/dev/null || echo "No venv found"

# BAD: hardcoded single layout
source venv/bin/activate
```

### For CI and automation

```yaml
# GOOD: check both, venv first (matches project_venv_dir())
- name: Activate venv
  run: |
    if [ -d venv ]; then source venv/bin/activate
    elif [ -d .venv ]; then source .venv/bin/activate; fi
```

### For plugins and skills

Plugins run inside the Hermes installation's venv. Don't assume the venv name — use `sys.prefix` or `sys.executable`:

```python
import sys

# GOOD: wherever Python is running from
python_exe = Path(sys.executable)

# BAD: assuming .venv in the CWD
python_exe = Path.cwd() / ".venv" / "bin" / "python"  # May not be the running venv
```

## Troubleshooting

### "No module installed" but the package exists

The wrong interpreter is answering. On checkouts that carry venvs, check:

```bash
which python        # Should point inside .venv/ or venv/ (checkout layouts)
python -c "import sys; print(sys.prefix)"  # Confirms active venv
```

On a PM-era install (2026-09 onward) there is no in-tree `venv/` and no `python` shim — `which python` just reports your shell's Python, which Hermes does not use. Check the interpreter the launcher runs instead: the shims exec the durable launcher bound to the PM-store Python, and `hermes --version` prints the install directory and method. The dual-layout checks in this skill apply to checkouts that still carry venvs.

### Both `.venv/` and `venv/` exist

Upstream's `project_venv_dir()` resolves `venv/` first, so scripts mirroring Hermes core pick `venv/` — which may be the stale one if this checkout is uv-managed. Don't guess: find the live one (e.g. `venv/bin/pip show hermes-agent` vs `.venv/bin/pip show hermes-agent`, or `hermes doctor`), then delete the stale directory to remove the ambiguity.

### A protection or PATH feature silently does nothing

Symptom: an update/protection/preflight step reports success but never ran. Cause: a **venv-only** check on a **`.venv`-only** checkout — the class tracked by **#79542**; its canonical instances (`_venv_scripts_dir`, the service-PATH builder) were fixed or retired upstream during 2026-09. Confirm the layout first (`ls -d venv .venv`), then treat any venv-name-specific check as suspect and resolve through `project_venv_dir()`.

### Windows: "python" not found

Windows venvs use `Scripts\python.exe`, not `bin/python`. Use `venv_bin_dir()` or `sys.executable`.

### Every launch replays a full self-update tail

Symptom: each `hermes` invocation prints "finishing an interrupted source update..." (deps, TUI, web UI, desktop) yet the marker never clears. Cause: `$HERMES_HOME/installs/<key>/source-completion-pending` is newer than the install stamp, so the tail is still owed — retries are capped with backoff (up to 6 attempts), after which it waits for an explicit `hermes update`; a dirty checkout (`dirty:true` in the install stamp) also keeps it owed regardless of marker age (`hermes_cli/venv_sync.py`: arm/clear paths). Distinguish one case: if the venv itself is out of sync (`hermes doctor` reports it, or `pm.venv_is_current()` is false), `prepare_launch` may return the store interpreter and relaunch instead of running the tail — restore the PM environment first (`hermes pm install`), close and relaunch Hermes, then run `hermes update`. → Let one run finish uninterrupted (killing it mid-tail re-arms the loop); escape hatch for diagnosis: `HERMES_DISABLE_LAZY_INSTALLS=1` skips the lazy tail entirely.

### Staged toolchain fails verification on an older macOS (dyld `Symbol not found`)

Symptom: the update tail prints staged-entry verification failures naming `dyld` and a missing symbol (e.g. `__libcpp_verbose_abort` from the staged `node`, or a Foundation symbol from `CuaDriver.app`), every launch stays slow, and the marker never clears. Cause: the staged binaries' OS floor is newer than the host — confirm with `sw_vers -productVersion` against `otool -l <staged binary> | grep -A3 LC_BUILD_VERSION` (`minos`). A `minos` above the host version means the toolchain dropped this macOS, not a corrupt download — re-downloading changes nothing. → Check the floor first; then `hermes pm doctor`, and either opt out of the offending component (`hermes pm install --without cua-driver`, the updater's own hint) or stay on the older working toolchain. For diagnosis only, `HERMES_DISABLE_LAZY_INSTALLS=1` skips the lazy tail entirely. Observed 2026-10-16: macOS 12.7.6 host vs staged-node `minos 13.5` (installed `node-20.18.0`, `minos 10.15`, would run — the updater does not select it).

### `No module named 'x._x'` although the package is installed

Symptom: an import that works standalone fails inside Hermes with a missing C-extension submodule. Cause: interpreter/site-packages mismatch — e.g. a stale shim running Python 3.12 while PM forces a 3.14-built dependency tree onto its path; the extension tag doesn't match so the submodule is unresolvable. → Compare the `Python:` line of `hermes --version` across every `hermes` on PATH (`which -a hermes`; check what each shim execs) against the durable launcher (`hermes-agent/.hermes/bin/hermes`, bound to the PM-store Python). Use the durable launcher; refresh or remove stale shims. Never `pip install` into the PM store to work around it — that drifts from the resolved `uv.lock` and PM reports the environment not-current; instead restore with `hermes pm install`, then close and relaunch Hermes before retrying.

## See Also

- `references/venv_detection_patterns.py` — copy-paste-ready detection functions
- Hermes core `hermes_constants.py` — `project_venv_dir()` (the resolver), `venv_bin_dir()` (a thin delegate; the implementation lives in `pm/environments.py`), `venv_python_path()`
- Bug **#79542** — `_venv_scripts_dir()` checked only `venv`, so Windows update protections silently skipped on `.venv` installs (the canonical harm of this split; triaged as a duplicate of **#43250**). The resolver-based fix landed in main (2026-09, both layouts); the issue was still open as of 2026-09-29
- Related history: the venv-bin-dir consolidation — the layout open-coded in seven places using three different Windows predicates, the #76091 fix shipping an eighth copy first — is preserved in upstream's commit history; at head `venv_bin_dir()` delegates to `pm/environments.py`, which owns the implementation.

## Report

This skill diagnoses path issues — the dual-venv layout (.venv/venv), how to detect which venv is active, the canonical resolution order, and best practices for code, scripts, and documentation that reference paths. When you run the diagnostic workflow, present findings in the standard format below.

### Summary
Your script fails with "No module named hermes_agent" because it is using the wrong Python interpreter. The checkout has both `venv/` and `.venv/`, and your script hardcoded `venv/bin/python` which is stale — the active environment is `.venv/`.

### Findings
| Severity | What | Evidence |
|---|---|---|
| HIGH | Script uses stale `venv/bin/python` | `venv/bin/pip show hermes-agent` returns "not installed"; `.venv/bin/pip show hermes-agent` returns the package |
| MEDIUM | Both `venv/` and `.venv/` exist, causing confusion | `ls -d venv .venv` shows both directories; `project_venv_dir()` resolves `venv/` first |

### Recommended Fix
Replace the hardcoded path in your script with a dynamic resolution: `from hermes_constants import project_venv_dir, venv_bin_dir` and use `venv_bin_dir(project_venv_dir(root)) / "python"`. Then delete the stale `venv/` directory to remove the ambiguity.

### References
- `hermes_constants.py` — `project_venv_dir()`, `venv_bin_dir()`
- `pm/environments.py` — `committed_venv()`, `project_python()`
- Bug #79542 — the canonical venv-layout issue

---

*Facts verified 2026-10-05 against upstream source at `5000e2993` (`pm/environments.py` — `project_python()` = `venv_python(selected_venv(root))`, `selected_venv()` = `_recorded_venv() or base_venv()`, `base_venv()` = `payload_venv() or project_venv_dir() or <root>/venv`, `venv_python()` documented as returning a path that may not exist, `committed_venv()` = `_recorded_venv() or payload_venv()`); the PM-era layout and `project_venv_dir()` in-tree order carry a 2026-09-29 check at the same revision (`hermes_constants.py`, `pyproject.toml` `requires-python` `>=3.11,<3.15`); earlier verification 2026-09-14 at `8aa219ef` (`hermes_constants.py`, `hermes_cli/gateway_service_unit.py`, `pyproject.toml`); the gateway-bypass citation moved to `gateway_service_unit.py` at `2f6170bf` (2026-09-22, drift #103) and again to `hermes_cli/gateway.py` at `5000e299` (2026-09-29, drift #123 — the service-PATH bypass retired); re-checked 2026-10-12 against upstream main (`53bc70c5`): the old service-unit module is gone and the builder lives in hermes_cli/gateway.py ("selected at boot, not persisted"); upstream issue tracker (#79542 closed, #76091 closed, #92376 unrelated to venv layout); live layouts on two hosts (mid-2026 observations): a Linux/WSL installer install (`venv/`, Python 3.11.15, pre-pm) and a Windows desktop-app install (`.venv/`, Python 3.13.14, uv 0.11.21); re-checked 2026-09-29 for PR #124: PM-era installs keep the dependency environment outside the checkout (locked Python 3.14.7) and remove a legacy in-tree venv once a generation is committed. The `project_python()` fallback was additionally confirmed by EXECUTION on 2026-10-05, not by reading alone: in a temp install root with no committed generation, `committed_venv()` returned `None` while `project_python()` returned `<root>/venv/bin/python`, which does not exist; with a generation recorded both returned the committed environment, and a malformed record raised `RuntimeError` from both. Verified 2026-10-13 on a PM-era macOS install: the still-owed update tail (`source-completion-pending` newer than the install stamp, capped retries with backoff in `hermes_cli/venv_sync.py`, `HERMES_DISABLE_LAZY_INSTALLS=1` escape hatch) and the stale-shim ABI mismatch (`No module named 'x._x'` from a 3.12 shim forced onto 3.14 site-packages; durable launcher bound to store Python). Staged-toolchain OS-floor note verified 2026-10-16 (macOS 12.7.6 host vs staged-node `minos 13.5` via `otool`/`sw_vers`; `pm install --without` opt-out per the updater's own hint). Re-verify before reuse.*
