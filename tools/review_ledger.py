#!/usr/bin/env python3
"""Review Round Ledger - track per-PR review findings and resolution status.

Fetches review threads from GitHub via GraphQL and writes a structured ledger
JSON file that records which findings were raised by which bot, their severity,
resolution status, and whether the PR is merge-ready.

Usage:
    python tools/review_ledger.py --pr 448 --write
    python tools/review_ledger.py --pr 448 --json

Live smoke tests (network + gh):
    HERMES_GUIDE_LIVE_TESTS=1 python tools/test_review_ledger.py

Dependencies:
    - gh CLI (must be on PATH): https://cli.github.com/
    - Python 3.11+

Cross-platform: uses pathlib.Path and subprocess with list args. No shell=True.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = os.environ.get("GITHUB_REPOSITORY", "iap/hermes-guide")
LIVE_TEST_ENV = "HERMES_REVIEW_INTEGRATION"
LEDGER_DIR = Path(".hermes")
LEDGER_FILE = "review-rounds.json"

BOT_LOGINS = {
    "qodo": {"qodo-code-review", "qodo-code-review[bot]"},
    "coderabbit": {"coderabbitai", "coderabbitai[bot]", "coderabbit"},
}


def live_tests_enabled():
    """Live (network/gh) tests are opt-in so the default suite stays hermetic."""
    return os.environ.get(LIVE_TEST_ENV, "").strip().lower() in {"1", "true", "yes"}


def _run_gh_graphql(query):
    try:
        result = subprocess.run(
            ["gh", "api", "graphql", "-f", "query=" + query],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"gh GraphQL timed out after {exc.timeout}s") from exc
    except OSError as exc:
        raise RuntimeError(f"gh CLI unavailable: {exc}") from exc
    if result.returncode != 0:
        raise RuntimeError("gh GraphQL failed: " + result.stderr.strip())
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"gh returned invalid JSON: {exc}") from exc


def _fetch_reviews(pr_number):
    reviews = []
    after = ""
    owner, name = REPO.split("/", 1)
    for _ in range(50):
        after_arg = f', after: "{after}"' if after else ""
        query = (
            f'query {{ repository(owner: "{owner}", name: "{name}") {{ '
            f"pullRequest(number: {pr_number}) {{ "
            f"reviews(first: 100{after_arg}) {{ "
            f"pageInfo {{ hasNextPage endCursor }} "
            f"nodes {{ author {{ login }} state submittedAt commit {{ oid }} }} "
            f"}} }} }} }}"
        )
        data = _run_gh_graphql(query)
        pr = data["data"]["repository"]["pullRequest"]
        reviews.extend(pr["reviews"]["nodes"])
        page = pr["reviews"].get("pageInfo") or {}
        if not page.get("hasNextPage"):
            break
        after = page.get("endCursor") or ""
        if not after:
            break
    return reviews


def _fetch_pr_threads(pr_number):
    threads = []
    head_oid = None
    after = ""
    owner, name = REPO.split("/", 1)
    # Qodo #19: first:100 truncates long histories and false-cleans PRs
    # whose unresolved threads live past page one. Page threads until
    # exhausted.
    # Qodo #20: no fixed page cap (PRs can exceed 500 threads).
    for _ in range(20):
        after_arg = f', after: "{after}"' if after else ""
        query = (
            f'query {{ repository(owner: "{owner}", name: "{name}") {{ '
            f"pullRequest(number: {pr_number}) {{ headRefOid "
            f"reviewThreads(first: 100{after_arg}) {{ "
            f"pageInfo {{ hasNextPage endCursor }} "
            f"nodes {{ id isResolved isOutdated comments(first: 5) {{ "
            f"nodes {{ author {{ login }} body path line createdAt }} }} }} "
            f"}} }} }} }}"
        )
        data = _run_gh_graphql(query)
        pr = data["data"]["repository"]["pullRequest"]
        head_oid = pr["headRefOid"]
        threads.extend(pr["reviewThreads"]["nodes"])
        t_page = pr["reviewThreads"].get("pageInfo") or {}
        if not t_page.get("hasNextPage"):
            break
        after = t_page.get("endCursor") or ""
        if not after:
            break
    reviews = _fetch_reviews(pr_number)
    return threads, head_oid, reviews


def compute_reviewed(reviews, head_oid=None):
    """Whether Qodo / CodeRabbit completed a review (independent of findings).

    Qodo #12: a bot that reviews with zero inline findings must count as
    reviewed, so its clean state is not conflated with a bot that has
    not reviewed at all.
    """
    def _login(r):
        return ((r.get("author") or {}).get("login") or "").lower()

    def _reviewed(bot):
        logins = BOT_LOGINS[bot]
        # Qodo #18: a later CHANGES_REQUESTED overrides an earlier review.
        # Qodo #5: a review for an older head does not clear a new commit.
        # Qodo #21: PENDING/DISMISSED are not a completed review; any
        # CHANGES_REQUESTED on the head blocks even if earlier COMMENTED exists.
        saw_request = False
        saw_ok = False
        ordered = sorted(reviews, key=lambda r: r.get("submittedAt") or "")
        for r in ordered:
            if _login(r) not in logins:
                continue
            if head_oid:
                commit = (r.get("commit") or {}).get("oid")
                if commit and commit != head_oid:
                    continue
            state = r.get("state")
            if state in ("PENDING", "DISMISSED"):
                # Unsubmitted/dismissed reviews never count as reviewed.
                continue
            if state == "CHANGES_REQUESTED":
                saw_request = True
                saw_ok = False
            elif state == "APPROVED":
                saw_request = False
                saw_ok = True
            elif state in (None, "COMMENTED"):
                # Bare comment never clears an outstanding request.
                if not saw_request:
                    saw_ok = True
        return saw_ok and not saw_request

    return _reviewed("qodo"), _reviewed("coderabbit")


def _classify_bot(author_login):
    # Exact match only (Qodo #3): substring matching let lookalike users
    # (e.g. "notcoderabbit") count as review bots.
    login_lower = (author_login or "").lower()
    for bot_key, logins in BOT_LOGINS.items():
        if login_lower in logins:
            return bot_key
    return None


def _extract_severity(body):
    # Look only at the header region: severity words elsewhere in the body
    # are prose, not the finding's severity.
    header = "\n".join((body or "").splitlines()[:6]).lower()
    # Qodo uses emoji markers: red=high, orange=medium, yellow=low, green=minor
    if "🔴" in header:
        return "high"
    if "🟠" in header:
        return "medium"
    if "🟡" in header:
        return "low"
    if "🟢" in header:
        return "minor"
    # CodeRabbit puts the severity first (e.g. **Minor** ... **Low value**),
    # so prefer the severity word over the separate value label.
    if re.search(r"\b(critical|high|major)\b", header):
        return "high"
    if re.search(r"\bmedium\b", header):
        return "medium"
    if re.search(r"\b(minor|trivial)\b", header):
        return "minor"
    if re.search(r"\blow\b", header):
        return "low"
    return "unknown"


def _extract_title(body):
    # Qodo/CodeRabbit comments often start with a severity marker like
    # "U+1F534 **High**" -- skip those and find the actual finding title.
    severity_words = {"high", "medium", "low", "minor", "trivial"}
    for match in re.finditer(r"\*\*(.+?)\*\*", body):
        title = match.group(1).strip()
        title = re.sub(r"[🔴🟠🟡🟢⚪]", "", title).strip()
        if title and title.lower() not in severity_words:
            return title[:120]
    # Fall back to first non-empty, non-HTML-comment line that isn't just a severity
    for line in body.splitlines():
        line = line.strip()
        if line and not line.startswith("<!--"):
            # Skip lines that are just severity markers
            cleaned = re.sub(r"[🔴🟠🟡🟢⚪]", "", line).strip().strip("*").strip()
            if cleaned.lower() not in severity_words and cleaned:
                return line[:120]
    return "untitled"


def _parse_threads(threads):
    findings = []
    non_review_open = 0
    for thread in threads:
        comments = (thread.get("comments") or {}).get("nodes") or []
        if not comments:
            continue
        first = comments[0]
        author = (first.get("author") or {}).get("login", "")
        bot = _classify_bot(author)
        is_resolved = thread.get("isResolved", False)
        is_outdated = bool(thread.get("isOutdated", False))
        if bot is None:
            if not is_resolved and not is_outdated:
                non_review_open += 1
            continue
        body = first.get("body", "")
        finding = {
            "id": thread["id"],
            "thread_id": thread["id"],
            "bot": bot,
            "severity": _extract_severity(body),
            "title": _extract_title(body),
            "file": first.get("path"),
            "line": first.get("line"),
            "status": (
                "resolved" if is_resolved else ("outdated" if is_outdated else "open")
            ),
            "resolved_commit": None,
            "created_at": first.get("createdAt"),
        }
        findings.append(finding)
    return findings, non_review_open


def unresolved_findings(findings):
    return [f for f in findings if f["status"] == "open"]


def build_ledger(pr_number, head_oid, findings, qodo_reviewed=False, coderabbit_reviewed=False, non_review_open=0):
    qodo_findings = [f for f in findings if f["bot"] == "qodo"]
    cr_findings = [f for f in findings if f["bot"] == "coderabbit"]

    qodo_open = [f for f in qodo_findings if f["status"] == "open"]
    cr_open = [f for f in cr_findings if f["status"] == "open"]

    qodo_clean = qodo_reviewed and len(qodo_open) == 0
    coderabbit_clean = coderabbit_reviewed and len(cr_open) == 0

    # Both flags are already head-scoped by compute_reviewed(); deriving this
    # from them keeps the field honest when a bot reviewed an older commit.
    same_head = bool(qodo_reviewed and coderabbit_reviewed)
    merge_ready = (
        qodo_clean
        and coderabbit_clean
        and same_head
        and len(unresolved_findings(findings)) == 0
        and non_review_open == 0
    )

    round_data = {
        "round": 1,
        "timestamp": datetime.now(UTC).isoformat(),
        "head_commit": head_oid,
        "findings": findings,
        "qodo_clean": qodo_clean,
        "coderabbit_clean": coderabbit_clean,
        "qodo_reviewed": qodo_reviewed,
        "coderabbit_reviewed": coderabbit_reviewed,
        "same_head": same_head,
        "merge_ready": merge_ready,
        "summary": {
            "total_findings": len(findings),
            "qodo_total": len(qodo_findings),
            "qodo_open": len(qodo_open),
            "coderabbit_total": len(cr_findings),
            "coderabbit_open": len(cr_open),
            "non_review_open": non_review_open,
        },
    }

    return {
        "pr": pr_number,
        "head_commit": head_oid,
        "rounds": [round_data],
        "merge_ready": merge_ready,
    }


def write_ledger(ledger, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _json_for_stdout(ledger):
    """ASCII-only JSON so consoles with a non-UTF-8 code page do not crash."""
    return json.dumps(ledger, indent=2, ensure_ascii=True)


def main():
    parser = argparse.ArgumentParser(
        description="Review Round Ledger - track per-PR review findings"
    )
    parser.add_argument("--pr", type=int, required=True, help="PR number")
    parser.add_argument("--write", action="store_true", help="Write ledger to disk")
    parser.add_argument(
        "--json", action="store_true", help="Print ledger JSON to stdout"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file path (default: .hermes/review-rounds.json)",
    )
    args = parser.parse_args()

    try:
        threads, head_oid, reviews = _fetch_pr_threads(args.pr)
    except (RuntimeError, KeyError, TypeError, ValueError) as exc:
        print("error: " + str(exc), file=sys.stderr)
        return 2

    findings, non_review_open = _parse_threads(threads)
    qodo_reviewed, coderabbit_reviewed = compute_reviewed(reviews, head_oid)
    ledger = build_ledger(args.pr, head_oid, findings, qodo_reviewed, coderabbit_reviewed, non_review_open)

    if args.write:
        if args.output:
            out_path = Path(args.output)
        else:
            out_path = LEDGER_DIR / LEDGER_FILE
        write_ledger(ledger, out_path)
        if not args.json:
            print("Ledger written to " + str(out_path))

    if args.json or not args.write:
        print(_json_for_stdout(ledger))

    if ledger["merge_ready"]:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
