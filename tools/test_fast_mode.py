#!/usr/bin/env python3
"""Regression: fast/degraded-host mode never starts a subprocess.

On a degraded host every `hermes` launch takes minutes (update-completion
retry with failing toolchain verification). `run_all(fast=True)` must bound
that: no subprocess starts and hooks use the in-process variant. Home/config
resolve from the library only; when they do not (no live Hermes process),
each requested check reports `unknown` as skipped in fast mode instead of
paying the 60 s + 90 s subprocess budgets.

Guards:

1. With `_run` rigged to raise, `run_all(fast=True)` completes without
   touching it (no `hermes` launch, no `config path`, no `hooks doctor`).
2. With the library home stubbed out, every envelope is `unknown` and says
   fast mode skipped it — honest, never healthy.
3. `scope=` still filters to exactly one check in fast mode.
4. The unknown-scope error names the valid scopes and hints at an outdated
   installed plugin.
5. `_FAST_MODE` is restored after the run (no leakage into later calls).

Run: python3 tools/test_fast_mode.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

failures: list[str] = []


def _load_checks():
    """Import checks.py under a valid package name (the repo dir has hyphens)."""
    td = Path(tempfile.mkdtemp())
    pkg = td / "hermes_guide"
    pkg.mkdir()
    for name in ("__init__.py", "checks.py", "constants.py"):
        shutil.copy(REPO / name, pkg / name)
    sys.path.insert(0, str(td))
    import hermes_guide.checks as checks  # noqa: E402
    return checks


def main() -> int:
    checks = _load_checks()

    def _boom(*args, **kwargs):
        raise AssertionError(f"subprocess started in fast mode: {args!r}")

    checks._run = _boom

    labels = checks.labels()
    if len(labels) != 9:
        failures.append(f"expected 9 check labels, got {labels}")

    # (1) full fast run: no subprocess; envelopes well-formed either way
    try:
        results = checks.run_all(fast=True)
    except AssertionError as exc:
        failures.append(f"run_all(fast=True) started a subprocess: {exc}")
        results = {}
    if sorted(results.keys()) != sorted(labels):
        failures.append(f"fast run keys {sorted(results.keys())} != labels")
    for label, env in results.items():
        if env.get("status") not in ("healthy", "informational", "broken", "unknown"):
            failures.append(f"fast {label}: bad status {env.get('status')!r}")
        if "reason" not in env:
            failures.append(f"fast {label}: envelope lacks a reason")

    # (2) no library home: every envelope is unknown-skipped, never healthy
    real_home = checks._hermes_home_from_library
    checks._hermes_home_from_library = lambda: None
    try:
        skipped = checks.run_all(fast=True)
    except AssertionError as exc:
        failures.append(f"no-home fast run started a subprocess: {exc}")
        skipped = {}
    finally:
        checks._hermes_home_from_library = real_home
    if sorted(skipped.keys()) != sorted(labels):
        failures.append("no-home fast run keys != labels")
    for label, env in skipped.items():
        if env.get("status") != "unknown":
            failures.append(f"no-home fast {label}: status {env.get('status')!r}, expected 'unknown'")
        if "fast mode" not in str(env.get("reason", "")):
            failures.append(f"no-home fast {label}: reason hides fast mode: {env.get('reason')!r}")

    # (3) scope still filters in fast mode
    try:
        scoped = checks.run_all(scope="mcp", fast=True)
    except AssertionError as exc:
        failures.append(f"scoped fast run started a subprocess: {exc}")
        scoped = {}
    if sorted(scoped.keys()) != ["mcp"]:
        failures.append(f"scoped fast run keys {sorted(scoped.keys())} != ['mcp']")

    # (4) unknown scope names scopes and hints at an outdated install
    try:
        checks.run_all(scope="bogus", fast=True)
        failures.append("unknown scope 'bogus' did not raise ValueError")
    except ValueError as exc:
        text = str(exc)
        if "bogus" not in text or "mcp" not in text:
            failures.append(f"ValueError omits scope/scopes: {exc}")
        if "hermes plugins update" not in text:
            failures.append(f"ValueError lacks the outdated-plugin hint: {exc}")

    # (5) flag restored
    if checks._FAST_MODE:
        failures.append("_FAST_MODE leaked True after run_all(fast=True)")

    # fast + readonly_hooks compose (proactive boundary shape)
    try:
        both = checks.run_all(readonly_hooks=True, fast=True)
    except AssertionError as exc:
        failures.append(f"fast+readonly run started a subprocess: {exc}")
        both = {}
    if sorted(both.keys()) != sorted(labels):
        failures.append("fast+readonly run keys != labels")

    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("OK: fast mode starts no subprocess and reports skipped-unknown")
    return 0


if __name__ == "__main__":
    sys.exit(main())
