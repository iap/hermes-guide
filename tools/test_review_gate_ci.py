#!/usr/bin/env python3
"""Guard that the review gate stays wired into reusable CI.

Qodo #8: nothing verified the workflow still runs the gate. This test
fails if the step or its regression siblings are removed.
"""
import pathlib

WORKFLOW = pathlib.Path(__file__).resolve().parent.parent / ".github/workflows/reusable-ci.yml"


def _gate_job(text: str) -> str:
    start = text.index("check_review_gate:")
    end = text.index("\n  legacy-mac:", start)
    return text[start:end]


def _gate_step(text: str) -> str:
    return _gate_job(text).split("- name: Review round clean gate", 1)[1]


def _gate_command_ok(text: str) -> bool:
    step = _gate_step(text)
    return (
        "if: runner.os == 'Linux'" in step
        and 'python tools/check_review_round_clean.py --pr "$PR_NUMBER"' in step
        and "--no-live-check" not in step
    )


def test_review_gate_wired():
    text = WORKFLOW.read_text(encoding="utf-8")
    job = _gate_job(text)
    assert "check_review_gate:" in text
    assert "needs: plugin" in job
    assert "if: inputs.run-full-gate && inputs.event-name == 'pull_request'" in job
    assert "Review round clean gate" in job
    assert "tools/check_review_round_clean.py" in job
    assert "Review round clean gate regression" in text
    assert "tools/test_check_review_round_clean.py" in text
    assert "Review ledger regression" in text
    assert "tools/test_review_ledger.py" in text
    assert _gate_command_ok(text), "gate step must stay enabled and run the live gate"


def test_review_gate_command_regressions():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert not _gate_command_ok(text.replace("if: runner.os == 'Linux'", "if: false"))
    assert not _gate_command_ok(
        text.replace(
            'python tools/check_review_round_clean.py --pr "$PR_NUMBER"',
            'python tools/check_review_round_clean.py --pr "$PR_NUMBER" --no-live-check',
        )
    )


if __name__ == "__main__":
    test_review_gate_wired()
    test_review_gate_command_regressions()
    print("PASS: review gate CI wiring")
