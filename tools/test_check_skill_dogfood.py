#!/usr/bin/env python3
"""Behavioral coverage for check_skill_dogfood.py's release harness.

The live release gate cannot run in CI without a candidate Hermes install, so
this test exercises the shipped selftest: version parsing, read-only command
safety, and the locked JSON document validator. The release path itself is run
manually before a tag with `--release --require-live`.

Usage:
    python tools/test_check_skill_dogfood.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "check_skill_dogfood.py"


def main() -> int:
    failures: list[str] = []
    result = subprocess.run(
        [sys.executable, str(TOOL), "--selftest"],
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=120,
    )
    if result.returncode != 0:
        failures.append(
            f"selftest exited {result.returncode}: {result.stderr[:300]}"
        )
    if "OK: dogfood selftest passed" not in result.stdout:
        failures.append(f"selftest success line missing: {result.stdout[:300]!r}")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print("OK: check_skill_dogfood selftest wiring passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
