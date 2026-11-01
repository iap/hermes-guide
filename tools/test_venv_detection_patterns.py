"""Behavioral tests for skills/diagnosing-path/references/venv_detection_patterns.py.

Run: python3 tools/test_venv_detection_patterns.py
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "skills" / "diagnosing-path" / "references" / "venv_detection_patterns.py"

spec = importlib.util.spec_from_file_location("venv_detection_patterns", SCRIPT)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

is_venv_active = mod.is_venv_active
active_venv_path = mod.active_venv_path
find_venv_dirs = mod.find_venv_dirs
resolve_venv = mod.resolve_venv
venv_bin_dir = mod.venv_bin_dir
venv_python_path = mod.venv_python_path
activate_venv_command = mod.activate_venv_command
probe_shell = mod.probe_shell


def case_is_venv_active_false():
    had_real = hasattr(sys, "real_prefix")
    saved = getattr(sys, "real_prefix", None)
    if had_real:
        delattr(sys, "real_prefix")
    try:
        with mock.patch.object(sys, "base_prefix", sys.prefix):
            assert is_venv_active() is False
    finally:
        if had_real:
            sys.real_prefix = saved


def case_find_venv_dirs_empty():
    import shutil
    import tempfile

    root = Path(tempfile.mkdtemp())
    try:
        assert find_venv_dirs(root) == []
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_find_venv_dirs_venv():
    import shutil
    import tempfile

    root = Path(tempfile.mkdtemp())
    (root / "venv").mkdir()
    (root / "venv" / "pyvenv.cfg").write_text("home = x\n")
    try:
        result = find_venv_dirs(root)
        assert len(result) == 1
        assert result[0] == root / "venv"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_find_venv_dirs_dotvenv():
    import shutil
    import tempfile

    root = Path(tempfile.mkdtemp())
    (root / ".venv").mkdir()
    (root / ".venv" / "pyvenv.cfg").write_text("home = x\n")
    try:
        result = find_venv_dirs(root)
        assert len(result) == 1
        assert result[0] == root / ".venv"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_find_venv_dirs_both():
    import shutil
    import tempfile

    root = Path(tempfile.mkdtemp())
    (root / "venv").mkdir()
    (root / "venv" / "pyvenv.cfg").write_text("home = x\n")
    (root / ".venv").mkdir()
    (root / ".venv" / "pyvenv.cfg").write_text("home = x\n")
    try:
        result = find_venv_dirs(root)
        assert len(result) == 2
        assert result[0] == root / "venv"
        assert result[1] == root / ".venv"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_find_venv_dirs_no_pyvenv_cfg():
    import shutil
    import tempfile

    root = Path(tempfile.mkdtemp())
    (root / "venv").mkdir()
    try:
        result = find_venv_dirs(root)
        assert result == []
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_resolve_venv_none():
    import shutil
    import tempfile

    root = Path(tempfile.mkdtemp())
    try:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VIRTUAL_ENV", None)
            with mock.patch.object(sys, "base_prefix", sys.prefix):
                if hasattr(sys, "real_prefix"):
                    delattr(sys, "real_prefix")
                result = resolve_venv(root)
                assert result is None
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_resolve_venv_dotvenv_only():
    import shutil
    import tempfile

    root = Path(tempfile.mkdtemp())
    (root / ".venv").mkdir()
    try:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VIRTUAL_ENV", None)
            with mock.patch.object(sys, "base_prefix", sys.prefix):
                if hasattr(sys, "real_prefix"):
                    delattr(sys, "real_prefix")
                result = resolve_venv(root)
                assert result == root / ".venv"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_resolve_venv_venv_dir():
    import shutil
    import tempfile

    root = Path(tempfile.mkdtemp())
    (root / "venv").mkdir()
    try:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VIRTUAL_ENV", None)
            with mock.patch.object(sys, "base_prefix", sys.prefix):
                if hasattr(sys, "real_prefix"):
                    delattr(sys, "real_prefix")
                result = resolve_venv(root)
                assert result == root / "venv"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_resolve_venv_active_prefix_wins():
    import shutil
    import tempfile

    root = Path(tempfile.mkdtemp())
    venv = Path(tempfile.mkdtemp())
    (venv / "pyvenv.cfg").write_text("home = x\n")
    try:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VIRTUAL_ENV", None)
            with mock.patch.object(sys, "base_prefix", "/nonexistent-base"):
                with mock.patch.object(sys, "prefix", str(venv)):
                    if hasattr(sys, "real_prefix"):
                        delattr(sys, "real_prefix")
                    result = resolve_venv(root)
                    assert result == venv
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(venv, ignore_errors=True)


def case_venv_bin_dir_posix():
    if sys.platform != "win32":
        venv = Path("/tmp/test_venv")
        assert venv_bin_dir(venv) == venv / "bin"


def case_venv_python_path_posix():
    if sys.platform != "win32":
        venv = Path("/tmp/test_venv")
        assert venv_python_path(venv) == venv / "bin" / "python"


def case_activate_venv_command_posix():
    if sys.platform != "win32":
        venv = Path("/tmp/test venv")
        cmd = activate_venv_command(venv)
        assert cmd == "source '/tmp/test venv/bin/activate'"


def case_venv_bin_dir_windows():
    if sys.platform == "win32":
        venv = Path("C:/test_venv")
        assert venv_bin_dir(venv) == venv / "Scripts"


def case_venv_python_path_windows():
    if sys.platform == "win32":
        venv = Path("C:/test_venv")
        assert venv_python_path(venv) == venv / "Scripts" / "python.exe"


def case_activate_venv_command_windows_cmd():
    if sys.platform == "win32":
        venv = Path("C:/test venv")
        cmd = activate_venv_command(venv, shell="cmd")
        assert "activate.bat" in cmd


def case_activate_venv_command_windows_powershell():
    if sys.platform == "win32":
        venv = Path("C:/test venv")
        cmd = activate_venv_command(venv, shell="powershell")
        assert "Activate.ps1" in cmd


def case_probe_shell_none():
    saved = os.environ.get("VIRTUAL_ENV")
    os.environ.pop("VIRTUAL_ENV", None)
    try:
        assert probe_shell() is None
    finally:
        if saved is not None:
            os.environ["VIRTUAL_ENV"] = saved


def case_probe_shell_valid():
    import shutil
    import tempfile

    venv = Path(tempfile.mkdtemp())
    (venv / "pyvenv.cfg").write_text("home = x\n")
    saved = os.environ.get("VIRTUAL_ENV")
    try:
        os.environ["VIRTUAL_ENV"] = str(venv)
        assert probe_shell() == venv
    finally:
        if saved is None:
            os.environ.pop("VIRTUAL_ENV", None)
        else:
            os.environ["VIRTUAL_ENV"] = saved
        shutil.rmtree(venv, ignore_errors=True)


def main() -> int:
    if not __debug__:
        print("error: assertions are disabled (python -O); re-run without -O", file=sys.stderr)
        return 2
    cases = [v for k, v in globals().items() if k.startswith("case_")]
    failures = []
    for case in cases:
        try:
            case()
            print(f"OK: {case.__name__}")
        except Exception as exc:
            failures.append(f"{case.__name__}: {exc}")
            print(f"FAIL: {case.__name__}: {exc}", file=sys.stderr)
    if failures:
        print(f"\n{len(failures)} failure(s)", file=sys.stderr)
        return 1
    print(f"\nOK: {len(cases)} case(s) passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
