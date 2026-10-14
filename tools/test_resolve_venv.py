#!/usr/bin/env python3
"""Behavioral coverage for skills/diagnosing-path/references/resolve_venv.py.

The growth policy requires tools/test_*.py coverage for executable
references scripts: a green guard suite only scans the file, it never runs
it. Each case below executes resolve_venv() against fixture trees covering
the documented resolution order (VIRTUAL_ENV, sys.prefix, venv/, .venv/,
None) including the upstream-mirroring quirks (is_dir() alone wins, so a
stray empty directory counts; venv/ beats .venv/).

Hermetic: stdlib only, tempdir fixtures, ambient interpreter influence
neutralized via mock (VIRTUAL_ENV scrubbed, sys.prefix pinned to
base_prefix except in the dedicated sys.prefix case).

Run: python3 tools/test_resolve_venv.py
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "skills" / "diagnosing-path" / "references" / "resolve_venv.py"


def _load():
    spec = importlib.util.spec_from_file_location("resolve_venv_ref", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.resolve_venv


def _clean_env(extra=None):
    """Ambient env minus VIRTUAL_ENV (tempfile still needs TEMP), plus extras."""
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    if extra:
        env.update(extra)
    return env


def _pin_to_base():
    """Force the sys.prefix branch off regardless of the test runner."""
    return mock.patch.object(sys, "base_prefix", sys.prefix)


def _mkroot(*dirs, with_cfg=()):
    """Fixture project root; dirs created empty unless listed in with_cfg."""
    root = Path(tempfile.mkdtemp())
    for name in dirs:
        d = root / name
        d.mkdir()
        if name in with_cfg:
            (d / "pyvenv.cfg").write_text("home = x\n", encoding="utf-8")
    return root


def case_virtual_env_wins(mod):
    td = _mkroot("venv", ".venv")
    venv = _mkroot("real")
    (venv / "pyvenv.cfg").write_text("home = x\n", encoding="utf-8")
    try:
        with mock.patch.dict(os.environ, _clean_env({"VIRTUAL_ENV": str(venv)})):
            with _pin_to_base():
                assert mod(td) == venv, "explicit VIRTUAL_ENV must win"
    finally:
        shutil.rmtree(td, ignore_errors=True)
        shutil.rmtree(venv, ignore_errors=True)
    print("OK: VIRTUAL_ENV wins over project candidates")


def case_invalid_virtual_env_falls_through(mod):
    td = _mkroot("venv")
    try:
        with mock.patch.dict(
            os.environ, _clean_env({"VIRTUAL_ENV": str(td / "nope")})
        ):
            with _pin_to_base():
                assert mod(td) == td / "venv", "bogus VIRTUAL_ENV must fall through"
    finally:
        shutil.rmtree(td, ignore_errors=True)
    print("OK: invalid VIRTUAL_ENV falls through")


def case_venv_only_empty_dir_wins(mod):
    td = _mkroot("venv")
    try:
        with mock.patch.dict(os.environ, _clean_env()):
            with _pin_to_base():
                assert mod(td) == td / "venv", "empty venv/ wins by is_dir alone"
    finally:
        shutil.rmtree(td, ignore_errors=True)
    print("OK: lone empty venv/ wins")


def case_dotvenv_only(mod):
    td = _mkroot(".venv")
    try:
        with mock.patch.dict(os.environ, _clean_env()):
            with _pin_to_base():
                assert mod(td) == td / ".venv"
    finally:
        shutil.rmtree(td, ignore_errors=True)
    print("OK: lone .venv/ resolves")


def case_venv_beats_dotvenv(mod):
    td = _mkroot("venv", ".venv")
    try:
        with mock.patch.dict(os.environ, _clean_env()):
            with _pin_to_base():
                assert mod(td) == td / "venv", "venv/ must beat .venv/"
    finally:
        shutil.rmtree(td, ignore_errors=True)
    print("OK: venv/ beats .venv/")


def case_nothing_resolves_none(mod):
    td = _mkroot()
    try:
        with mock.patch.dict(os.environ, _clean_env()):
            with _pin_to_base():
                assert mod(td) is None, "bare dir must resolve None"
    finally:
        shutil.rmtree(td, ignore_errors=True)
    print("OK: no candidates resolves None")


def case_sys_prefix_venv(mod):
    td = _mkroot()
    fake = _mkroot("fake")
    (fake / "pyvenv.cfg").write_text("home = x\n", encoding="utf-8")
    try:
        with mock.patch.dict(os.environ, _clean_env()):
            with mock.patch.object(sys, "prefix", str(fake)):
                with mock.patch.object(sys, "base_prefix", "/nonexistent-base"):
                    assert mod(td) == Path(str(fake)), "in-venv prefix must win"
    finally:
        shutil.rmtree(td, ignore_errors=True)
        shutil.rmtree(fake, ignore_errors=True)
    print("OK: running inside a venv resolves sys.prefix")


def main() -> int:
    mod = _load()
    cases = (
        case_virtual_env_wins,
        case_invalid_virtual_env_falls_through,
        case_venv_only_empty_dir_wins,
        case_dotvenv_only,
        case_venv_beats_dotvenv,
        case_nothing_resolves_none,
        case_sys_prefix_venv,
    )
    failures: list[str] = []
    for case in cases:
        try:
            case(mod)
        except Exception as exc:
            failures.append(f"{case.__name__}: {exc}")
            print(f"FAIL: {case.__name__}: {exc}")
    if failures:
        print(f"\n{len(failures)} failure(s)")
        return 1
    print(f"\nOK: {len(cases)} resolve_venv case(s) passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
