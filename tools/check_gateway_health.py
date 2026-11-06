#!/usr/bin/env python3
"""Read-only CLI wrapper for checks.check_gateway_health.

Usage:
    python tools/check_gateway_health.py [--json]

Runs the gateway keepalive audit from the current $HERMES_HOME and prints
the envelope (text by default, one JSON document with --json). Exits 0 when
healthy/informational, 1 when broken/unknown — matching `hermes guide`.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load_checks():
    td = Path(tempfile.mkdtemp())
    pkg = td / "hermes_guide"
    pkg.mkdir()
    for name in ("__init__.py", "checks.py", "constants.py"):
        shutil.copy(REPO / name, pkg / name)
    sys.path.insert(0, str(td))
    from hermes_guide import checks

    return checks


def main(argv: list[str]) -> int:
    checks = _load_checks()

    result = checks.check_gateway_health()
    if "--json" in argv:
        print(json.dumps(result, indent=2, default=str))
    else:
        status = result.get("status", "unknown")
        mark = "+" if status == "healthy" else "~" if status == "informational" else "x" if status == "broken" else "?"
        print(f"{mark} {result.get('reason')}")
        detail = result.get("detail")
        if isinstance(detail, list):
            for line in detail:
                print(f"  {line}")
        elif detail:
            print(f"  {detail}")
    return 1 if result.get("status") in ("broken", "unknown") else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
