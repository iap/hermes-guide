#!/usr/bin/env python3
"""Behavioral coverage for render_docs.py's --check and --write modes.

render_docs.py regenerates generated doc blocks in README.md, AGENTS.md, and
docs/findings.md. The --check mode verifies they're in sync without writing.
A regression in the renderer or its --check flag would silently ship stale
docs. These tests exercise the shipped entry point.

Stdlib only — no PyYAML, no Hermes, no network. Safe for the fast tier.

Usage:
    python tools/test_render_docs.py

Exit codes: 0 clean, 1 a case failed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "render_docs.py"


def run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True, text=True, cwd=REPO, timeout=300,
    )


def main() -> int:
    failures: list[str] = []

    # default (no args) is check mode — should exit 0 when docs are in sync
    r = run([])
    if r.returncode != 0:
        failures.append(f"default exited {r.returncode}: {(r.stdout + r.stderr)[:300]}")

    # --write should exit 0
    r = run(["--write"])
    if r.returncode != 0:
        failures.append(f"--write exited {r.returncode}: {(r.stdout + r.stderr)[:300]}")

    # verify --write actually fixes stale content
    target = REPO / "README.md"
    original = target.read_text(encoding="utf-8")
    drifted = original.replace("Thirty-one", "Thirty-two", 1)
    if drifted != original:
        target.write_text(drifted, encoding="utf-8")
        # default should now detect drift
        r = run([])
        if r.returncode == 0:
            failures.append("default did not detect introduced drift")
        # --write should fix it
        r = run(["--write"])
        if r.returncode != 0:
            failures.append(f"--write failed to fix drift: {(r.stdout + r.stderr)[:300]}")
        restored = target.read_text(encoding="utf-8")
        if restored != original:
            failures.append("--write did not restore original content")
            target.write_text(original, encoding="utf-8")

    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("OK: render_docs behavioral tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
