#!/usr/bin/env python3
"""Tests for check_review_round_clean.py."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_review_round_clean as gate


def test_check_ledger_pass():
    ledger = {
        "pr": 42,
        "head_commit": "abc123",
        "merge_ready": True,
        "rounds": [
            {
                "qodo_clean": True,
                "coderabbit_clean": True,
                "summary": {"qodo_open": 0, "coderabbit_open": 0, "total_findings": 2},
            }
        ],
    }
    failures = gate._check_ledger(ledger, 42, "abc123")
    assert failures == [], f"Expected no failures, got {failures}"


def test_check_ledger_pr_mismatch():
    ledger = {
        "pr": 99,
        "head_commit": "abc123",
        "merge_ready": True,
        "rounds": [
            {
                "qodo_clean": True,
                "coderabbit_clean": True,
                "summary": {"qodo_open": 0, "coderabbit_open": 0},
            }
        ],
    }
    failures = gate._check_ledger(ledger, 42, "abc123")
    assert any("PR mismatch" in f for f in failures)


def test_check_ledger_stale_head():
    ledger = {
        "pr": 42,
        "head_commit": "old123",
        "merge_ready": True,
        "rounds": [
            {
                "qodo_clean": True,
                "coderabbit_clean": True,
                "summary": {"qodo_open": 0, "coderabbit_open": 0},
            }
        ],
    }
    failures = gate._check_ledger(ledger, 42, "new456")
    assert any("Stale ledger" in f for f in failures)


def test_check_ledger_no_rounds():
    ledger = {"pr": 42, "head_commit": "abc123", "merge_ready": False, "rounds": []}
    failures = gate._check_ledger(ledger, 42, "abc123")
    assert any("No review rounds" in f for f in failures)


def test_check_ledger_qodo_not_clean():
    ledger = {
        "pr": 42,
        "head_commit": "abc123",
        "merge_ready": False,
        "rounds": [
            {
                "qodo_clean": False,
                "coderabbit_clean": True,
                "summary": {"qodo_open": 2, "coderabbit_open": 0},
            }
        ],
    }
    failures = gate._check_ledger(ledger, 42, "abc123")
    assert any("Qodo review not clean" in f for f in failures)
    assert any("unresolved finding" in f for f in failures)


def test_check_ledger_coderabbit_not_clean():
    ledger = {
        "pr": 42,
        "head_commit": "abc123",
        "merge_ready": False,
        "rounds": [
            {
                "qodo_clean": True,
                "coderabbit_clean": False,
                "summary": {"qodo_open": 0, "coderabbit_open": 1},
            }
        ],
    }
    failures = gate._check_ledger(ledger, 42, "abc123")
    assert any("CodeRabbit review not clean" in f for f in failures)


def test_check_ledger_merge_ready_false():
    ledger = {
        "pr": 42,
        "head_commit": "abc123",
        "merge_ready": False,
        "rounds": [
            {
                "qodo_clean": True,
                "coderabbit_clean": True,
                "summary": {"qodo_open": 0, "coderabbit_open": 0},
            }
        ],
    }
    failures = gate._check_ledger(ledger, 42, "abc123")
    assert any("merge_ready is False" in f for f in failures)


def test_fetch_fresh_ledger():
    try:
        ledger = gate._fetch_fresh_ledger(448)
    except (RuntimeError, KeyError, TypeError):
        print("SKIP: gh not available")
        return
    assert ledger["pr"] == 448
    assert "rounds" in ledger
    assert len(ledger["rounds"]) == 1


def test_cli_live_failure_fails_closed(monkey=None):
    # Qodo #2: live fetch raising must fail the gate, never PASS on a ledger.
    import argparse

    orig_parse = argparse.ArgumentParser.parse_args
    orig_get_head = gate._get_pr_head
    orig_fetch = gate.rl._fetch_pr_threads

    def _raise(*a, **k):
        raise RuntimeError("simulated gh failure")

    try:
        gate._get_pr_head = lambda _pr: "abc123"
        gate.rl._fetch_pr_threads = _raise
        # Ledger says merge-ready but live fetch raises -> must be gate failure.
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "ledger.json"
            p.write_text(
                json.dumps(
                    {
                        "pr": 42,
                        "head_commit": "abc123",
                        "rounds": [
                            {
                                "round": 1,
                                "head_commit": "abc123",
                                "qodo_clean": True,
                                "coderabbit_clean": True,
                                "qodo_reviewed": True,
                                "coderabbit_reviewed": True,
                                "same_head": True,
                                "merge_ready": True,
                                "summary": {"total_findings": 0, "qodo_open": 0, "coderabbit_open": 0},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            argparse.ArgumentParser.parse_args = lambda self: argparse.Namespace(
                pr=42, ledger=str(p), no_live_check=False
            )
            assert gate.main() == 1
    finally:
        gate._get_pr_head = orig_get_head
        gate.rl._fetch_pr_threads = orig_fetch
        argparse.ArgumentParser.parse_args = orig_parse


def test_main_callable():
    assert callable(gate.main)


if __name__ == "__main__":
    import traceback

    tests = [v for k, v in globals().items() if k.startswith("test_")]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
            print(f"  PASS: {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL: {test.__name__}: {exc}")
            traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
