#!/usr/bin/env python3
"""Tests for review_ledger.py."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_ledger as rl

# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


def test_classify_bot_qodo():
    assert rl._classify_bot("qodo-code-review") == "qodo"
    assert rl._classify_bot("qodo-code-review[bot]") == "qodo"
    assert rl._classify_bot("Qodo-Code-Review") == "qodo"


def test_classify_bot_coderabbit():
    assert rl._classify_bot("coderabbitai") == "coderabbit"
    assert rl._classify_bot("coderabbitai[bot]") == "coderabbit"
    assert rl._classify_bot("CodeRabbit") == "coderabbit"


def test_classify_bot_unknown():
    assert rl._classify_bot("github-actions") is None
    assert rl._classify_bot("dependabot") is None
    assert rl._classify_bot("") is None


def test_extract_severity_high():
    body = "## High\nSome issue"
    assert rl._extract_severity(body) == "high"


def test_extract_severity_medium():
    body = "## Medium\nSome issue"
    assert rl._extract_severity(body) == "medium"


def test_extract_severity_low():
    body = "## Low\nSome issue"
    assert rl._extract_severity(body) == "low"


def test_extract_severity_trivial():
    body = "This is a trivial change"
    assert rl._extract_severity(body) == "minor"


def test_extract_severity_unknown():
    body = "Just a comment"
    assert rl._extract_severity(body) == "unknown"


def test_parse_threads_empty():
    findings, _ = rl._parse_threads([])
    assert findings == []


def test_parse_threads_qodo_resolved():
    threads = [
        {
            "id": "T1",
            "isResolved": True,
            "comments": {
                "nodes": [
                    {
                        "author": {"login": "qodo-code-review"},
                        "body": "## High\nFix this",
                        "path": "checks.py",
                        "line": 10,
                        "createdAt": "2026-11-08T00:00:00Z",
                    }
                ]
            },
        }
    ]
    findings, _ = rl._parse_threads(threads)
    assert len(findings) == 1
    assert findings[0]["bot"] == "qodo"
    assert findings[0]["status"] == "resolved"
    assert findings[0]["severity"] == "high"
    assert findings[0]["file"] == "checks.py"
    assert findings[0]["line"] == 10


def test_parse_threads_coderabbit_open():
    threads = [
        {
            "id": "T2",
            "isResolved": False,
            "comments": {
                "nodes": [
                    {
                        "author": {"login": "coderabbitai[bot]"},
                        "body": "## Low\nNitpick",
                        "path": "tools/x.py",
                        "line": 5,
                        "createdAt": "2026-11-08T00:00:00Z",
                    }
                ]
            },
        }
    ]
    findings, _ = rl._parse_threads(threads)
    assert len(findings) == 1
    assert findings[0]["bot"] == "coderabbit"
    assert findings[0]["status"] == "open"
    assert findings[0]["severity"] == "low"


def test_parse_threads_skips_non_bot():
    threads = [
        {
            "id": "T3",
            "isResolved": False,
            "comments": {
                "nodes": [
                    {
                        "author": {"login": "human-user"},
                        "body": "LGTM",
                        "path": None,
                        "line": None,
                        "createdAt": "2026-11-08T00:00:00Z",
                    }
                ]
            },
        }
    ]
    findings, _ = rl._parse_threads(threads)
    assert findings == []


def test_parse_threads_empty_comments():
    threads = [{"id": "T4", "isResolved": False, "comments": {"nodes": []}}]
    findings, _ = rl._parse_threads(threads)
    assert findings == []


def test_unresolved_findings():
    findings = [
        {"status": "open", "bot": "qodo"},
        {"status": "resolved", "bot": "qodo"},
        {"status": "open", "bot": "coderabbit"},
    ]
    open_ones = rl.unresolved_findings(findings)
    assert len(open_ones) == 2


def test_build_ledger_merge_ready():
    findings = [
        {
            "thread_id": "T1",
            "bot": "qodo",
            "severity": "high",
            "title": "Fix",
            "file": "a.py",
            "line": 1,
            "status": "resolved",
            "created_at": None,
        },
        {
            "thread_id": "T2",
            "bot": "coderabbit",
            "severity": "low",
            "title": "Nit",
            "file": "b.py",
            "line": 2,
            "status": "resolved",
            "created_at": None,
        },
    ]
    ledger = rl.build_ledger(42, "abc123", findings, True, True)
    assert ledger["merge_ready"] is True
    assert ledger["rounds"][0]["qodo_clean"] is True
    assert ledger["rounds"][0]["coderabbit_clean"] is True
    assert ledger["rounds"][0]["summary"]["total_findings"] == 2
    assert ledger["rounds"][0]["summary"]["qodo_open"] == 0
    assert ledger["rounds"][0]["summary"]["coderabbit_open"] == 0


def test_build_ledger_not_merge_ready_open_findings():
    findings = [
        {
            "thread_id": "T1",
            "bot": "qodo",
            "severity": "high",
            "title": "Fix",
            "file": "a.py",
            "line": 1,
            "status": "open",
            "created_at": None,
        },
        {
            "thread_id": "T2",
            "bot": "coderabbit",
            "severity": "low",
            "title": "Nit",
            "file": "b.py",
            "line": 2,
            "status": "resolved",
            "created_at": None,
        },
    ]
    ledger = rl.build_ledger(42, "abc123", findings, True, True)
    assert ledger["merge_ready"] is False
    assert ledger["rounds"][0]["qodo_clean"] is False
    assert ledger["rounds"][0]["coderabbit_clean"] is True


def test_build_ledger_no_findings():
    ledger = rl.build_ledger(42, "abc123", [], False, False)
    assert ledger["merge_ready"] is False
    assert ledger["rounds"][0]["qodo_clean"] is False
    assert ledger["rounds"][0]["coderabbit_clean"] is False


def test_build_ledger_no_findings_clean_when_reviewed():
    ledger = rl.build_ledger(42, "abc123", [], True, True)
    assert ledger["merge_ready"] is True
    assert ledger["rounds"][0]["qodo_clean"] is True
    assert ledger["rounds"][0]["coderabbit_clean"] is True


def test_parse_threads_deleted_author():
    threads = [
        {
            "id": "T5",
            "isResolved": False,
            "comments": {
                "nodes": [
                    {
                        "author": None,
                        "body": "ghost comment",
                        "path": "a.py",
                        "line": 1,
                        "createdAt": "2026-11-08T00:00:00Z",
                    }
                ]
            },
        }
    ]
    findings, human_open_count = rl._parse_threads(threads)
    assert findings == []
    assert human_open_count == 1


def test_classify_bot_exact_only():
    assert rl._classify_bot("qodo-code-review") == "qodo"
    assert rl._classify_bot("qodo-code-review[bot]") == "qodo"
    assert rl._classify_bot("coderabbitai[bot]") == "coderabbit"
    assert rl._classify_bot("notcoderabbit") is None
    assert rl._classify_bot("iamqodo-code-review") is None
    assert rl._classify_bot("human-user") is None


def test_build_ledger_human_open_blocks():
    findings = [
        {
            "thread_id": "T1",
            "bot": "qodo",
            "severity": "low",
            "title": "t",
            "file": "a.py",
            "line": 1,
            "status": "resolved",
            "created_at": None,
        }
    ]
    ledger = rl.build_ledger(42, "abc123", findings, True, True, 1)
    assert ledger["merge_ready"] is False
    assert ledger["rounds"][0]["summary"]["human_open"] == 1


def test_compute_reviewed_chronology():
    q, _c = rl.compute_reviewed(
        [
            {
                "author": {"login": "qodo-code-review[bot]"},
                "state": "COMMENTED",
                "commit": {"oid": "abc123"},
            },
            {
                "author": {"login": "qodo-code-review[bot]"},
                "state": "CHANGES_REQUESTED",
                "commit": {"oid": "abc123"},
            },
        ],
        "abc123",
    )
    assert q is False


def test_compute_reviewed_changes_requested():
    q, _c = rl.compute_reviewed(
        [
            {
                "author": {"login": "qodo-code-review[bot]"},
                "state": "CHANGES_REQUESTED",
            }
        ]
    )
    assert q is False


def test_compute_reviewed_cr_chronology():
    # Later COMMENTED must not clear CHANGES_REQUESTED; only APPROVED does.
    blocked = [
        {
            "author": {"login": "coderabbitai[bot]"},
            "state": "COMMENTED",
            "commit": {"oid": "abc123"},
        },
        {
            "author": {"login": "coderabbitai[bot]"},
            "state": "CHANGES_REQUESTED",
            "commit": {"oid": "abc123"},
        },
        {
            "author": {"login": "coderabbitai[bot]"},
            "state": "COMMENTED",
            "commit": {"oid": "abc123"},
        },
    ]
    _q, cr = rl.compute_reviewed(blocked, "abc123")
    assert cr is False
    approved = blocked + [
        {
            "author": {"login": "coderabbitai[bot]"},
            "state": "APPROVED",
            "commit": {"oid": "abc123"},
        }
    ]
    _q2, cr2 = rl.compute_reviewed(approved, "abc123")
    assert cr2 is True


def test_compute_reviewed_stale_head():
    q, _c = rl.compute_reviewed(
        [
            {
                "author": {"login": "qodo-code-review[bot]"},
                "state": "COMMENTED",
                "commit": {"oid": "oldhead"},
            }
        ],
        "newhead",
    )
    assert q is False


def test_run_gh_graphql_utf8():
    import json as _json
    import subprocess as _sp

    class Fake:
        returncode = 0
        stdout = _json.dumps({"data": {"x": "caf\u00e9 \U0001f600"}}, ensure_ascii=False)
        stderr = ""

    orig = _sp.run
    try:
        _sp.run = lambda *a, **k: Fake()
        data = rl._run_gh_graphql("query {}")
        assert data["data"]["x"] == "caf\u00e9 \U0001f600"
    finally:
        _sp.run = orig


def test_compute_reviewed():
    q, c = rl.compute_reviewed(
        [
            {"author": {"login": "qodo-code-review[bot]"}},
            {"author": {"login": "coderabbitai[bot]"}},
        ]
    )
    assert q is True and c is True
    q2, c2 = rl.compute_reviewed([{"author": {"login": "human"}}])
    assert q2 is False and c2 is False


def test_build_ledger_only_qodo():
    findings = [
        {
            "thread_id": "T1",
            "bot": "qodo",
            "severity": "high",
            "title": "Fix",
            "file": "a.py",
            "line": 1,
            "status": "resolved",
            "created_at": None,
        },
    ]
    ledger = rl.build_ledger(42, "abc123", findings, True, False)
    assert ledger["merge_ready"] is False
    assert ledger["rounds"][0]["qodo_clean"] is True
    assert ledger["rounds"][0]["coderabbit_clean"] is False


def test_write_ledger():
    ledger = {"pr": 1, "merge_ready": False, "rounds": []}
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "sub" / "ledger.json"
        rl.write_ledger(ledger, out)
        assert out.exists()
        with open(out) as f:
            data = json.load(f)
        assert data["pr"] == 1


def test_extract_title_bold():
    body = "**Fix the bug**\nDetails here"
    title = rl._extract_title(body)
    assert "Fix the bug" in title


def test_extract_title_fallback():
    body = "Just a plain comment\nSecond line"
    title = rl._extract_title(body)
    assert title == "Just a plain comment"


# ---------------------------------------------------------------------------
# Integration test (requires gh CLI + network)
# ---------------------------------------------------------------------------


def test_integration_pr_448():
    """Fetch real PR 448 threads and verify structure."""
    try:
        threads, head_oid, _reviews = rl._fetch_pr_threads(448)
    except (RuntimeError, KeyError, TypeError, ValueError) as exc:
        if "gh" in str(exc).lower() or "not found" in str(exc).lower():
            print("SKIP: gh not available or not authenticated")
            return
        raise
    assert isinstance(threads, list)
    assert len(threads) > 0
    assert isinstance(head_oid, str)
    assert len(head_oid) == 40
    findings, _ = rl._parse_threads(threads)
    assert len(findings) > 0
    bots = {f["bot"] for f in findings}
    assert "qodo" in bots or "coderabbit" in bots


if __name__ == "__main__":
    # Run all tests
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
