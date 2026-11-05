#!/usr/bin/env python3
"""Behavioral regression test for tools/check_tag_version_gap.py."""
from __future__ import annotations

import importlib.util
import sys
import unittest.mock as mock
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load_mod():
    path = REPO / "tools" / "check_tag_version_gap.py"
    spec = importlib.util.spec_from_file_location("check_tag_version_gap", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_unrelated_tags_ignored():
    mod = _load_mod()
    rg = sys.modules['release_gate_shared']
    def fake_run(*args):
        s = ' '.join(str(a) for a in args)
        if 'rev-parse' in s:
            return (0, 'exists')
        return (0, '')
    with mock.patch.object(rg, '_run', side_effect=fake_run):
        with mock.patch.object(mod, '_git_tags', return_value=['v1.0.0', 'v0.9.2']):
            code = mod.check_tag_version_gap('v0.9.3')
            assert code == 0
    print('OK: unrelated tags ignored')


def test_gap_refused():
    mod = _load_mod()
    rg = sys.modules['release_gate_shared']
    def fake_run(*args):
        s = ' '.join(str(a) for a in args)
        if 'rev-parse' in s:
            return (0, 'exists')
        return (0, '')
    with mock.patch.object(rg, '_run', side_effect=fake_run):
        with mock.patch.object(mod, '_git_tags', return_value=['v0.9.2']):
            code = mod.check_tag_version_gap('v0.9.1')
            assert code == 1
    print('OK: gap refused')


if __name__ == '__main__':
    test_unrelated_tags_ignored()
    test_gap_refused()
    print('ALL OK')
