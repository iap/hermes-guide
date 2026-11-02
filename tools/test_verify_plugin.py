"""Regression tests for _check_registration in verify_plugin.py.

Run: python3 tools/test_verify_plugin.py
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "tools" / "verify_plugin.py"

spec = importlib.util.spec_from_file_location("verify_plugin", SCRIPT)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

_check_registration = mod._check_registration


def _make_plugin(source):
    d = Path(tempfile.mkdtemp())
    plugin_dir = d / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "__init__.py").write_text(source)
    return plugin_dir


def case_register_with_ctx_passes():
    pd = _make_plugin("__version__ = \"1.0.0\"\ndef register(ctx):\n    pass\n")
    results = _check_registration(pd)
    checks = {r[0]: r[1] for r in results}
    assert checks.get("register(ctx) defined") is True
    assert checks.get("register accepts ctx param") is True


def case_register_no_params_fails():
    pd = _make_plugin("__version__ = \"1.0.0\"\ndef register():\n    pass\n")
    results = _check_registration(pd)
    checks = {r[0]: r[1] for r in results}
    assert checks.get("register(ctx) defined") is True
    assert checks.get("register accepts ctx param") is False


def case_nested_register_does_not_satisfy():
    src = "__version__ = \"1.0.0\"\n" + "def wrapper():\n" + "    def register(ctx):\n" + "        pass\n" + "def register():\n" + "    pass\n"
    pd = _make_plugin(src)
    results = _check_registration(pd)
    checks = {r[0]: r[1] for r in results}
    assert checks.get("register(ctx) defined") is True
    assert checks.get("register accepts ctx param") is False


def case_class_method_register_does_not_satisfy():
    src = "__version__ = \"1.0.0\"\n" + "class Foo:\n" + "    def register(self, ctx):\n" + "        pass\n" + "def register():\n" + "    pass\n"
    pd = _make_plugin(src)
    results = _check_registration(pd)
    checks = {r[0]: r[1] for r in results}
    assert checks.get("register(ctx) defined") is True
    assert checks.get("register accepts ctx param") is False


def case_posonly_param_accepted():
    pd = _make_plugin("__version__ = \"1.0.0\"\ndef register(ctx, /):\n    pass\n")
    results = _check_registration(pd)
    checks = {r[0]: r[1] for r in results}
    assert checks.get("register(ctx) defined") is True
    assert checks.get("register accepts ctx param") is True


def case_vararg_accepted():
    pd = _make_plugin("__version__ = \"1.0.0\"\ndef register(*args):\n    pass\n")
    results = _check_registration(pd)
    checks = {r[0]: r[1] for r in results}
    assert checks.get("register(ctx) defined") is True
    assert checks.get("register accepts ctx param") is True


def case_no_register_fails():
    pd = _make_plugin("__version__ = \"1.0.0\"\n")
    results = _check_registration(pd)
    checks = {r[0]: r[1] for r in results}
    assert checks.get("register(ctx) defined") is False


def case_missing_init_returns_error():
    d = Path(tempfile.mkdtemp())
    pd = d / "plugin"
    pd.mkdir()
    results = _check_registration(pd)
    assert any(r[0] == "__init__.py exists" and r[1] is False for r in results)


def case_conditional_register_in_if_block():
    src = "__version__ = \"1.0.0\"\n" + "if True:\n" + "    def register(ctx):\n" + "        pass\n"
    pd = _make_plugin(src)
    results = _check_registration(pd)
    checks = {r[0]: r[1] for r in results}
    assert checks.get("register(ctx) defined") is True, "conditional register should be found"
    assert checks.get("register accepts ctx param") is True, "conditional register should accept ctx"


def case_register_with_required_extra_pos_fails():
    pd = _make_plugin("__version__ = \"1.0.0\"\ndef register(ctx, required, /):\n    pass\n")
    results = _check_registration(pd)
    checks = {r[0]: r[1] for r in results}
    assert checks.get("register(ctx) defined") is True
    assert checks.get("register accepts ctx param") is False, "register with required extra pos should fail"


def case_register_with_required_kwonly_fails():
    pd = _make_plugin("__version__ = \"1.0.0\"\ndef register(ctx, *, required):\n    pass\n")
    results = _check_registration(pd)
    checks = {r[0]: r[1] for r in results}
    assert checks.get("register(ctx) defined") is True
    assert checks.get("register accepts ctx param") is False, "register with required kwonly should fail"


CASES = [
    case_register_with_ctx_passes,
    case_register_no_params_fails,
    case_nested_register_does_not_satisfy,
    case_class_method_register_does_not_satisfy,
    case_posonly_param_accepted,
    case_vararg_accepted,
    case_no_register_fails,
    case_missing_init_returns_error,
    case_conditional_register_in_if_block,
    case_register_with_required_extra_pos_fails,
    case_register_with_required_kwonly_fails,
]


def main():
    passed = 0
    for case in CASES:
        try:
            case()
            print("OK: %s" % case.__name__)
            passed += 1
        except AssertionError as e:
            print("FAIL: %s: %s" % (case.__name__, e))
    print()
    print("OK: %d/%d case(s) passed" % (passed, len(CASES)))
    if passed != len(CASES):
        sys.exit(1)


if __name__ == "__main__":
    main()
