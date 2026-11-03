#!/usr/bin/env python3
"""Behavioral coverage for check_gates.py's --list and --quick modes.

check_gates.py is the orchestrator for the hermetic gate tier. A regression
in its argument parsing or gate enumeration would silently drop gates from
the local fast path. These tests exercise the shipped entry point.

Stdlib only — no PyYAML, no Hermes, no network. Safe for the fast tier.

Usage:
    python tools/test_check_gates.py

Exit codes: 0 clean, 1 a case failed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "check_gates.py"


def run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True, text=True, cwd=REPO, timeout=300,
    )


def main() -> int:
    failures: list[str] = []

    # --list should exit 0 and list all 13 gates
    r = run(["--list"])
    if r.returncode != 0:
        failures.append(f"--list exited {r.returncode}: {r.stderr[:200]}")
    if "Hermetic tier" not in r.stdout:
        failures.append("--list missing 'Hermetic tier' header")
    gate_lines = [l for l in r.stdout.splitlines() if l.strip().startswith("tools/")]
    if len(gate_lines) < 13:
        failures.append(f"--list shows only {len(gate_lines)} gates, expected 13")
    # verify all 13 expected gates are present
    expected_gates = [
        "test_skill_counts.py", "render_docs.py", "check_skill_provenance.py",
        "check_self_claim.py", "check_doc_style.py", "check_version_consistency.py",
        "gen_changelog.py", "check_issue_templates.py", "check_scope_enumeration.py",
        "check_no_mutation.py", "check_scanner_hygiene.py", "check_eol_contract.py",
        "verify_plugin.py",
    ]
    for g in expected_gates:
        if g not in r.stdout:
            failures.append(f"--list missing expected gate: {g}")

    # --quick should exit 0 (counts + provenance only)
    r = run(["--quick"])
    if r.returncode != 0:
        failures.append(f"--quick exited {r.returncode}: {(r.stdout + r.stderr)[:300]}")

    # bare invocation should run all gates (exit 0 or 1; 1 is acceptable if a
    # content gate like gen_changelog fails for an uncommitted PR range)
    r = run([])
    if r.returncode not in (0, 1):
        failures.append(f"bare exited {r.returncode}: {(r.stdout + r.stderr)[:300]}")
    if "gate(s) failed" in r.stderr and "gen_changelog" not in r.stderr:
        failures.append(f"unexpected gate failure: {combined[:300]}")

    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("OK: check_gates behavioral tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
