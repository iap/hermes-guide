#!/usr/bin/env python3
"""Guard that the review gate stays wired into reusable CI.

Qodo #8: nothing verified the workflow still runs the gate. This test
fails if the step or its regression siblings are removed.
"""
import pathlib

WORKFLOW = pathlib.Path(__file__).resolve().parent.parent / ".github/workflows/reusable-ci.yml"


def test_review_gate_wired():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Review round clean gate" in text
    assert "tools/check_review_round_clean.py" in text
    assert "check_review_gate:" in text
    assert "needs: plugin" in text
    assert "inputs.event-name == 'pull_request'" in text
    assert "--pr" in text
    assert "Review round clean gate regression" in text
    assert "tools/test_check_review_round_clean.py" in text
    assert "Review ledger regression" in text
    assert "tools/test_review_ledger.py" in text


if __name__ == "__main__":
    test_review_gate_wired()
    print("PASS: review gate CI wiring")
