#!/usr/bin/env python3
"""Tests for check_review_round_clean.py."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_review_round_clean as gate

gate.rl._fetch_check_runs = lambda _sha: []


def test_is_bot_author():
    assert gate._is_bot_author("dependabot[bot]")
    assert not gate._is_bot_author("iap")
    assert not gate._is_bot_author("bot")


def test_get_pr_author_bot_typename_without_suffix():
    orig = gate.rl._run_gh_graphql
    try:
        gate.rl._run_gh_graphql = lambda _q: {
            "data": {
                "repository": {
                    "pullRequest": {
                        "author": {"login": "dependabot", "__typename": "Bot"}
                    }
                }
            }
        }
        login = gate._get_pr_author(42)
    finally:
        gate.rl._run_gh_graphql = orig
    assert login == "dependabot[bot]"
    assert gate._is_bot_author(login)


def test_get_pr_author_bot_typename_keeps_existing_suffix():
    orig = gate.rl._run_gh_graphql
    try:
        gate.rl._run_gh_graphql = lambda _q: {
            "data": {
                "repository": {
                    "pullRequest": {
                        "author": {"login": "dependabot[bot]", "__typename": "Bot"}
                    }
                }
            }
        }
        login = gate._get_pr_author(42)
    finally:
        gate.rl._run_gh_graphql = orig
    assert login == "dependabot[bot]"


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


def test_check_ledger_non_review_open_blocks():
    ledger = {
        "pr": 42,
        "head_commit": "abc123",
        "merge_ready": True,
        "rounds": [
            {
                "qodo_clean": True,
                "coderabbit_clean": True,
                "summary": {
                    "qodo_open": 0,
                    "coderabbit_open": 0,
                    "non_review_open": 2,
                },
            }
        ],
    }
    failures = gate._check_ledger(ledger, 42, "abc123")
    assert any("non-review thread" in f for f in failures)


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


def test_fetch_fresh_ledger_parses_stub_response():
    calls = []

    def _fake(query):
        calls.append(query)
        if "reviewThreads" in query:
            return {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "headRefOid": "abc123",
                            "reviewThreads": {
                                "pageInfo": {"hasNextPage": False},
                                "nodes": [],
                            },
                        }
                    }
                }
            }
        return {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviews": {
                            "pageInfo": {"hasNextPage": False},
                            "nodes": [
                                {
                                    "author": {"login": "qodo-code-review[bot]"},
                                    "state": "COMMENTED",
                                    "commit": {"oid": "abc123"},
                                },
                                {
                                    "author": {"login": "coderabbitai[bot]"},
                                    "state": "COMMENTED",
                                    "commit": {"oid": "abc123"},
                                },
                            ],
                        }
                    }
                }
            }
        }

    orig = gate.rl._run_gh_graphql
    try:
        gate.rl._run_gh_graphql = _fake
        ledger = gate._fetch_fresh_ledger(448)
    finally:
        gate.rl._run_gh_graphql = orig

    assert ledger["pr"] == 448
    assert ledger["head_commit"] == "abc123"
    assert len(ledger["rounds"]) == 1
    assert ledger["merge_ready"] is True


def test_cli_live_failure_fails_closed():
    # Qodo #2: live fetch raising must fail the gate, never PASS on a ledger.
    import argparse

    orig_parse = argparse.ArgumentParser.parse_args
    orig_get_head = gate._get_pr_head
    orig_get_author = gate._get_pr_author
    orig_fetch = gate.rl._fetch_pr_threads

    def _raise(*a, **k):
        raise RuntimeError("simulated gh failure")

    try:
        gate._get_pr_head = lambda _pr: "abc123"
        gate._get_pr_author = lambda _pr: ""
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
                        "merge_ready": True,
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
        gate._get_pr_author = orig_get_author
        gate.rl._fetch_pr_threads = orig_fetch
        argparse.ArgumentParser.parse_args = orig_parse


def test_cli_pass_returns_zero():
    import argparse

    orig_parse = argparse.ArgumentParser.parse_args
    orig_get_head = gate._get_pr_head
    orig_get_author = gate._get_pr_author
    orig_fetch = gate.rl._fetch_pr_threads
    try:
        gate._get_pr_head = lambda _pr: "abc123"
        gate._get_pr_author = lambda _pr: ""
        gate.rl._fetch_pr_threads = lambda _pr: ([], "abc123", [])
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
                        "merge_ready": True,
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
                pr=42, ledger=str(p), no_live_check=True
            )
            assert gate.main() == 0
    finally:
        gate._get_pr_head = orig_get_head
        gate._get_pr_author = orig_get_author
        gate.rl._fetch_pr_threads = orig_fetch
        argparse.ArgumentParser.parse_args = orig_parse


def test_cli_head_error_returns_two():
    import argparse

    orig_parse = argparse.ArgumentParser.parse_args
    orig_get_head = gate._get_pr_head
    try:
        def _raise(*a, **k):
            raise RuntimeError("no head")

        gate._get_pr_head = _raise
        argparse.ArgumentParser.parse_args = lambda self: argparse.Namespace(
            pr=42, ledger=None, no_live_check=True
        )
        assert gate.main() == 2
    finally:
        gate._get_pr_head = orig_get_head
        argparse.ArgumentParser.parse_args = orig_parse


def _live_ledger(tmpdir, head="abc123"):
    import json
    from pathlib import Path

    p = Path(tmpdir) / "ledger.json"
    p.write_text(
        json.dumps(
            {
                "pr": 42,
                "head_commit": head,
                "merge_ready": True,
                "rounds": [
                    {
                        "round": 1,
                        "head_commit": head,
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
    return str(p)


def test_cli_live_human_thread_blocks():
    import argparse

    orig_parse = argparse.ArgumentParser.parse_args
    orig_get_head = gate._get_pr_head
    orig_get_author = gate._get_pr_author
    orig_fetch = gate.rl._fetch_pr_threads
    try:
        gate._get_pr_head = lambda _pr: "abc123"
        gate._get_pr_author = lambda _pr: ""
        gate.rl._fetch_pr_threads = lambda _pr: (
            [
                {
                    "id": "TH",
                    "isResolved": False,
                    "comments": {
                        "nodes": [
                            {
                                "author": {"login": "human.user"},
                                "body": "please check",
                                "path": "a.py",
                                "line": 1,
                                "createdAt": "2026-11-08T00:00:00Z",
                            }
                        ]
                    },
                }
            ],
            "abc123",
            [
                {"author": {"login": "qodo-code-review[bot]"}, "state": "COMMENTED", "commit": {"oid": "abc123"}},
                {"author": {"login": "coderabbitai[bot]"}, "state": "COMMENTED", "commit": {"oid": "abc123"}},
            ],
        )
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            p = _live_ledger(td)
            argparse.ArgumentParser.parse_args = lambda self: argparse.Namespace(
                pr=42, ledger=p, no_live_check=False
            )
            assert gate.main() == 1
    finally:
        gate._get_pr_head = orig_get_head
        gate._get_pr_author = orig_get_author
        gate.rl._fetch_pr_threads = orig_fetch
        argparse.ArgumentParser.parse_args = orig_parse


def test_cli_live_head_mismatch_blocks():
    import argparse

    orig_parse = argparse.ArgumentParser.parse_args
    orig_get_head = gate._get_pr_head
    orig_get_author = gate._get_pr_author
    orig_fetch = gate.rl._fetch_pr_threads
    try:
        gate._get_pr_head = lambda _pr: "abc123"
        gate._get_pr_author = lambda _pr: ""
        gate.rl._fetch_pr_threads = lambda _pr: (
            [],
            "def456",
            [
                {"author": {"login": "qodo-code-review[bot]"}, "state": "COMMENTED", "commit": {"oid": "def456"}},
                {"author": {"login": "coderabbitai[bot]"}, "state": "COMMENTED", "commit": {"oid": "def456"}},
            ],
        )
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            p = _live_ledger(td)
            argparse.ArgumentParser.parse_args = lambda self: argparse.Namespace(
                pr=42, ledger=p, no_live_check=False
            )
            assert gate.main() == 1
    finally:
        gate._get_pr_head = orig_get_head
        gate._get_pr_author = orig_get_author
        gate.rl._fetch_pr_threads = orig_fetch
        argparse.ArgumentParser.parse_args = orig_parse


def test_cli_live_clean_passes():
    import argparse

    orig_parse = argparse.ArgumentParser.parse_args
    orig_get_head = gate._get_pr_head
    orig_get_author = gate._get_pr_author
    orig_fetch = gate.rl._fetch_pr_threads
    try:
        gate._get_pr_head = lambda _pr: "abc123"
        gate._get_pr_author = lambda _pr: ""
        gate.rl._fetch_pr_threads = lambda _pr: (
            [],
            "abc123",
            [
                {"author": {"login": "qodo-code-review[bot]"}, "state": "COMMENTED", "commit": {"oid": "abc123"}},
                {"author": {"login": "coderabbitai[bot]"}, "state": "COMMENTED", "commit": {"oid": "abc123"}},
            ],
        )
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            p = _live_ledger(td)
            argparse.ArgumentParser.parse_args = lambda self: argparse.Namespace(
                pr=42, ledger=p, no_live_check=False
            )
            assert gate.main() == 0
    finally:
        gate._get_pr_head = orig_get_head
        gate._get_pr_author = orig_get_author
        gate.rl._fetch_pr_threads = orig_fetch
        argparse.ArgumentParser.parse_args = orig_parse


def test_cli_live_no_reviews_blocks():
    import argparse

    orig_parse = argparse.ArgumentParser.parse_args
    orig_get_head = gate._get_pr_head
    orig_get_author = gate._get_pr_author
    orig_fetch = gate.rl._fetch_pr_threads
    try:
        gate._get_pr_head = lambda _pr: "abc123"
        gate._get_pr_author = lambda _pr: ""
        gate.rl._fetch_pr_threads = lambda _pr: ([], "abc123", [])
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            p = _live_ledger(td)
            argparse.ArgumentParser.parse_args = lambda self: argparse.Namespace(
                pr=42, ledger=p, no_live_check=False
            )
            assert gate.main() == 1
    finally:
        gate._get_pr_head = orig_get_head
        gate._get_pr_author = orig_get_author
        gate.rl._fetch_pr_threads = orig_fetch
        argparse.ArgumentParser.parse_args = orig_parse


def test_cli_live_old_head_blocks():
    import argparse

    orig_parse = argparse.ArgumentParser.parse_args
    orig_get_head = gate._get_pr_head
    orig_get_author = gate._get_pr_author
    orig_fetch = gate.rl._fetch_pr_threads
    try:
        gate._get_pr_head = lambda _pr: "abc123"
        gate._get_pr_author = lambda _pr: ""
        gate.rl._fetch_pr_threads = lambda _pr: (
            [],
            "abc123",
            [
                {"author": {"login": "qodo-code-review[bot]"}, "state": "COMMENTED", "commit": {"oid": "old"}},
                {"author": {"login": "coderabbitai[bot]"}, "state": "COMMENTED", "commit": {"oid": "old"}},
            ],
        )
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            p = _live_ledger(td)
            argparse.ArgumentParser.parse_args = lambda self: argparse.Namespace(
                pr=42, ledger=p, no_live_check=False
            )
            assert gate.main() == 1
    finally:
        gate._get_pr_head = orig_get_head
        gate._get_pr_author = orig_get_author
        gate.rl._fetch_pr_threads = orig_fetch
        argparse.ArgumentParser.parse_args = orig_parse


def test_cli_live_coderabbit_check_accepts():
    import argparse

    orig_parse = argparse.ArgumentParser.parse_args
    orig_head = gate._get_pr_head
    orig_author = gate._get_pr_author
    orig_fetch = gate.rl._fetch_pr_threads
    orig_runs = gate.rl._fetch_check_runs
    try:
        gate._get_pr_head = lambda _pr: "abc123"
        gate._get_pr_author = lambda _pr: ""
        gate.rl._fetch_pr_threads = lambda _pr: (
            [],
            "abc123",
            [
                {
                    "author": {"login": "qodo-code-review[bot]"},
                    "state": "COMMENTED",
                    "commit": {"oid": "abc123"},
                }
            ],
        )
        gate.rl._fetch_check_runs = lambda _sha: [
            {
                "app": {"slug": "coderabbitai"},
                "status": "completed",
                "conclusion": "SUCCESS",
            }
        ]
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            p = _live_ledger(td)
            argparse.ArgumentParser.parse_args = lambda self: argparse.Namespace(
                pr=42, ledger=p, no_live_check=False
            )
            assert gate.main() == 0
    finally:
        gate._get_pr_head = orig_head
        gate._get_pr_author = orig_author
        gate.rl._fetch_pr_threads = orig_fetch
        gate.rl._fetch_check_runs = orig_runs
        argparse.ArgumentParser.parse_args = orig_parse


def test_cli_bot_author_skips():
    import argparse

    orig_parse = argparse.ArgumentParser.parse_args
    orig_head = gate._get_pr_head
    orig_author = gate._get_pr_author
    try:
        gate._get_pr_head = lambda _pr: "abc123"
        gate._get_pr_author = lambda _pr: "dependabot[bot]"
        argparse.ArgumentParser.parse_args = lambda self: argparse.Namespace(
            pr=42, ledger="does-not-exist.json", no_live_check=True
        )
        assert gate.main() == 0
    finally:
        gate._get_pr_head = orig_head
        gate._get_pr_author = orig_author
        argparse.ArgumentParser.parse_args = orig_parse


def test_cli_ledger_failure_returns_one():
    import argparse

    orig_parse = argparse.ArgumentParser.parse_args
    orig_head = gate._get_pr_head
    orig_author = gate._get_pr_author
    try:
        gate._get_pr_head = lambda _pr: "abc123"
        gate._get_pr_author = lambda _pr: ""
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
                        "merge_ready": False,
                        "rounds": [
                            {
                                "qodo_clean": False,
                                "coderabbit_clean": True,
                                "summary": {"qodo_open": 1, "coderabbit_open": 0},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            argparse.ArgumentParser.parse_args = lambda self: argparse.Namespace(
                pr=42, ledger=str(p), no_live_check=True
            )
            assert gate.main() == 1
    finally:
        gate._get_pr_head = orig_head
        gate._get_pr_author = orig_author
        argparse.ArgumentParser.parse_args = orig_parse


def test_cli_invalid_ledger_returns_two():
    import argparse

    orig_parse = argparse.ArgumentParser.parse_args
    orig_head = gate._get_pr_head
    orig_author = gate._get_pr_author
    try:
        gate._get_pr_head = lambda _pr: "abc123"
        gate._get_pr_author = lambda _pr: ""
        import json
        import tempfile
        from pathlib import Path

        for bad in (
            [],
            {"rounds": [None]},
            {"rounds": [{"summary": None}]},
            {"rounds": [{"summary": {"qodo_open": "1"}}]},
        ):
            with tempfile.TemporaryDirectory() as td:
                p = Path(td) / "ledger.json"
                p.write_text(json.dumps(bad), encoding="utf-8")
                argparse.ArgumentParser.parse_args = lambda self: argparse.Namespace(
                    pr=42, ledger=str(p), no_live_check=True
                )
                assert gate.main() == 2
    finally:
        gate._get_pr_head = orig_head
        gate._get_pr_author = orig_author
        argparse.ArgumentParser.parse_args = orig_parse


def test_cli_failure_goes_to_stderr():
    import argparse
    import contextlib
    import io
    import json
    import tempfile
    from pathlib import Path

    orig_parse = argparse.ArgumentParser.parse_args
    orig_head = gate._get_pr_head
    orig_author = gate._get_pr_author
    try:
        gate._get_pr_head = lambda _pr: "abc123"
        gate._get_pr_author = lambda _pr: ""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "ledger.json"
            p.write_text(
                json.dumps(
                    {
                        "pr": 42,
                        "head_commit": "oldhead",
                        "merge_ready": True,
                        "rounds": [
                            {
                                "qodo_clean": True,
                                "coderabbit_clean": True,
                                "summary": {"qodo_open": 0, "coderabbit_open": 0},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            argparse.ArgumentParser.parse_args = lambda self: argparse.Namespace(
                pr=42, ledger=str(p), no_live_check=True
            )
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                assert gate.main() == 1
            assert "REVIEW ROUND GATE: FAIL" in err.getvalue()
            assert "REVIEW ROUND GATE: FAIL" not in out.getvalue()
    finally:
        gate._get_pr_head = orig_head
        gate._get_pr_author = orig_author
        argparse.ArgumentParser.parse_args = orig_parse


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
