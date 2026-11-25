"""Shared pytest fixtures for hermes-guide's regression suite.

The repo's plugin modules live in a hyphenated directory, so they cannot be
imported as a package by name. The ``checks`` fixture loads them explicitly
into a synthetic ``hermes_guide`` package (the same effect as the standalone
scripts' temp-copy shim) and yields a fresh module per test so monkeypatched
globals never leak between cases.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_PLUGIN_FILES = ("__init__.py", "checks.py", "constants.py")


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def checks() -> Iterator[object]:
    """Yield a fresh ``checks`` module under a valid synthetic package."""
    pkg_name = "hermes_guide"
    package = types.ModuleType(pkg_name)
    package.__path__ = [str(REPO_ROOT)]
    sys.modules[pkg_name] = package
    try:
        spec = importlib.util.spec_from_file_location(
            f"{pkg_name}.checks", REPO_ROOT / "checks.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"{pkg_name}.checks"] = module
        spec.loader.exec_module(module)
        yield module
    finally:
        for name in [
            n for n in sys.modules if n == pkg_name or n.startswith(f"{pkg_name}.")
        ]:
            del sys.modules[name]
