#!/usr/bin/env python3
"""Performance budget for the `--fast` degraded-host path.

`run_all(fast=True)` must stay fast on large skill trees: a parser or walker
regression that turns the C-loader win back into a multi-minute command would
silently break the degraded-host path users rely on. This test generates a
200-skill fixture in a temp HERMES_HOME (no real skills, no network) and
asserts the measured elapsed time stays inside the budget.

Budget: 60 s. Current measurement on the maintainer's macOS 12.7.6 box
(4 cores, heavily loaded) is ~21 s for run_all(fast=True) with 205 real
skills. The budget is generous to absorb runner variance while still catching
an order-of-magnitude regression (e.g. reverting to the pure-Python
SafeLoader, which took 36.7 s for 205 skills).

Run: python3 tools/test_fast_budget.py
Exit codes: 0 clean, 1 budget exceeded or fixture failure.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent


def _load_checks():
    td = Path(tempfile.mkdtemp())
    pkg = td / "hermes_guide"
    pkg.mkdir()
    for name in ("__init__.py", "checks.py", "constants.py"):
        shutil.copy(REPO / name, pkg / name)
    sys.path.insert(0, str(td))
    import hermes_guide.checks as checks  # noqa: E402

    return checks


def _make_skills(home: Path, count: int) -> None:
    skills_root = home / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        d = skills_root / f"bench-skill-{i:03d}"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\n"
            f"name: bench-skill-{i:03d}\n"
            f"description: Benchmark skill {i} for the fast-mode budget test.\n"
            "version: 1.0.0\n"
            "---\n\n"
            f"# Bench skill {i}\n",
            encoding="utf-8",
        )


def main() -> int:
    checks = _load_checks()
    td = tempfile.mkdtemp()
    home = Path(td) / "hermes"
    home.mkdir()
    _make_skills(home, 200)

    os.environ.pop("HERMES_DISABLE_LAZY_INSTALLS", None)
    with patch.object(checks, "_hermes_home", return_value=str(home)), \
         patch.object(checks, "_read_config", return_value=(None, {})):
        start = time.monotonic()
        results = checks.run_all(fast=True)
        elapsed = time.monotonic() - start

    budget = 60.0
    skills_result = results.get("skills", {})
    print(f"fast budget: {elapsed:.2f}s / {budget:.0f}s "
          f"(skills: {skills_result.get('status')})")
    if elapsed > budget:
        print(f"FAIL: run_all(fast=True) took {elapsed:.2f}s, budget {budget:.0f}s",
              file=sys.stderr)
        return 1
    if skills_result.get("status") not in ("healthy", "informational"):
        print(f"FAIL: unexpected skills status {skills_result.get('status')!r}",
              file=sys.stderr)
        return 1
    print("OK: fast-mode budget holds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
