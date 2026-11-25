#!/usr/bin/env python3
"""Tests for review_ledger.py."""

from __future__ import annotations

import json
import os
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


def test_extract_severity_does_not_match_substrings():
    assert rl._extract_severity("Use shared state safely") == "unknown"


def test_extract_severity_qodo_emoji():
    assert rl._extract_severity("🔴 **High** 5. Old reviews") == "high"


def test_extract_severity_coderabbit_minor_beats_low_value():
    body = (
        "<!-- coderabbit-ai-generated:v1 -->\n\n"
        '**<picture><img alt=""></picture> Minor** · '
        "**Functional Correctness** · **Low value**"
    )
    assert rl._extract_severity(body) == "minor"


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


def test_parse_threads_outdated_not_open():
    threads = [
        {
            "id": "T-outdated",
            "isResolved": False,
            "isOutdated": True,
            "comments": {
                "nodes": [
                    {
                        "author": {"login": "qodo-code-review"},
                        "body": "## High\nAlready fixed",
                        "path": "checks.py",
                        "line": 10,
                        "createdAt": "2026-11-08T00:00:00Z",
                    }
                ]
            },
        }
    ]
    findings, non_review_open = rl._parse_threads(threads)
    assert findings[0]["status"] == "outdated"
    assert rl.unresolved_findings(findings) == []
    assert non_review_open == 0


def test_parse_threads_outdated_human_not_counted():
    threads = [
        {
            "id": "T-human-outdated",
            "isResolved": False,
            "isOutdated": True,
            "comments": {
                "nodes": [
                    {
                        "author": {"login": "human-user"},
                        "body": "old question",
                        "path": None,
                        "line": None,
                        "createdAt": "2026-11-08T00:00:00Z",
                    }
                ]
            },
        }
    ]
    _findings, non_review_open = rl._parse_threads(threads)
    assert non_review_open == 0


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


def test_parse_threads_null_author():
    threads = [
        {
            "id": "T-null-author",
            "isResolved": False,
            "isOutdated": False,
            "comments": {
                "nodes": [
                    {
                        "author": None,
                        "body": "deleted account",
                        "path": None,
                        "line": None,
                        "createdAt": "2026-11-08T00:00:00Z",
                    }
                ]
            },
        }
    ]
    findings, human = rl._parse_threads(threads)
    assert findings == []
    assert human == 1


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
    findings, non_review_open = rl._parse_threads(threads)
    assert findings == []
    assert non_review_open == 1


def test_classify_bot_exact_only():
    assert rl._classify_bot("qodo-code-review") == "qodo"
    assert rl._classify_bot("qodo-code-review[bot]") == "qodo"
    assert rl._classify_bot("coderabbitai[bot]") == "coderabbit"
    assert rl._classify_bot("notcoderabbit") is None
    assert rl._classify_bot("iamqodo-code-review") is None
    assert rl._classify_bot("human-user") is None


def test_build_ledger_non_review_open_blocks():
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
    assert ledger["rounds"][0]["summary"]["non_review_open"] == 1


def test_build_ledger_same_head_requires_both_bots():
    partial = rl.build_ledger(42, "abc123", [], True, False)
    assert partial["rounds"][0]["same_head"] is False
    both = rl.build_ledger(42, "abc123", [], True, True)
    assert both["rounds"][0]["same_head"] is True


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

    def fake_run(*a, **k):
        assert k.get("encoding") == "utf-8"
        return Fake()

    orig = _sp.run
    try:
        _sp.run = fake_run
        data = rl._run_gh_graphql("query {}")
        assert data["data"]["x"] == "caf\u00e9 \U0001f600"
    finally:
        _sp.run = orig


def test_run_gh_graphql_missing_binary():
    import subprocess as _sp

    orig = _sp.run

    def _raise(*a, **k):
        raise FileNotFoundError("gh")

    try:
        _sp.run = _raise
        try:
            rl._run_gh_graphql("query {}")
        except RuntimeError as exc:
            assert "gh" in str(exc).lower()
        else:
            raise AssertionError("expected RuntimeError when gh is missing")
    finally:
        _sp.run = orig


def test_run_gh_graphql_timeout():
    import subprocess as _sp

    orig = _sp.run

    def _raise(*a, **k):
        raise _sp.TimeoutExpired(["gh"], 60)

    try:
        _sp.run = _raise
        try:
            rl._run_gh_graphql("query {}")
        except RuntimeError as exc:
            assert "timed out" in str(exc).lower()
        else:
            raise AssertionError("expected RuntimeError on gh timeout")
    finally:
        _sp.run = orig


def test_compute_reviewed_sorts_by_submitted_at():
    # Input is newest-first; chronological order is COMMENTED then
    # CHANGES_REQUESTED, so the verdict must be blocked regardless of input order.
    q, _c = rl.compute_reviewed(
        [
            {
                "author": {"login": "qodo-code-review[bot]"},
                "state": "CHANGES_REQUESTED",
                "submittedAt": "2026-11-09T02:00:00Z",
                "commit": {"oid": "abc123"},
            },
            {
                "author": {"login": "qodo-code-review[bot]"},
                "state": "COMMENTED",
                "submittedAt": "2026-11-09T01:00:00Z",
                "commit": {"oid": "abc123"},
            },
        ],
        "abc123",
    )
    assert q is False


def test_compute_reviewed_approved_after_changes_scrambled():
    q, _c = rl.compute_reviewed(
        [
            {
                "author": {"login": "qodo-code-review[bot]"},
                "state": "APPROVED",
                "submittedAt": "2026-11-09T03:00:00Z",
                "commit": {"oid": "abc123"},
            },
            {
                "author": {"login": "qodo-code-review[bot]"},
                "state": "CHANGES_REQUESTED",
                "submittedAt": "2026-11-09T01:00:00Z",
                "commit": {"oid": "abc123"},
            },
        ],
        "abc123",
    )
    assert q is True


def test_fetch_pr_threads_paginates_reviews_and_fetches_submitted_at():
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
        if 'after: "c1"' in query:
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
                                        "submittedAt": "2026-11-09T02:00:00Z",
                                        "commit": {"oid": "abc123"},
                                    }
                                ],
                            }
                        }
                    }
                }
            }
        return {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviews": {
                            "pageInfo": {"hasNextPage": True, "endCursor": "c1"},
                            "nodes": [
                                {
                                    "author": {"login": "coderabbitai[bot]"},
                                    "state": "COMMENTED",
                                    "submittedAt": "2026-11-09T01:00:00Z",
                                    "commit": {"oid": "abc123"},
                                }
                            ],
                        }
                    }
                }
            }
        }

    orig = rl._run_gh_graphql
    try:
        rl._run_gh_graphql = _fake
        threads, head, reviews = rl._fetch_pr_threads(42)
    finally:
        rl._run_gh_graphql = orig

    assert threads == []
    assert head == "abc123"
    assert len(reviews) == 2
    assert any("submittedAt" in c for c in calls)
    assert any('after: "c1"' in c for c in calls)


def test_fetch_pr_threads_omits_empty_cursor():
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
                            "nodes": [],
                        }
                    }
                }
            }
        }

    orig = rl._run_gh_graphql
    try:
        rl._run_gh_graphql = _fake
        rl._fetch_pr_threads(42)
    finally:
        rl._run_gh_graphql = orig

    assert calls
    assert "after:" not in calls[0]


def test_live_tests_enabled_env_gate():
    import os as _os

    orig = _os.environ.pop(rl.LIVE_TEST_ENV, None)
    try:
        assert rl.live_tests_enabled() is False
        _os.environ[rl.LIVE_TEST_ENV] = "1"
        assert rl.live_tests_enabled() is True
        _os.environ[rl.LIVE_TEST_ENV] = "0"
        assert rl.live_tests_enabled() is False
    finally:
        if orig is None:
            _os.environ.pop(rl.LIVE_TEST_ENV, None)
        else:
            _os.environ[rl.LIVE_TEST_ENV] = orig


def test_repo_constant_drives_query():
    calls = []

    def _fake(query):
        calls.append(query)
        return {
            "data": {
                "repository": {
                    "pullRequest": {
                        "headRefOid": "abc123",
                        "reviewThreads": {
                            "pageInfo": {"hasNextPage": False},
                            "nodes": [],
                        },
                        "reviews": {"pageInfo": {"hasNextPage": False}, "nodes": []},
                    }
                }
            }
        }

    orig = rl._run_gh_graphql
    try:
        rl._run_gh_graphql = _fake
        rl._fetch_pr_threads(7)
    finally:
        rl._run_gh_graphql = orig

    owner, name = rl.REPO.split("/", 1)
    assert any(f'owner: "{owner}"' in c and f'name: "{name}"' in c for c in calls)


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


def test_stdout_json_is_ascii_safe():
    rendered = rl._json_for_stdout({"title": "📎 emoji"})
    assert rendered.isascii()
    assert json.loads(rendered)["title"] == "📎 emoji"


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
    if not rl.live_tests_enabled():
        print("SKIP: set HERMES_REVIEW_INTEGRATION=1 for the live PR-448 check")
        return
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
