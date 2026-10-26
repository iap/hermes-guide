#!/usr/bin/env python3
"""Regression: continued shell credentials stay out of deep-hook reports.

Synthetic credential fixtures live under tests/ for install-scanner hygiene.
Doctor execution is stubbed; no hook, network request, or real Hermes runs.
"""

from __future__ import annotations

import importlib.util
import shlex
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MARK_BAD = "\u2717"
MARK_WARN = "\u26a0"


def _load_checks():
    package = types.ModuleType("redaction_fixture")
    package.__path__ = [str(REPO)]
    sys.modules[package.__name__] = package
    spec = importlib.util.spec_from_file_location("redaction_fixture.checks", REPO / "checks.py")
    assert spec is not None and spec.loader is not None
    checks = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = checks
    spec.loader.exec_module(checks)
    return checks


def selftest() -> int:
    checks = _load_checks()
    checks._hermes_candidates = lambda: ["/fake/hermes"]
    checks._check_allowlist_json = lambda home=None: None
    marker = "SYNTHETIC_REVIEW_VALUE"
    head, tail = marker.split("_REVIEW", 1)
    tail = "_REVIEW" + tail
    continuation = chr(92) + "\n"
    double_quote = chr(34)
    single_quote = chr(39)
    commands = [
        "curl --password " + continuation + "  " + marker,
        "curl --password=" + continuation + marker,
        "PASSWORD=" + continuation + marker,
        "curl --password " + head + continuation + tail,
        "PASSWORD=" + head + continuation + tail,
        "curl --password " + double_quote + head + continuation + tail + double_quote,
        "curl --password " + single_quote + head + continuation + tail + single_quote,
        "curl --pass" + continuation + "word " + marker,
        "PASS" + continuation + "WORD=" + marker,
        "Authorization: " + continuation + "Bearer " + marker,
        "Authorization: Bea" + continuation + "rer " + marker,
        "Authorization: Bearer " + continuation + marker,
        "tool Bearer " + continuation + marker,
        "curl --oauth2-bearer " + continuation + marker,
        "curl -u " + continuation + "alice:" + marker,
        "curl -ualice:" + head + continuation + tail,
        # Three slashes escape one literal slash and continue the shell word.
        "curl --password " + head + chr(92) * 2 + continuation + tail,
        "curl --password " + continuation + "  " + continuation + marker,
        # CRLF doctor output is handled conservatively, without a Bash claim.
        "curl --password " + chr(92) + "\r\n  " + marker,
    ]
    # Brackets and status-symbol prefixes can be ordinary credential text.
    for prefix in ("[", MARK_BAD, MARK_WARN, "\u2713", "\u2139"):
        commands.append("curl --password " + continuation + "  " + prefix + marker)
    count = 0
    for command in commands:
        wrapped = "bash -c " + shlex.quote(command + " ./run.sh")
        assert shlex.split(wrapped) == ["bash", "-c", command + " ./run.sh"]
        doctor = "Checking hooks...\n  [pre_tool] " + wrapped + "\n"
        doctor += "      " + MARK_BAD + " not allowlisted\n"
        neighbor = "  " + MARK_WARN + " normal-hook   node /tmp/hook.js\n"
        doctor += neighbor
        # Exercise both stdout report detail and stderr on command failure.
        for rc, stdout, stderr in ((0, doctor, ""), (1, "", doctor)):
            checks._run = lambda cmd, timeout=20: (rc, stdout, stderr)
            result = checks.check_hooks()
            text = result["detail"]
            assert result["status"] == ("broken" if rc == 0 else "unknown"), result
            for fragment in (marker, head, tail):
                assert fragment not in text, (command, result)
            assert "***" in text and "./run.sh" in text, (command, result)
            assert neighbor.strip() in text, (command, result)
            assert MARK_BAD in text and MARK_WARN in text, result
            count += 1

    # A doctor marker at the start of a continuation line is NOT a record
    # boundary when it sits inside a quoted credential. The old regex-only
    # folding leaked the quoted tail; quote-aware folding must mask it whole.
    for prefix in (MARK_BAD, MARK_WARN, "\u2713", "\u2139"):
        command = (
            "PASSWORD=" + double_quote + "correct" + continuation
            + prefix + " horse" + double_quote
        )
        doctor = "Checking hooks...\n  [pre_tool] bash -c " + shlex.quote(command) + "\n"
        checks._run = lambda cmd, timeout=20: (0, doctor, "")
        result = checks.check_hooks()
        text = result["detail"]
        assert "correct" not in text and "horse" not in text, (prefix, result)
        assert "***" in text, result
        count += 1

    # Outside a quote the same shape is a genuine record boundary and must
    # survive as evidence rather than being folded into the credential value.
    command = "hook run " + continuation + MARK_BAD + " failed"
    doctor = "Checking hooks...\n  " + command + "\n"
    checks._run = lambda cmd, timeout=20: (0, doctor, "")
    result = checks.check_hooks()
    assert MARK_BAD + " failed" in result["detail"], result
    count += 1

    # A malformed record with an unclosed quote must not carry quote state into
    # the next record and swallow its status marker (Qodo finding 2).
    command = (
        "hook echo " + double_quote + "unterminated\n"
        "  [pre_tool] --password secret"
        + continuation + MARK_BAD + " failed"
    )
    doctor = "Checking hooks...\n" + command + "\n"
    checks._run = lambda cmd, timeout=20: (0, doctor, "")
    result = checks.check_hooks()
    assert "secret" not in result["detail"], result
    assert MARK_BAD + " failed" in result["detail"], result
    count += 1

    # An escaped literal quote outside quotes must not open quote state
    # (Qodo finding 3).
    command = (
        "hook echo " + chr(92) + double_quote + " literal and --password secret"
        + continuation + MARK_BAD + " failed"
    )
    doctor = "Checking hooks...\n  " + command + "\n"
    checks._run = lambda cmd, timeout=20: (0, doctor, "")
    result = checks.check_hooks()
    assert "secret" not in result["detail"], result
    assert MARK_BAD + " failed" in result["detail"], result
    count += 1

    # Matching sees logical shell words; unrelated evidence keeps its spelling.
    unchanged = [
        "node " + continuation + "  ./run.sh",
        "python -u " + continuation + "  ./run.sh",
        "sort -u " + continuation + "  ./input.txt",
        "git commit --author " + continuation + "  'Jane Doe' -m x",
        "echo first\nsecond",
        "echo " + chr(92) * 2 + "\nnext",
    ]
    for text in unchanged:
        assert checks._redact_hook_output(text) == text, repr(text)
        count += 1

    # An incomplete credential must not consume a neighboring doctor record.
    for symbol in (MARK_BAD, MARK_WARN, "\u2713", "\u2139"):
        next_record = symbol + " next-hook"
        text = "tool --password " + continuation + "  " + next_record + "\n"
        assert checks._redact_hook_output(text) == text, repr(text)
        count += 1

    # Projection ends at the matched value, leaving its following continuation.
    text = "tool --password " + marker + continuation + " ./run.sh"
    assert checks._redact_hook_output(text) == "tool --password ***" + continuation + " ./run.sh"
    count += 1
    # Backslash parity and single-quote semantics decide whether the closing
    # quote really closes; a wrong state hides the next doctor record.
    for quote, counts in ((double_quote, (0, 2)), (single_quote, (0, 1, 2, 3))):
        for backslashes in counts:
            for newline in ("\n", "\r\n"):
                text = (
                    "PASSWORD=" + quote + "SECRETvalue" + chr(92) * backslashes
                    + quote + chr(92) + newline + MARK_BAD + " next"
                )
                out = checks._redact_hook_output(text)
                assert "SECRETvalue" not in out, (quote, backslashes, newline, out)
                assert MARK_BAD + " next" in out, (quote, backslashes, newline, out)
                count += 1
    print(f"OK: {count} continued-credential and diagnostic-boundary cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(selftest())
