"""Behavioral coverage for `hermes` executable resolution in checks.py.

The gates in `tools/` read text, so a resolution bug can ship with every gate
green. These tests build real stub executables and assert which one actually
answered — the failure mode where `PATH` names an install whose console script
cannot exec itself.

Run: python tools/test_checks_cli_resolution.py
"""

import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

failures = []


def _load_checks():
    """Import the plugin package under a shim (hyphenated dir can't import)."""
    td = Path(tempfile.mkdtemp())
    pkg = td / "hermes_guide"
    pkg.mkdir()
    for name in ("__init__.py", "checks.py", "constants.py"):
        shutil.copy(REPO / name, pkg / name)
    sys.path.insert(0, str(td))
    import hermes_guide.checks as checks_mod  # noqa: E402

    return checks_mod


checks = _load_checks()
HERMES_EXE = checks.HERMES_EXE  # noqa: F821 — resolved from the plugin under test


def check(name, condition, detail=""):
    if condition:
        print(f"PASS  {name}")
    else:
        print(f"FAIL  {name}{f'  [{detail}]' if detail else ''}")
        failures.append(name)


def _stub(directory, name, body):
    """Write an executable stub script and return its path."""
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _bad_shim(directory, name):
    """A console script whose interpreter line cannot resolve, like a GNU
    `realpath -- "$0"` shim on a host that has no GNU realpath."""
    return _stub(
        directory,
        name,
        "#!/bin/sh\n"
        "'''exec' \"$(dirname -- \"$(realpath -- \"$0\")\")\"/'python3' \"$0\" \"$@\"\n"
        "' '''\n",
    )


def _working(directory, name, marker):
    return _stub(directory, name, f"#!/bin/sh\necho {marker}\nexit 0\n")


def _fake_interpreter(directory):
    """A stand-in for sys.executable living in `directory`."""
    return _working(directory, "python3", "PY-OK")


def test_sibling_outranks_path():
    """The install running the check answers, not one earlier on PATH."""
    with tempfile.TemporaryDirectory() as tmp:
        sibling, other = os.path.join(tmp, "sibling"), os.path.join(tmp, "other")
        os.makedirs(sibling), os.makedirs(other)
        exe = _fake_interpreter(sibling)
        _working(sibling, HERMES_EXE, "SIBLING")
        _working(other, HERMES_EXE, "FROMPATH")

        original_exe, original_path = sys.executable, os.environ["PATH"]
        try:
            sys.executable = exe
            os.environ["PATH"] = other + os.pathsep + original_path
            rc, out, _ = checks._run_hermes(["config", "path"])
        finally:
            sys.executable, os.environ["PATH"] = original_exe, original_path

        check("sibling executable outranks PATH", rc == 0 and "SIBLING" in out,
              f"rc={rc} out={out.strip()!r}")


def test_falls_through_broken_shim():
    """An unusable entry point falls through to the next candidate."""
    with tempfile.TemporaryDirectory() as tmp:
        sibling, other = os.path.join(tmp, "sibling"), os.path.join(tmp, "other")
        os.makedirs(sibling), os.makedirs(other)
        exe = _fake_interpreter(sibling)
        _bad_shim(sibling, HERMES_EXE)
        _working(other, HERMES_EXE, "FALLBACK")

        original_exe, original_path = sys.executable, os.environ["PATH"]
        try:
            sys.executable = exe
            os.environ["PATH"] = other + os.pathsep + original_path
            rc, out, _ = checks._run_hermes(["config", "path"])
        finally:
            sys.executable, os.environ["PATH"] = original_exe, original_path

        check("broken shim falls through to next candidate",
              rc == 0 and "FALLBACK" in out, f"rc={rc} out={out.strip()!r}")


def test_broken_shim_reproduces_126():
    """The real failure mode is exit 126 — assert it, so the test above is honest."""
    with tempfile.TemporaryDirectory() as tmp:
        broken = _bad_shim(tmp, HERMES_EXE)
        proc = subprocess.run([broken], capture_output=True, text=True, timeout=30)
        if sys.platform == "darwin" and os.environ.get("PATH", "").find("realpath") < 0:
            check("broken shim exits 126", proc.returncode == 126, f"rc={proc.returncode}")
        else:
            print(f"SKIP  broken shim exits 126 (host provides realpath; rc={proc.returncode})")


def test_real_failure_is_not_retried():
    """A non-zero return from a working executable is Hermes' answer, not a
    reason to try the next install until something looks green."""
    with tempfile.TemporaryDirectory() as tmp:
        sibling, other = os.path.join(tmp, "sibling"), os.path.join(tmp, "other")
        os.makedirs(sibling), os.makedirs(other)
        exe = _fake_interpreter(sibling)
        _stub(sibling, HERMES_EXE, "#!/bin/sh\necho 'REAL-FAILURE'\nexit 3\n")
        _working(other, HERMES_EXE, "OTHER-INSTALL")

        original_exe, original_path = sys.executable, os.environ["PATH"]
        try:
            sys.executable = exe
            os.environ["PATH"] = other + os.pathsep + original_path
            rc, out, _ = checks._run_hermes(["config", "path"])
        finally:
            sys.executable, os.environ["PATH"] = original_exe, original_path

        check("real failure is reported, not retried",
              rc == 3 and "REAL-FAILURE" in out and "OTHER-INSTALL" not in out,
              f"rc={rc} out={out.strip()!r}")


def test_path_only_still_resolves():
    """A host with no sibling entry point still works via PATH."""
    with tempfile.TemporaryDirectory() as tmp:
        lonely = os.path.join(tmp, "lonely")
        elsewhere = os.path.join(tmp, "elsewhere")
        os.makedirs(lonely)
        os.makedirs(elsewhere)
        exe = _fake_interpreter(elsewhere)
        _working(lonely, HERMES_EXE, "PATHONLY")

        original_exe, original_path = sys.executable, os.environ["PATH"]
        try:
            sys.executable = exe
            os.environ["PATH"] = lonely + os.pathsep + original_path
            rc, out, _ = checks._run_hermes(["config", "path"])
        finally:
            sys.executable, os.environ["PATH"] = original_exe, original_path

        check("PATH-only resolution still works", rc == 0 and "PATHONLY" in out,
              f"rc={rc} out={out.strip()!r}")


def test_no_candidate_reports_clearly():
    """No executable anywhere is a stated error, not a silent empty answer."""
    with tempfile.TemporaryDirectory() as tmp:
        elsewhere = os.path.join(tmp, "elsewhere")
        os.makedirs(elsewhere)
        exe = _fake_interpreter(elsewhere)

        original_exe, original_path = sys.executable, os.environ["PATH"]
        try:
            sys.executable = exe
            os.environ["PATH"] = elsewhere
            checks.shutil.which = lambda *_a, **_k: None
            rc, out, err = checks._run_hermes(["config", "path"])
        finally:
            sys.executable, os.environ["PATH"] = original_exe, original_path

        check("no candidate is a clear error",
              rc == -127 and HERMES_EXE in err, f"rc={rc} err={err!r}")


def main():
    test_sibling_outranks_path()
    test_falls_through_broken_shim()
    test_broken_shim_reproduces_126()
    test_real_failure_is_not_retried()
    test_path_only_still_resolves()
    test_no_candidate_reports_clearly()

    print()
    if failures:
        print(f"FAILED {len(failures)}: {', '.join(failures)}")
        return 1
    print("OK: hermes executable resolution behaves as specified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
