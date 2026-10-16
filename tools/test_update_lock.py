#!/usr/bin/env python3
"""Regression coverage for checks.check_update_lock.

Pins the stale-lock verdicts against the live incident shape (2026-10-16:
hermes-update.lock holding dead PID 96771 while every CLI invocation
wedged): dead owner is broken with removal wording; live owner (own PID)
is informational; absent lock is healthy; unparseable content is unknown.
The check never deletes anything — assert that too.

No Hermes binary and no live $HERMES_HOME: checks.py is shim-loaded,
_hermes_home points at a fixture dir, and dead PIDs come from reaped
subprocesses (never magic constants).

Run: python3 tools/test_update_lock.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOCK_REL = os.path.join("hermes-agent", ".git", "hermes-update.lock")


def _load_checks():
    td = Path(tempfile.mkdtemp())
    pkg = td / "hermes_guide"
    pkg.mkdir()
    for name in ("__init__.py", "checks.py", "constants.py"):
        shutil.copy(REPO / name, pkg / name)
    sys.path.insert(0, str(td))
    import hermes_guide.checks as checks  # noqa: E402

    return checks


def _home_with_lock(content: str | None) -> str:
    td = tempfile.mkdtemp()
    if content is not None:
        lockdir = os.path.join(td, "hermes-agent", ".git")
        os.makedirs(lockdir)
        with open(os.path.join(lockdir, "hermes-update.lock"), "w",
                   encoding="utf-8") as fh:
            fh.write(content)
    return td


def _dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def test_stale_lock_is_broken():
    checks = _load_checks()
    home = _home_with_lock(f"{_dead_pid()}\n1792133081\n")
    checks._hermes_home = lambda: home
    before = os.listdir(os.path.join(home, "hermes-agent", ".git"))
    result = checks.check_update_lock()
    after = os.listdir(os.path.join(home, "hermes-agent", ".git"))
    assert result["status"] == "broken", result
    assert "stale" in result["reason"] and "dead" in result["reason"], result
    assert before == after, "check must never delete the lock"


def test_live_owner_is_informational():
    checks = _load_checks()
    checks._hermes_home = lambda: _home_with_lock(f"{os.getpid()}\n")
    result = checks.check_update_lock()
    assert result["status"] == "informational", result
    assert "do not remove" in result["reason"], result


def test_absent_lock_is_healthy():
    checks = _load_checks()
    checks._hermes_home = lambda: _home_with_lock(None)
    result = checks.check_update_lock()
    assert result["status"] == "healthy", result
    assert "nothing to audit" in result["reason"], result


def test_unparseable_lock_is_unknown():
    checks = _load_checks()
    checks._hermes_home = lambda: _home_with_lock("not-a-pid\n")
    result = checks.check_update_lock()
    assert result["status"] == "unknown", result


def test_update_label_registered():
    checks = _load_checks()
    assert "update" in checks.labels()
    assert len(checks.labels()) == 9


def main() -> int:
    cases = [
        test_stale_lock_is_broken,
        test_live_owner_is_informational,
        test_absent_lock_is_healthy,
        test_unparseable_lock_is_unknown,
        test_update_label_registered,
    ]
    failed = 0
    for case in cases:
        try:
            case()
            print(f"ok: {case.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL: {case.__name__}: {exc}")
    print(f"{'FAIL' if failed else 'OK'}: {len(cases) - failed}/{len(cases)} update-lock cases")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
