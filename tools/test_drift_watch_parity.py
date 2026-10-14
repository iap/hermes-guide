#!/usr/bin/env python3
"""Scheduled drift runs must watch at least the local default file list.

tools/check_upstream_drift.py falls back to its coded WATCH_FILES default,
but .github/workflows/upstream-drift.yml overrides it via env. If the env
list drops a file the default watches, scheduled runs silently stop
monitoring it (this bit agent/credential_pool.py and hermes_cli/auth.py:
Qodo review on PR #220 caught the dead coverage). Assert scheduled ⊇
default — the workflow may watch extra files, never fewer.

Hermetic: pure text parsing, no network, no imports.

Run: python3 tools/test_drift_watch_parity.py
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _code_default() -> list[str]:
    """File list from the coded WATCH_FILES fallback in check_upstream_drift.py.

    Parsed via AST (not regex): the region also contains the quoted env var
    name itself, which a naive quote scan mistakes for a watched file.
    """
    text = (REPO / "tools" / "check_upstream_drift.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and len(node.args) > 1
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "WATCH_FILES"
            and isinstance(node.args[1], ast.Constant)
        ):
            return str(node.args[1].value).split()
    raise AssertionError("coded WATCH_FILES default not found")


def _workflow_list() -> list[str]:
    """File list from the WATCH_FILES env in upstream-drift.yml."""
    text = (REPO / ".github" / "workflows" / "upstream-drift.yml").read_text(
        encoding="utf-8")
    m = re.search(r"(?m)^\s*WATCH_FILES:\s*(.+)$", text)
    assert m, "upstream-drift.yml sets no WATCH_FILES env"
    return m.group(1).split()


def main() -> int:
    missing = [f for f in _code_default() if f not in _workflow_list()]
    if missing:
        print(f"FAIL: scheduled watch list drops {len(missing)} default file(s): "
              f"{', '.join(missing)}")
        return 1
    print(f"OK: scheduled watch list covers all {len(_code_default())} default file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
