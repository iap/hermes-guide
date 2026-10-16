#!/usr/bin/env python3
"""Regression coverage for checks.check_session_health.

Pins the runaway-session signature against the real incident shape
(2026-10-16: 47 turns, 20+ tool-turns/turn, 70K input tokens/call,
free-tier model, alternation repairs): a session matching all three
thresholds is broken with an actionable detail; elevated-but-below is
informational; quiet logs are healthy; a missing log is healthy (nothing
to audit); malformed lines never crash the parser.

No Hermes binary and no live $HERMES_HOME: checks.py is shim-loaded and
_hermes_home is pointed at a fixture dir.

Run: python3 tools/test_session_health.py
"""

from __future__ import annotations

import os
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


def _turn_lines(session: str, turns: int, tool_turns: int, in_tokens: int,
                model: str = "vendor/big-model", repairs: int = 0) -> list[str]:
    lines = []
    for i in range(turns):
        lines.append(
            f"2026-10-16 05:42:30,950 INFO [{session}] agent.conversation_loop: "
            f"API call #{i}: model={model} provider=x in={in_tokens} out=300 "
            f"total={in_tokens + 300} latency=9.6s id={i:040d}\n"
        )
        lines.append(
            f"2026-10-16 05:42:58,422 INFO [{session}] agent.conversation_loop: "
            f"Turn ended: reason=text_response(finish_reason=stop) model={model} "
            f"api_calls=2/90 budget=2/90 tool_turns={tool_turns} "
            f"last_msg_role=assistant response_len=764 session={session}\n"
        )
    for _ in range(repairs):
        lines.append(
            f"2026-10-16 05:42:30,950 INFO [{session}] agent.conversation_loop: "
            f"Repaired 2 message-alternation violations before request (session={session})\n"
        )
    return lines


def test_runaway_signature_is_broken():
    checks = _load_checks()
    lines = _turn_lines("20261016_021208_97c585", turns=16, tool_turns=20,
                        in_tokens=70205, model="meituan/longcat-2.5-preview:free",
                        repairs=2)
    checks._hermes_home = lambda: _home_with_log(lines)
    result = checks.check_session_health()
    assert result["status"] == "broken", result
    assert "runaway" in result["reason"], result
    detail = " ".join(result["detail"])
    assert "20261016_021208_97c585" in detail, result
    assert "fresh session" in detail, result
    assert "free-tier" in detail, result


def test_single_spike_is_not_runaway():
    # One heavy turn plus one big (unrelated) context call must not read as
    # a loop: the signature requires repetition.
    checks = _load_checks()
    lines = _turn_lines("steady", turns=16, tool_turns=1, in_tokens=3000)
    lines.append(
        "2026-10-16 05:42:30,950 INFO [steady] agent.conversation_loop: "
        "API call #99: model=vendor/big provider=x in=50000 out=300 "
        "total=50300 latency=9.6s id=0000000000000000000000000000000000000099\n"
    )
    lines.append(
        "2026-10-16 05:42:58,422 INFO [steady] agent.conversation_loop: "
        "Turn ended: reason=text_response(finish_reason=stop) model=vendor/big "
        "api_calls=2/90 budget=2/90 tool_turns=12 "
        "last_msg_role=assistant response_len=764 session=steady\n"
    )
    checks._hermes_home = lambda: _home_with_log(lines)
    result = checks.check_session_health()
    assert result["status"] != "broken", result


def test_stale_runaway_is_note_not_broken():
    checks = _load_checks()
    old = _turn_lines("oldsess", turns=16, tool_turns=20,
                      in_tokens=70000, model="vendor/small:free", repairs=2)
    filler = _turn_lines("newbie", turns=2, tool_turns=1, in_tokens=2000)
    filler = filler * 300  # push oldsess out of the recent window
    checks._hermes_home = lambda: _home_with_log(old + filler)
    result = checks.check_session_health()
    assert result["status"] != "broken", result
    assert "past runaway" in " ".join(result["detail"] or []), result


def test_unparseable_tail_is_unknown():
    checks = _load_checks()
    lines = ["2026-10-16 05:42:30,950 INFO [x] agent.conversation_loop: "
             "heartbeat ok\n"]
    checks._hermes_home = lambda: _home_with_log(lines)
    result = checks.check_session_health()
    assert result["status"] == "unknown", result


def test_interrupted_session_volume_via_api_calls():
    # Interrupted turns never emit "Turn ended": volume must also come from
    # api_calls, or exactly the looping shape goes undetected.
    checks = _load_checks()
    lines = _turn_lines("loop99", turns=22, tool_turns=20,
                        in_tokens=70000, model="vendor/small:free",
                        repairs=3)
    # Simulate interrupts: only 5 turns ever "end".
    kept, ends = [], 0
    for line in lines:
        if "Turn ended:" in line:
            ends += 1
            if ends > 5:
                continue
        kept.append(line)
    checks._hermes_home = lambda: _home_with_log(kept)
    result = checks.check_session_health()
    assert result["status"] == "broken", result
    assert "22 api calls" in " ".join(result["detail"]), result


def test_elevated_is_informational():
    checks = _load_checks()
    lines = _turn_lines("abc123", turns=9, tool_turns=3, in_tokens=5000)
    checks._hermes_home = lambda: _home_with_log(lines)
    result = checks.check_session_health()
    assert result["status"] == "informational", result


def test_quiet_is_healthy():
    checks = _load_checks()
    lines = _turn_lines("abc123", turns=2, tool_turns=1, in_tokens=3000)
    checks._hermes_home = lambda: _home_with_log(lines)
    result = checks.check_session_health()
    assert result["status"] == "healthy", result


def test_missing_log_is_healthy():
    checks = _load_checks()
    checks._hermes_home = lambda: _home_with_log(None)
    result = checks.check_session_health()
    assert result["status"] == "healthy", result
    assert "nothing to audit" in result["reason"], result


def test_malformed_lines_never_crash():
    checks = _load_checks()
    lines = ["not a log line\n", "Turn ended: tool_turns=abc session=\n",
             "\x00binary\xffjunk\n"]
    checks._hermes_home = lambda: _home_with_log(lines)
    result = checks.check_session_health()
    assert result["status"] in ("healthy", "informational"), result


def test_sessions_label_registered():
    checks = _load_checks()
    assert "sessions" in checks.labels()
    assert len(checks.labels()) == 9


def main() -> int:
    cases = [
        test_runaway_signature_is_broken,
        test_single_spike_is_not_runaway,
        test_stale_runaway_is_note_not_broken,
        test_unparseable_tail_is_unknown,
        test_interrupted_session_volume_via_api_calls,
        test_elevated_is_informational,
        test_quiet_is_healthy,
        test_missing_log_is_healthy,
        test_malformed_lines_never_crash,
        test_sessions_label_registered,
    ]
    failed = 0
    for case in cases:
        try:
            case()
            print(f"ok: {case.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL: {case.__name__}: {exc}")
    print(f"{'FAIL' if failed else 'OK'}: {len(cases) - failed}/{len(cases)} session-health cases")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
