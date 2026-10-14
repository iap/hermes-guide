# `resolve_venv()` — best-available-answer replica for scripts

Active venv first (§A of the skill), then the project's candidate dirs (§B).
This is a **superset** of upstream, not a mirror: steps 1–2 are the replica's
own additions for script use — `project_venv_dir()` never reads `VIRTUAL_ENV`,
and it consults `sys.prefix` only for its out-of-tree fallback (gated by a
`direct_url.json` ownership check). Steps 3–4 mirror upstream's candidate scan
exactly: `is_dir()` alone, so a stray empty directory wins the same way it
does upstream. Prefer importing `project_venv_dir()` when Hermes core is
importable; use this replica outside the checkout.

```python
import os
import sys
from pathlib import Path

def resolve_venv(project_root: Path | None = None) -> Path | None:
    """Resolve the active or canonical venv for a Hermes Agent checkout.

    Resolution order:
    1. VIRTUAL_ENV environment variable (if set and valid)
    2. sys.prefix (if running inside a venv)
    3. venv/ (installer default — project_venv_dir() resolves this first)
    4. .venv/ (uv default)
    5. None (system Python, no venv)

    NOT a mirror of upstream: steps 1-2 (active-env detection) are this
    replica's own additions for script use - project_venv_dir() never
    reads VIRTUAL_ENV, and it consults sys.prefix only for its out-of-tree
    fallback (gated by a direct_url.json ownership check). Steps 3-4
    mirror upstream's candidate scan exactly: is_dir() alone, so a stray
    empty directory wins the same way it does upstream. Prefer importing
    project_venv_dir() when Hermes core is importable; use this replica
    outside the checkout.
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
