#!/usr/bin/env python3
"""Regression coverage for the hardened check_upstream_drift.py.

The weekly drift watch was hardened to (a) scan upstream git history at
commit granularity, (b) use exact-title dedup so a substring-matching issue
cannot suppress a real alert, (c) fail the run on transport failures, and
(d) block filing when the CI-pin freshness check cannot run. Each case below
pins one of those behaviors.

No network, no `gh` CLI, no upstream clone: git/gh are monkeypatched.

Run: python3 tools/test_upstream_drift_hygiene.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent


def _load_module():
    """Import the drift script as a module.

    The script does `sys.path.insert(0, REPO_ROOT); import constants`, so we need
    constants.py and checks.py importable from the same dir as the script.
    """
    import importlib
    td = Path(tempfile.mkdtemp())
    # Copy the three plugin sources to the temp root (so `import constants` works)
    for name in ("__init__.py", "checks.py", "constants.py"):
        shutil.copy(REPO / name, td / name)
    # Copy the drift script itself
    shutil.copy(REPO / "tools" / "check_upstream_drift.py",
                td / "check_upstream_drift.py")
    sys.path.insert(0, str(td))
    mod = importlib.import_module("check_upstream_drift")
    return mod


def case_upstream_drift_filed(mod):
    """Upstream drift files a single upstream-titled issue, not two."""
    calls = []

    def fake_file_issue(repo, title, body, label):
        assert label == "drift"
        calls.append((repo, title, body, label))
        return 1

    def fake_list_open_issues(repo, title):
        return []

    def fake_clone():
        return "/tmp/fake-upstream"

    def fake_git(repo_dir, *args):
        if args[:2] == ("rev-parse", "HEAD"):
            return "abc1234567890def", "", 0
        if "--format" in args:
            return "abc1234\x1f2026-09-11 06:37:27 -0700\x1ffix(mcp): rename mcp_servers key", "", 0
        return "", "", 0

    def fake_git_log(repo_dir, ref_range, watched=None):
        return [{"sha": "abc1234", "date": "2026-09-11", "subject": "fix(mcp): rename", "files": ["hermes_cli/config.py"]}]

    def fake_verify_facts(repo_dir, head):
        return ["MCP config key: upstream now `mcp`, hermes-guide asserts `mcp_servers`"]

    def fake_verify_ci_pin():
        return [], None

    with mock.patch.object(mod, "clone_upstream", fake_clone), \
         mock.patch.object(mod, "git", fake_git), \
         mock.patch.object(mod, "git_log", fake_git_log), \
         mock.patch.object(mod, "verify_facts", fake_verify_facts), \
         mock.patch.object(mod, "verify_ci_pin", fake_verify_ci_pin), \
         mock.patch.object(mod, "_file_issue", fake_file_issue), \
         mock.patch.object(mod, "_list_open_issues", fake_list_open_issues), \
         mock.patch.dict("os.environ", {"GITHUB_REPOSITORY": "iap/hermes-guide"}):
        rc = mod.main()

    assert rc == 0, f"main returned {rc}, expected 0"
    titles = [c[1] for c in calls]
    assert mod.ISSUE_TITLE_UPSTREAM in titles, f"upstream title not filed: {titles}"
    assert len(calls) == 1, f"expected 1 issue, got {len(calls)}: {titles}"
    body = calls[0][2]
    assert "abc1234" in body
    assert "fix(mcp): rename" in body
    assert "hermes_cli/config.py" in body
    print("OK: upstream drift files one issue with commit and file context")


def case_exact_title_dedup(mod):
    """_list_open_issues matches exact title only — substring does not dedup."""
    # Fake gh CLI returning two issues, one with a substring-matching title.
    fake_api_response = json.dumps([
        {"number": 1, "title": "Upstream schema drift"},  # substring, not exact
        {"number": 2, "title": mod.ISSUE_TITLE_UPSTREAM},  # exact match
    ])
    with mock.patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            "gh", returncode=0, stdout=fake_api_response, stderr="")
        result = mod._list_open_issues("iap/hermes-guide", mod.ISSUE_TITLE_UPSTREAM)
    # Only the exact match should survive.
    assert len(result) == 1, f"expected 1 exact match, got {len(result)}: {result}"
    assert result[0]["title"] == mod.ISSUE_TITLE_UPSTREAM
    print("OK: exact-title dedup only (substring does not suppress)")


def case_transport_failure_fails_run(mod):
    """A broken gh call must raise, not silently skip and report success."""
    with mock.patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            "gh", returncode=1, stdout="", stderr="network down")
        try:
            mod._list_open_issues("iap/hermes-guide", mod.ISSUE_TITLE_UPSTREAM)
            assert False, "_list_open_issues should have raised"
        except RuntimeError as exc:
            assert "gh issue list failed" in str(exc)
    print("OK: transport failure raises, does not silently skip")


def case_file_issue_skips_when_open(mod):
    """_file_issue returns 0 (no create) when an exact-title issue is already open."""
    calls = []

    def fake_create(repo, title, body, label):
        calls.append((repo, title, body, label))
        return 1

    with mock.patch.object(
        mod, "_list_open_issues",
        return_value=[{"number": 7, "title": mod.ISSUE_TITLE_UPSTREAM}],
    ), \
         mock.patch.object(mod, "_file_issue", side_effect=mod._file_issue) as patched, \
         mock.patch.object(subprocess, "run") as mock_run:
        rc = patched("iap/hermes-guide", mod.ISSUE_TITLE_UPSTREAM, "body", "drift")
    assert rc == 0
    assert calls == []
    # gh issue create must never be called when the issue is already open.
    assert mock_run.call_count == 0
    print("OK: _file_issue skips filing when an exact-title issue is open")


def case_git_log_parsing_robust(mod):
    """git_log preserves watched files and deduplicates merge records."""
    fake_output = (
        "abc1234\x1f2026-09-11 06:37:27 -0700\x1ffix(mcp): rename\n"
        "hermes_constants.py\n"
        "abc1234\x1f2026-09-11 06:37:27 -0700\x1ffix(mcp): rename\n"
        "tools/memory_tool_store.py\n"
        "def5678\x1f2026-09-10\x1ffix(skill): tweak"
    )
    with mock.patch.object(subprocess, "run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            "git", returncode=0, stdout=fake_output, stderr="")
        records = mod.git_log("/tmp/fake", "HEAD~3..HEAD")
    assert len(records) == 2, f"expected 2 records, got {len(records)}: {records}"
    assert records[0]["sha"] == "abc1234"
    assert records[0]["files"] == [
        "hermes_constants.py", "tools/memory_tool_store.py"
    ]
    assert records[1]["sha"] == "def5678"
    command = mock_run.call_args.args[0]
    assert "--diff-merges=separate" in command
    print("OK: git_log preserves and deduplicates merge file context")


def case_pin_failure_fails_closed(mod):
    """A pin-check transport failure blocks issue filing, even with drift."""
    issue_calls = []

    def fake_git(repo_dir, *args):
        if args[:2] == ("rev-parse", "HEAD"):
            return "abc1234567890def", "", 0
        if args[:2] == ("log", "--format=%h %ci %s"):
            return "abc1234 2026-09-11 fix(mcp): rename", "", 0
        return "", "", 0

    def fake_file_issue(repo, title, body, label):
        issue_calls.append((repo, title, body, label))
        return 1

    with mock.patch.object(mod, "clone_upstream", return_value="/tmp/fake-upstream"), \
         mock.patch.object(mod, "git", fake_git), \
         mock.patch.object(mod, "verify_facts", return_value=[]), \
         mock.patch.object(
             mod, "verify_ci_pin",
             return_value=([], "could not list upstream tags")), \
         mock.patch.object(
             mod, "scan_upstream_history",
             return_value=([{"sha": "abc1234", "date": "2026-09-11",
                             "subject": "fix(mcp): rename", "files": []}], [])), \
         mock.patch.object(mod, "_file_issue", fake_file_issue), \
         mock.patch.dict("os.environ", {"GITHUB_REPOSITORY": "iap/hermes-guide"}):
        rc = mod.main()

    assert rc == 1
    assert issue_calls == []
    print("OK: pin-check failure blocks issue filing")


def main() -> int:
    mod = _load_module()
    failures: list[str] = []
    for case in (
        case_upstream_drift_filed,
        case_exact_title_dedup,
        case_transport_failure_fails_run,
        case_file_issue_skips_when_open,
        case_git_log_parsing_robust,
        case_pin_failure_fails_closed,
    ):
        try:
            case(mod)
        except Exception as exc:
            failures.append(f"{case.__name__}: {exc}")
            print(f"FAIL: {case.__name__}: {exc}")
    if failures:
        print(f"\n{len(failures)} failure(s)")
        return 1
    print("\nOK: 6 upstream-drift hygiene case(s) passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
