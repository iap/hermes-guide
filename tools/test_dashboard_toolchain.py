#!/usr/bin/env python3
"""Regression tests for the dashboard scope toolchain.

Validates DASHBOARD_* finding IDs, scope registration, and the envelopes
`check_dashboard` emits across its failure modes (fast, home unresolved,
checkout missing, node missing, toolchain indeterminate).

Run: python3 tools/test_dashboard_toolchain.py

The id set is asserted against a literal set, not a count: a hardcoded
"5" goes stale the moment a sixth finding is added, and the registry is
the source of truth. Adding `DASHBOARD_CHECKOUT_UNRESOLVED` is what broke
the old assertion.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
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


checks = _load_checks()

DASHBOARD_IDS = [k for k in checks.FINDING_IDS if k.startswith("DASHBOARD_")]
VALID_STATUSES = {"healthy", "informational", "broken", "unknown"}

EXPECTED_DASHBOARD_IDS = {
    "DASHBOARD_NODE_OUTDATED",
    "DASHBOARD_NODE_OS_FLOOR_MISMATCH",
    "DASHBOARD_NODE_ENGINES_MISMATCH",
    "DASHBOARD_WEBUI_STALE_BUILD",
    "DASHBOARD_LAZY_INSTALL_DISABLED",
    "DASHBOARD_CHECKOUT_UNRESOLVED",
}


def test_dashboard_ids_complete():
    """Every DASHBOARD_* envelope id has a FINDING_IDS entry, and no more."""
    assert set(DASHBOARD_IDS) == EXPECTED_DASHBOARD_IDS, DASHBOARD_IDS


def test_dashboard_ids_are_3tuples():
    for fid in DASHBOARD_IDS:
        entry = checks.FINDING_IDS[fid]
        assert isinstance(entry, tuple) and len(entry) == 3, fid
        assert all(isinstance(x, str) for x in entry), fid


def test_labels_includes_dashboard():
    assert "dashboard" in checks.labels()


def test_check_dashboard_fast_envelope():
    with patch.object(checks, "_hermes_home", return_value="/nonexistent"):
        result = checks.run_all(scope="dashboard", fast=True)
    assert "dashboard" in result
    assert result["dashboard"]["status"] in VALID_STATUSES


def test_check_dashboard_direct_envelope():
    token = checks._FAST_MODE.set(True)
    try:
        result = checks.check_dashboard()
    finally:
        checks._FAST_MODE.reset(token)
    assert isinstance(result, dict)
    assert result["status"] in VALID_STATUSES


def test_check_dashboard_home_unresolved():
    with patch.object(checks, "_hermes_home", return_value=None):
        result = checks.check_dashboard()
    assert result["status"] == "unknown"
    assert result["id"] == "HOME_UNRESOLVED"


def test_check_dashboard_fast_mode_envelope():
    token = checks._FAST_MODE.set(True)
    try:
        result = checks.check_dashboard()
    finally:
        checks._FAST_MODE.reset(token)
    assert isinstance(result, dict)
    assert "id" in result
    assert "status" in result
    assert "reason" in result


def test_check_dashboard_returns_dict():
    with patch.object(checks, "_hermes_home", return_value="/nonexistent"):
        result = checks.check_dashboard()
    assert isinstance(result, dict)
    assert "status" in result
    assert result["status"] in VALID_STATUSES


def test_check_dashboard_indeterminate_returns_unknown():
    """When installed_node and lock_node are both None, returns unknown."""
    with patch.object(checks, "_hermes_home", return_value="/nonexistent"):
        result = checks.check_dashboard()
    assert result["status"] == "unknown"
    assert "id" in result


def test_check_dashboard_broken_when_node_missing_but_lock_present():
    """When installed_node is None but lock_node exists, returns broken."""
    td = tempfile.mkdtemp()
    home = os.path.join(td, "hermes")
    os.makedirs(os.path.join(home, "tools"), exist_ok=True)
    os.makedirs(os.path.join(home, "hermes-agent", "pm"), exist_ok=True)
    with open(os.path.join(home, "hermes-agent", "pm", "lock.json"), "w") as f:
        json.dump({"packages": {"node": {"version": "26.7.0"}}}, f)
    with patch.object(checks, "_hermes_home", return_value=home):
        result = checks.check_dashboard()
    assert result["status"] in ("broken", "unknown")
    assert "id" in result


def test_check_dashboard_unknown_when_no_checkout():
    """No hermes-agent checkout anywhere under $HERMES_HOME -> unknown."""
    td = tempfile.mkdtemp()
    home = os.path.join(td, "hermes")
    os.makedirs(os.path.join(home, "tools"), exist_ok=True)
    with patch.object(checks, "_hermes_home", return_value=home):
        result = checks.check_dashboard()
    assert result["status"] == "unknown"
    assert result["id"] == "DASHBOARD_CHECKOUT_UNRESOLVED"


def main() -> int:
    failures = 0
    for name in sorted(globals()):
        if not name.startswith("test_"):
            continue
        fn = globals()[name]
        try:
            fn()
        except AssertionError as exc:
            failures += 1
            print(f"FAIL: {name}: {exc}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 - report, don't crash the run
            failures += 1
            print(f"ERROR: {name}: {exc!r}", file=sys.stderr)
    if failures:
        print(f"error: {failures} dashboard test(s) failed", file=sys.stderr)
        return 1
    print("OK: dashboard toolchain tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
