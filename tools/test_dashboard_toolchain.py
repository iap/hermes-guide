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
