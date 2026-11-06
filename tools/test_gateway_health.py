#!/usr/bin/env python3
"""Behavioral coverage for checks.check_gateway_health.

Covers the keepalive-disconnect signature from the live incident
(2026-11-06: 46.7s API latency before a `ws closed reason=receive_failed`
with a `subagent.list` send failure): a recent disconnect aligned with a
>20s blocking call is broken with an aligned note; quiet logs are healthy;
a missing log is healthy; a past disconnect outside the recent window is
informational. Malformed lines never crash the parser.

No Hermes binary: checks.py is shim-loaded and _hermes_home is pointed at
a fixture directory.

Run: python3 tools/test_gateway_health.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent


def _load_checks():
    td = Path(tempfile.mkdtemp())
    pkg = td / "hermes_guide"
    pkg.mkdir()
    for name in ("__init__.py", "checks.py", "constants.py"):
        shutil.copy(REPO / name, pkg / name)
    sys.path.insert(0, str(td))
    import hermes_guide.checks as checks  # noqa: E402

    return checks


def _home_with_log(lines: list[str] | None) -> str:
    td = tempfile.mkdtemp()
    if lines is not None:
        logdir = os.path.join(td, "logs")
        os.makedirs(logdir)
        with open(os.path.join(logdir, "agent.log"), "w", encoding="utf-8") as fh:
            fh.writelines(lines)
    return td


def main() -> int:
    checks = _load_checks()
    failures: list[str] = []

    def run(lines):
        home = _home_with_log(lines)
        with patch.object(checks, "_hermes_home", return_value=home):
            return checks.check_gateway_health()

    # 1. Recent disconnect aligned with a >20s blocking call -> broken+aligned.
    aligned = run([
        "2026-11-06 22:17:31,403 INFO [s1] agent.tool_executor: tool terminal completed (204.11s, 243 chars)\n",
        "2026-11-06 22:18:57,888 INFO [s1] agent.conversation_loop: API call #40: model=x in=62059 latency=46.7s id=a\n",
        "2026-11-06 22:19:00,727 WARNING tui_gateway.ws: ws send failed peer=127.0.0.1:61582 error_type=WebSocketDisconnect error=\n",
        "2026-11-06 22:19:00,744 WARNING tui_gateway.ws: ws response send failed peer=127.0.0.1:61582 id=1056 method=subagent.list\n",
        "2026-11-06 22:19:00,776 ERROR tui_gateway.ws: ws receive failed peer=127.0.0.1:61582\n",
        "2026-11-06 22:19:01,494 INFO tui_gateway.ws: ws closed peer=127.0.0.1:61582 reason=receive_failed messages=1056 parse_errors=0\n",
    ])
    if aligned.get("status") != "broken":
        failures.append(f"aligned case expected broken, got {aligned}")
    detail = aligned.get("detail") or []
    if not any("aligned" in str(d) for d in detail):
        failures.append(f"aligned case missing aligned note: {detail}")
    if not any("receive_failed" in str(d) for d in detail):
        failures.append(f"aligned case missing reason: {detail}")
    if aligned.get("id") != "GATEWAY_HEALTH_ISSUES":
        failures.append(f"aligned case expected GATEWAY_HEALTH_ISSUES id")

    # 2. Disconnect without a preceding blocking call -> broken without aligned.
    plain = run([
        "2026-11-06 22:19:00,744 WARNING tui_gateway.ws: ws response send failed peer=127.0.0.1:61582 id=7 method=subagent.list\n",
        "2026-11-06 22:19:01,494 INFO tui_gateway.ws: ws closed peer=127.0.0.1:61582 reason=receive_failed messages=7\n",
    ])
    if plain.get("status") != "broken":
        failures.append(f"plain disconnect expected broken, got {plain}")
    detail = plain.get("detail") or []
    if any("aligned" in str(d) for d in detail):
        failures.append(f"plain case must not claim alignment: {detail}")

    # 3. Quiet log -> healthy.
    quiet = run(["2026-11-06 22:00:00,000 INFO run_agent: OpenAI client closed ok\n"])
    if quiet.get("status") != "healthy":
        failures.append(f"quiet case expected healthy, got {quiet}")

    # 4. Missing log -> healthy (nothing to audit).
    missing = run(None)
    if missing.get("status") != "healthy":
        failures.append(f"missing case expected healthy, got {missing}")

    # 5. Malformed lines never crash.
    crash = run(["not a log line\n", "\n", "2026-99-99 bad\n"])
    if crash.get("status") != "healthy":
        failures.append(f"malformed case expected healthy, got {crash}")

    if failures:
        print("FAIL:")
        for failure in failures:
            print(f" - {failure}")
        return 1
    print("OK: gateway health behavioral tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
