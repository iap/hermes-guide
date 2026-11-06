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

import datetime
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

    def ts_line(offset_seconds, suffix):
        dt = datetime.datetime.now() - datetime.timedelta(seconds=offset_seconds)
        return f"{dt.strftime('%Y-%m-%d %H:%M:%S')},000 {suffix}\n"

    # 1. Recent disconnect aligned with a >20s blocking call -> broken+aligned.
    # Fixture timestamps derive from the test clock so "recent" never ages out.
    aligned = run([
        ts_line(90, "INFO [s1] agent.tool_executor: tool terminal completed (204.11s, 243 chars)"),
        ts_line(4, "INFO [s1] agent.conversation_loop: API call #40: model=x in=62059 latency=46.7s id=a"),
        ts_line(2, "WARNING tui_gateway.ws: ws send failed peer=127.0.0.1:61582 error_type=WebSocketDisconnect error="),
        ts_line(2, "WARNING tui_gateway.ws: ws response send failed peer=127.0.0.1:61582 id=1056 method=subagent.list"),
        ts_line(2, "ERROR tui_gateway.ws: ws receive failed peer=127.0.0.1:61582"),
        ts_line(1, "INFO tui_gateway.ws: ws closed peer=127.0.0.1:61582 reason=receive_failed messages=1056 parse_errors=0"),
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
        ts_line(2, "WARNING tui_gateway.ws: ws response send failed peer=127.0.0.1:61582 id=7 method=subagent.list"),
        ts_line(1, "INFO tui_gateway.ws: ws closed peer=127.0.0.1:61582 reason=receive_failed messages=7"),
    ])
    if plain.get("status") != "broken":
        failures.append(f"plain disconnect expected broken, got {plain}")
    detail = plain.get("detail") or []
    if any("aligned" in str(d) for d in detail):
        failures.append(f"plain case must not claim alignment: {detail}")

    # 2b. Disconnect-only (no send failure) -> still broken.
    alone = run([
        ts_line(1, "INFO tui_gateway.ws: ws closed peer=127.0.0.1:61582 reason=receive_failed messages=42"),
    ])
    if alone.get("status") != "broken":
        failures.append(f"disconnect-only expected broken, got {alone}")

    # 2c. Non-1000 client_disconnect (code 1009) -> abnormal (broken).
    abnormal = run([
        ts_line(1, "INFO tui_gateway.ws: ws closed peer=127.0.0.1:61582 reason=client_disconnect(code=1009,reason=) messages=12"),
    ])
    if abnormal.get("status") != "broken":
        failures.append(f"code-1009 close expected broken, got {abnormal}")

    # 3. Quiet log -> healthy.
    quiet = run([ts_line(10, "INFO run_agent: OpenAI client closed ok")])
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

    # 6. Normal client close (code=1000) -> healthy, never broken.
    normal = run([
        ts_line(1, "INFO tui_gateway.ws: ws closed peer=127.0.0.1:61582 reason=client_disconnect(code=1000,reason=) messages=12"),
    ])
    if normal.get("status") != "healthy":
        failures.append(f"normal close expected healthy, got {normal}")

    # 6b. Unreadable log (POSIX chmod 000, non-root) -> unknown GATEWAY_LOG_UNREADABLE.
    # Windows ACLs ignore chmod 000, and root bypasses permissions; POSIX-only.
    if os.name != "nt" and getattr(os, "geteuid", None) is not None and os.geteuid() != 0:
        unreadable = _home_with_log([ts_line(1, "INFO tui_gateway.ws: ws closed peer=x reason=receive_failed messages=1")])
        try:
            os.chmod(os.path.join(unreadable, "logs", "agent.log"), 0o000)
            with patch.object(checks, "_hermes_home", return_value=unreadable):
                result = checks.check_gateway_health()
            if result.get("status") != "unknown" or result.get("id") != "GATEWAY_LOG_UNREADABLE":
                failures.append(f"unreadable case expected unknown GATEWAY_LOG_UNREADABLE, got {result}")
        finally:
            try:
                os.chmod(os.path.join(unreadable, "logs", "agent.log"), 0o644)
            except OSError:
                pass

    # 7. Keepalive-only failure -> broken.
    keepalive = run([
        ts_line(1, "ERROR tui_gateway.ws: keepalive ping timeout"),
    ])
    if keepalive.get("status") != "broken":
        failures.append(f"keepalive-only expected broken, got {keepalive}")

    # 7b. Bedrock ConnectionClosedError (no gateway signature) -> healthy.
    bedrock = run([
        ts_line(1, "ERROR bedrock.client: ConnectionClosedError: upstream closed"),
    ])
    if bedrock.get("status") != "healthy":
        failures.append(f"bedrock case expected healthy, got {bedrock}")

    # 7c. Standalone delegate timeout (no gateway failure) -> healthy/informational, never broken.
    standalone = run([
        ts_line(1, "WARNING tools.delegate_tool: Subagent 3 timed out after 990.0s"),
    ])
    if standalone.get("status") == "broken":
        failures.append(f"standalone timeout must not be broken, got {standalone}")

    # 7c2. Keepalive + delegate timeout together -> broken, delegate not labeled no-gateway.
    combined = run([
        ts_line(2, "ERROR tui_gateway.ws: keepalive ping timeout"),
        ts_line(1, "WARNING tools.delegate_tool: Subagent 3 timed out after 990.0s"),
    ])
    if combined.get("status") != "broken":
        failures.append(f"combined case expected broken, got {combined}")
    if not any("delegate timeout after 990.0s" in str(d) for d in (combined.get("detail") or [])):
        failures.append(f"combined case missing delegate timeout: {combined.get('detail')}")
    if any("no gateway failure" in str(d) for d in (combined.get("detail") or [])):
        failures.append(f"combined case must not claim no gateway failure: {combined.get('detail')}")

    # 7d. Malformed timeout seconds -> unknown, never healthy.
    malformed_timeout = run([
        ts_line(1, "WARNING tools.delegate_tool: Subagent 3 timed out after 1.2.3s"),
    ])
    if malformed_timeout.get("status") != "unknown":
        failures.append(f"malformed timeout expected unknown, got {malformed_timeout}")

    # 8. Old (>7d) disconnect -> informational, not broken.
    old = run([
        ts_line(8 * 86400, "INFO tui_gateway.ws: ws closed peer=127.0.0.1:61582 reason=receive_failed messages=7"),
    ])
    if old.get("status") != "informational":
        failures.append(f"old disconnect expected informational, got {old}")

    if failures:
        print("FAIL:")
        for failure in failures:
            print(f" - {failure}")
        return 1
    print("OK: gateway health behavioral tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
