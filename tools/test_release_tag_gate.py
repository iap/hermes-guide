#!/usr/bin/env python3
"""Behavioral regression test for tools/check_release_tag_gate.py."""
from __future__ import annotations

import importlib.util
import sys
import unittest.mock as mock
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load_gate():
    path = REPO / "tools" / "check_release_tag_gate.py"
    spec = importlib.util.spec_from_file_location("check_release_tag_gate", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_gap_against_stable_not_rc():
    mod = _load_gate()
    rg = sys.modules['release_gate_shared']
    def fake_run(*args):
        s = ' '.join(str(a) for a in args)
        if 'rev-parse' in s and 'refs/tags/v0.9.3' in s:
            return (1, '')  # not tagged
        if 'tag' in s and '-l' in s:
            return (0, 'v0.9.3-rc.1\nv0.9.2')
        return (0, '')
    with mock.patch.object(rg, '_run', side_effect=fake_run):
        with mock.patch.object(rg, '_git_tag_date', return_value=1000000000):
            code, errs = mod.check_release_tag_gate('0.9.3', window_hours=0)
            assert code == 0, (code, errs)
    print('OK: rc->stable promotion')


def test_malformed_version():
    mod = _load_gate()
    code, errs = mod.check_release_tag_gate('abc', window_hours=0)
    assert code == 2, (code, errs)
    print('OK: malformed version')


def test_window_hours_passed():
    mod = _load_gate()
    rg = sys.modules['release_gate_shared']
    calls = []
    orig = rg.active_release
    def wrapped(*args, **kwargs):
        calls.append(args)
        return (False, '')
    def fake_run(*args):
        s = ' '.join(str(a) for a in args)
        if 'rev-parse' in s:
            return (1, '')
        if 'tag' in s and '-l' in s:
            return (0, 'v0.9.2')
        return (0, '')
    with mock.patch.object(rg, '_run', side_effect=fake_run):
        with mock.patch.object(rg, '_git_tag_date', return_value=1000000000):
            with mock.patch.object(mod, 'active_release', side_effect=wrapped):
                with mock.patch.object(rg, 'active_release', side_effect=wrapped):
                    mod.check_release_tag_gate('0.9.3', window_hours=7)
    assert calls and calls[0][1] == 7
    print('OK: window hours passed')


if __name__ == '__main__':
    test_gap_against_stable_not_rc()
    test_malformed_version()
    test_window_hours_passed()
    print('ALL OK')
