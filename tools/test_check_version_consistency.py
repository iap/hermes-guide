#!/usr/bin/env python3
"""Behavioral coverage for check_version_consistency.py.

check_version_consistency.py verifies the plugin version agrees across
plugin.yaml, __init__.py, SECURITY.md, and pyproject.toml. A regression
would silently allow version drift. These tests exercise the shipped entry
point.

Stdlib only — no PyYAML, no Hermes, no network. Safe for the fast tier.

Usage:
    python tools/test_check_version_consistency.py

Exit codes: 0 clean, 1 a case failed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "check_version_consistency.py"


def run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True, text=True, cwd=REPO, timeout=300,
    )


def main() -> int:
    failures: list[str] = []

    # --selftest should exit 0
    r = run(["--selftest"])
    if r.returncode != 0:
        failures.append(f"--selftest exited {r.returncode}: {(r.stdout + r.stderr)[:300]}")

    # bare invocation should exit 0 (versions agree)
    r = run([])
    if r.returncode != 0:
        failures.append(f"bare exited {r.returncode}: {(r.stdout + r.stderr)[:300]}")
    if "agrees across" not in (r.stdout + r.stderr):
        failures.append("expected 'agrees across' in output")

    # exercise version drift detection through the CLI
    import shutil
    pyproject = REPO / "pyproject.toml"
    original = pyproject.read_text(encoding="utf-8")
    drifted = original.replace('version = "0.9.1"', 'version = "0.9.0"', 1)
    if drifted != original:
        pyproject.write_text(drifted, encoding="utf-8")
        r = run([])
        if r.returncode == 0:
            failures.append("checker did not detect version drift")
        pyproject.write_text(original, encoding="utf-8")
        # verify restored
        if pyproject.read_text(encoding="utf-8") != original:
            failures.append("failed to restore pyproject.toml")
            pyproject.write_text(original, encoding="utf-8")

    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1
    print("OK: check_version_consistency behavioral tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
