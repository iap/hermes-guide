#!/usr/bin/env python3
"""Regression coverage for checks.check_update_lock.

Pins the stale-lock verdicts against the live incident shape (2026-10-16:
hermes-update.lock holding dead PID 96771 while every CLI invocation
wedged): dead owner + HELD checkout is broken (wait, never delete); dead
owner + FREE checkout is informational residue (safe to remove, CLI
unaffected — verified live: a dead-owner free lock coexists with a
working CLI); live owner (own PID) is informational; absent lock at a
recognized install is healthy; unrecognized layouts and unreadable locks
are unknown. The check never deletes anything — assert that too.

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
    else:
        # No lock, but a recognizable install: absence is measurable here.
        os.makedirs(os.path.join(td, "hermes-agent", ".git"))
    return td


def _home_without_install() -> str:
    return tempfile.mkdtemp()


def _hold_lock(path: str):
    """Hold path's kernel lock like a live updater child; return a releaser."""
    if os.name == "nt":
        import msvcrt
        _locking = getattr(msvcrt, "locking")
        _NBLCK = getattr(msvcrt, "LK_NBLCK")
        _UNLCK = getattr(msvcrt, "LK_UNLCK")
        fd = os.open(path, os.O_RDWR | getattr(os, "O_BINARY", 0))
        os.lseek(fd, 1 << 20, os.SEEK_SET)
        _locking(fd, _NBLCK, 1)
        def release():
            try:
                os.lseek(fd, 1 << 20, os.SEEK_SET)
                _locking(fd, _UNLCK, 1)
            finally:
                os.close(fd)
        return release
    import fcntl
    fd = os.open(path, os.O_RDONLY)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    def release():
        os.close(fd)
    return release


def _dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def test_stale_lock_is_broken():
    # Dead owner + HELD checkout: genuinely wedged — wait, never delete.
    checks = _load_checks()
    home = _home_with_lock(f"{_dead_pid()}\n1792133081\n")
    path = os.path.join(home, "hermes-agent", ".git", "hermes-update.lock")
    release = _hold_lock(path)
    try:
        checks._hermes_home = lambda: home
        before = os.listdir(os.path.join(home, "hermes-agent", ".git"))
        result = checks.check_update_lock()
        after = os.listdir(os.path.join(home, "hermes-agent", ".git"))
    finally:
        release()
    assert result["status"] == "broken", result
    assert "wedges" in result["reason"] and "do not remove" in result["reason"], result
    assert before == after, "check must never delete the lock"


def test_free_stale_record_is_informational():
    # Dead owner + FREE checkout: harmless residue — verified live (a
    # dead-owner free lock coexists with a working CLI), so informational
    # with removal wording, never broken.
    checks = _load_checks()
    home = _home_with_lock(f"{_dead_pid()}\n1792133081\n")
    checks._hermes_home = lambda: home
    result = checks.check_update_lock()
    assert result["status"] == "informational", result
    assert "safe to remove" in result["reason"], result


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


def test_unrecognized_layout_is_unknown_not_healthy():
    # No hermes-agent checkout beside home: absence of a lock file proves
    # nothing about the real install — unknown, never a clean bill.
    checks = _load_checks()
    checks._hermes_home = lambda: _home_without_install()
    result = checks.check_update_lock()
    assert result["status"] == "unknown", result
    assert "unrecognized" in result["reason"], result


def test_held_lock_waits_not_broken():
    # Held checkout never authorizes removal, even with a dead record.
    checks = _load_checks()
    home = _home_with_lock(f"{_dead_pid()}\n1792133081\n")
    path = os.path.join(home, "hermes-agent", ".git", "hermes-update.lock")
    release = _hold_lock(path)
    try:
        checks._hermes_home = lambda: home
        result = checks.check_update_lock()
    finally:
        release()
    assert result["status"] == "broken", result
    assert "do not remove" in result["reason"], result
    assert "safe to remove" not in result["reason"], result


def test_worktree_lock_resolves_through_commondir():
    # Linked-worktree layout: .git is a file naming the worktree dir whose
    # commondir names the shared dir holding the lock.
    checks = _load_checks()
    td = tempfile.mkdtemp()
    work, shared = os.path.join(td, "work"), os.path.join(td, "shared")
    os.makedirs(work)
    os.makedirs(shared)
    with open(os.path.join(work, ".git"), "w", encoding="utf-8") as fh:
        fh.write("gitdir: elsewhere\n")
    os.makedirs(os.path.join(work, "elsewhere"))
    with open(os.path.join(work, "elsewhere", "commondir"), "w", encoding="utf-8") as fh:
        fh.write("../../shared\n")
    with open(os.path.join(shared, "hermes-update.lock"), "w", encoding="utf-8") as fh:
        fh.write(f"{_dead_pid()}\n1792133081\n")
    install = os.path.join(td, "hermes-agent")
    os.rename(work, install)
    checks._hermes_home = lambda: td
    result = checks.check_update_lock()
    assert result["status"] == "informational", result
    assert result["detail"] == os.path.join(shared, "hermes-update.lock"), result


def test_zip_layout_lock_found_at_root():
    # No .git at all: ZIP-install layout, lock at the install root.
    checks = _load_checks()
    td = tempfile.mkdtemp()
    install = os.path.join(td, "hermes-agent")
    os.makedirs(install)
    with open(os.path.join(install, ".hermes-update.lock"), "w", encoding="utf-8") as fh:
        fh.write(f"{_dead_pid()}\n1792133081\n")
    checks._hermes_home = lambda: td
    result = checks.check_update_lock()
    assert result["status"] == "informational", result
    assert result["detail"].endswith(".hermes-update.lock"), result


def test_unreadable_lock_is_unknown():
    checks = _load_checks()
    home = _home_with_lock(f"{_dead_pid()}\n")
    path = os.path.join(home, "hermes-agent", ".git", "hermes-update.lock")
    os.chmod(path, 0)
    try:
        with open(path, encoding="utf-8"):
            readable = True
    except OSError:
        readable = False
    if readable:
        os.chmod(path, 0o644)
        print("SKIP [unreadable lock]: platform ignores mode bits for the owner")
        return
    try:
        checks._hermes_home = lambda: home
        result = checks.check_update_lock()
    finally:
        os.chmod(path, 0o644)
    assert result["status"] == "unknown", result


def test_unparseable_lock_is_unknown():
    checks = _load_checks()
    checks._hermes_home = lambda: _home_with_lock("not-a-pid\n")
    result = checks.check_update_lock()
    assert result["status"] == "unknown", result


def test_probe_failure_is_unknown_not_live():
    checks = _load_checks()
    checks._hermes_home = lambda: _home_with_lock("12345\n")
    if os.name == "nt":
        # Windows takes the ctypes branch: patch that seam instead.
        orig = checks._windows_pid_alive
        checks._windows_pid_alive = lambda pid: (_ for _ in ()).throw(OSError("probe exploded"))
        try:
            result = checks.check_update_lock()
        finally:
            checks._windows_pid_alive = orig
    else:
        orig_kill = os.kill
        checks.os.kill = lambda pid, sig: (_ for _ in ()).throw(OSError("probe exploded"))
        try:
            result = checks.check_update_lock()
        finally:
            checks.os.kill = orig_kill
    assert result["status"] == "unknown", result
    assert "indeterminate" in result["reason"], result


def test_nonpositive_pid_is_unknown():
    # pid 0/-1 are kill(2) process-group selectors, not processes: a corrupt
    # lock must never read as a live owner.
    checks = _load_checks()
    for bad in ("0\n", "-1\n"):
        checks._hermes_home = lambda: _home_with_lock(bad)
        result = checks.check_update_lock()
        assert result["status"] == "unknown", (bad, result)


def test_huge_pid_is_unknown_not_crash():
    # Python ints are unbounded; os.kill raises OverflowError past C long.
    # That must be indeterminate, never an escaped crash (which run_all
    # would report as broken).
    checks = _load_checks()
    checks._hermes_home = lambda: _home_with_lock(f"{2 ** 70}\n")
    result = checks.check_update_lock()
    assert result["status"] == "unknown", result


def test_windows_probe_never_raises():
    # POSIX hosts have no ctypes.windll: the branch must degrade without
    # raising. On real Windows, our own PID must read alive — that is the
    # probe actually working, not just not-crashing.
    checks = _load_checks()
    result = checks._windows_pid_alive(os.getpid())
    if os.name == "nt":
        assert result is True, result
    else:
        assert result in (False, None), result


def test_update_label_registered():
    checks = _load_checks()
    assert "update" in checks.labels()
    assert len(checks.labels()) == 9


def main() -> int:
    cases = [
        test_stale_lock_is_broken,
        test_free_stale_record_is_informational,
        test_live_owner_is_informational,
        test_absent_lock_is_healthy,
        test_unrecognized_layout_is_unknown_not_healthy,
        test_held_lock_waits_not_broken,
        test_worktree_lock_resolves_through_commondir,
        test_zip_layout_lock_found_at_root,
        test_unreadable_lock_is_unknown,
        test_unparseable_lock_is_unknown,
        test_probe_failure_is_unknown_not_live,
        test_nonpositive_pid_is_unknown,
        test_huge_pid_is_unknown_not_crash,
        test_windows_probe_never_raises,
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
