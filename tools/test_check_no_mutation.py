#!/usr/bin/env python3
"""Behavioral coverage for check_no_mutation.py.

check_no_mutation.py scans plugin Python sources for filesystem writes, config
mutation, or mutating subprocesses. A regression would silently allow
mutation in a read-only plugin. These tests exercise the shipped entry point.

Stdlib only — no PyYAML, no Hermes, no network. Safe for the fast tier.

Usage:
    python tools/test_check_no_mutation.py

Exit codes: 0 clean, 1 a case failed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "check_no_mutation.py"


def run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True, text=True, cwd=REPO, timeout=300,
    )


def main() -> int:
    failures: list[str] = []

    # bare invocation should exit 0 (no mutation in current tree)
    r = run([])
    if r.returncode != 0:
        failures.append(f"bare exited {r.returncode}: {(r.stdout + r.stderr)[:300]}")
    if "no mutation detected" not in (r.stdout + r.stderr):
        failures.append("expected 'no mutation detected' in output")

    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("OK: check_no_mutation behavioral tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
