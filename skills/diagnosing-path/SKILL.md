---
name: diagnosing-path
description: "Diagnose Hermes Agent path issues — the dual-venv layout (.venv/venv), how to detect which venv is active, the canonical resolution order, and best practices for code, scripts, and documentation that reference paths."
version: 1.2.1
metadata:
  hermes:
    tags: [hermes, path, venv, python, troubleshooting, guide]
    related_skills: [hermes-configuration-guide, diagnosing-cli-tui, installing-hermes]
---

# Hermes Agent Path Diagnostics

This guide explains the dual-venv layout in Hermes Agent, how to detect which virtual environment is active, and the canonical resolution order. It applies to any code, script, or documentation that needs to reference paths in a Hermes Agent checkout.

## The Situation

Hermes Agent has a **dual-venv layout**: two directories can exist at the project root, both valid, and resolution is inconsistent across call sites because not every site uses the resolver.

| Directory | Origin | Python | Who writes it |
|---|---|---|---|
| `venv/` | `python -m venv venv`, and the curl installer | 3.11.x (verified: 3.11.15 on a Linux/WSL install) | The standard installers — the resolver winner |
| `.venv/` | `uv venv` (uv's default) | Whatever `uv` provisions — verified 3.13.14 (uv 0.11.21) on a Windows desktop-app install | uv / uv-based tooling |

The Python version does **not** identify the layout: upstream supports `requires-python = ">=3.11,<3.14"`, and `uv` resolves its own interpreter (3.13 in current tooling), so a `.venv` can be 3.11–3.13 depending on `uv`'s configuration. Both layouts were observed in the wild in the same week: the installer wrote `venv/` (Python 3.11.15) on a Linux/WSL host while the desktop app shipped `.venv/` (Python 3.13.14) on Windows.

Both can coexist. When they do, **`venv` wins**: upstream's own resolver picks it first, "matching what the installers write." Note the trap: "current tooling" (`uv` → `.venv`) and "resolver winner" (`venv`) are *different* directories — a script that scans `.venv` first can therefore resolve a different interpreter than Hermes core does on the same checkout.

**Why this happened:** Older installs and some documentation used `python -m venv venv`. When uv became the default package manager, `uv venv` created `.venv`. Migration scripts didn't remove the old `venv/`, so both persist.

Hermes Agent has a **dual-venv layout**: two directories can exist at the project root, both valid, and resolution is inconsistent across call sites because not every site uses the resolver.

**Current state upstream:** a resolver exists — `hermes_constants.py::project_venv_dir(project_root)` (added 2026-08-19, commit `7a94b1f`, verified in upstream history), resolving `venv` **before** `.venv`. Its docstring: *"``venv`` wins when both exist, matching what the installers write."* It checks `is_dir()` only (no `pyvenv.cfg` validation) and callers decide whether a missing venv is an error.

**The failure mode is call sites that bypass that resolver, not the absence of one.** Before `7a94b1f`, exactly **11** sites in `hermes_cli/` hardcoded `PROJECT_ROOT / "venv"` (`update_cmd.py` 7, `gateway.py` 2, `main.py` 2 — counted from the parent commit). Some bypasses persist today; e.g. `hermes_cli/gateway.py::_build_service_path_dirs` builds the service-unit PATH from `project_root / "venv" / "bin"` only — no `.venv` candidate — so on a `.venv`-only checkout the project venv is silently omitted from the generated PATH. The canonical open bug of this class is **#79542** (*"`_venv_scripts_dir()` only checks venv, not .venv, causing all Windows update protections to silently skip"*).

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

This is detection, not project resolution. Upstream's `project_venv_dir()` does **not** consult either of these.

### B. Which venv DIRECTORY does the project have? (upstream's resolver)

`project_venv_dir(project_root)` — import it; do not re-implement:

1. **`venv/`** — checked first.
2. **`.venv/`** — only when `venv/` is absent.
3. **`None`** — no venv directory. Callers decide if that is an error.

`is_dir()` only — no `pyvenv.cfg` validation, no environment-variable lookups.

### C. Script that needs the best available answer

Active venv first (A), then the project's candidate dirs (B). That is what the replica below does — and it is a **superset** of upstream, not a mirror: steps 1–2 are the replica's own additions for script use.

```python
import os
import sys
from pathlib import Path

def resolve_venv(project_root: Path | None = None) -> Path | None:
    """Resolve the active or canonical venv for a Hermes Agent checkout.

    Resolution order:
    1. VIRTUAL_ENV environment variable (if set and valid)
    2. sys.prefix (if running inside a venv inside the project)
    3. venv/ (installer default — project_venv_dir() resolves this first)
    4. .venv/ (uv default)
    5. None (system Python, no venv)

    NOT a mirror of upstream: steps 1-2 (active-env detection) are this
    replica's own additions for script use - project_venv_dir() consults
    neither VIRTUAL_ENV nor sys.prefix. Steps 3-4 mirror upstream exactly:
    is_dir() alone, so a stray empty directory wins the same way it does
    upstream. Prefer importing project_venv_dir() when Hermes core is
    importable; use this replica outside the checkout.
    """
    # 1. Explicit override
    env_venv = os.environ.get("VIRTUAL_ENV")
    if env_venv:
        p = Path(env_venv)
        if p.is_dir() and (p / "pyvenv.cfg").exists():
            return p

    # 2. Running inside a venv
    if hasattr(sys, "real_prefix") or (
        hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix
    ):
        prefix = Path(sys.prefix)
        if prefix.is_dir() and (prefix / "pyvenv.cfg").exists():
            return prefix

    # 3 & 4. Check project root candidates — venv first, matching upstream
    root = project_root or Path.cwd()
    for name in ("venv", ".venv"):
        candidate = root / name
        if candidate.is_dir():
            return candidate

    # 5. No venv found
    return None
```

## Cross-platform path construction

**Never hardcode `venv/bin/` or `venv/Scripts/`.** Use `venv_bin_dir()` from `hermes_constants.py`:

```python
from hermes_constants import venv_bin_dir, project_venv_dir

venv = project_venv_dir(Path("/path/to/hermes-agent"))
if venv:
    python_path = venv_bin_dir(venv) / "python"
    # POSIX: /path/to/hermes-agent/venv/bin/python    (installer layout)
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
- **Do:** Resolve via `project_venv_dir()` from `hermes_constants.py` (it picks `venv/` before `.venv/`).
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

The wrong venv is active. Check:

```bash
which python        # Should point inside .venv/ or venv/
python -c "import sys; print(sys.prefix)"  # Confirms active venv
```

### Both `.venv/` and `venv/` exist

Upstream's `project_venv_dir()` resolves `venv/` first, so scripts mirroring Hermes core pick `venv/` — which may be the stale one if this checkout is uv-managed. Don't guess: find the live one (e.g. `venv/bin/pip show hermes-agent` vs `.venv/bin/pip show hermes-agent`, or `hermes doctor`), then delete the stale directory to remove the ambiguity.

### A protection or PATH feature silently does nothing

Symptom: an update/protection/preflight step reports success but never ran, or a generated service unit's PATH lacks the venv. Cause: a **venv-only** check on a **`.venv`-only** checkout — the same class as open bug **#79542** (Windows update protections skip entirely) and the `_build_service_path_dirs` bypass above. Confirm the layout first (`ls -d venv .venv`), then treat any venv-name-specific check as suspect and resolve through `project_venv_dir()`.

### Windows: "python" not found

Windows venvs use `Scripts\python.exe`, not `bin/python`. Use `venv_bin_dir()` or `sys.executable`.

## See Also

- `references/venv_detection_patterns.py` — copy-paste-ready detection functions
- Hermes core `hermes_constants.py` — `project_venv_dir()` (the resolver), `venv_bin_dir()`, `venv_python_path()`
- Open bug **#79542** — `_venv_scripts_dir()` checks only `venv`, so Windows update protections silently skip on `.venv` installs (the canonical harm of this split)
- Related history: `venv_bin_dir()`'s docstring records the consolidation effort — the layout was open-coded in seven places using three different Windows predicates, and the fix for #76091 shipped an eighth copy before `hermes_constants.py` became the single source.

---

*Facts verified 2026-09-14 against upstream source at `8aa219ef` (`hermes_constants.py`, `hermes_cli/gateway.py`, `pyproject.toml`), upstream issue tracker (#79542 open, #76091 closed, #92376 unrelated to venv layout), and live layouts on two hosts: a Linux/WSL installer install (`venv/`, Python 3.11.15) and a Windows desktop-app install (`.venv/`, Python 3.13.14, uv 0.11.21). Re-verify before reuse.*
