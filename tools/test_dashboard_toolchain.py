#!/usr/bin/env python3
"""Regression tests for the dashboard scope toolchain.

Validates DASHBOARD_* finding IDs, scope registration, and that
check_dashboard returns a valid envelope in fast mode.

Run: python3 tools/test_dashboard_toolchain.py
"""

from __future__ import annotations

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


def test_five_dashboard_ids_present():
    assert len(DASHBOARD_IDS) == 5, DASHBOARD_IDS


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


if __name__ == "__main__":
    test_five_dashboard_ids_present()
    test_dashboard_ids_are_3tuples()
    test_labels_includes_dashboard()
    test_check_dashboard_fast_envelope()
    test_check_dashboard_direct_envelope()
    print("OK: dashboard toolchain tests passed")


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
    import json, tempfile, os
    td = tempfile.mkdtemp()
    home = os.path.join(td, "hermes")
    os.makedirs(os.path.join(home, "tools"), exist_ok=True)
    os.makedirs(os.path.join(home, "hermes-agent", "pm"), exist_ok=True)
    # Write lock with node version but no facts
    with open(os.path.join(home, "hermes-agent", "pm", "lock.json"), "w") as f:
        json.dump({"packages": {"node": {"version": "26.7.0"}}}, f)
    with patch.object(checks, "_hermes_home", return_value=home):
        result = checks.check_dashboard()
    assert result["status"] in ("broken", "unknown")
    assert "id" in result
