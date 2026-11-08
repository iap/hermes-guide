#!/usr/bin/env python3
"""Review Round Ledger - track per-PR review findings and resolution status.

Fetches review threads from GitHub via GraphQL and writes a structured ledger
JSON file that records which findings were raised by which bot, their severity,
resolution status, and whether the PR is merge-ready.

Usage:
    python tools/review_ledger.py --pr 448 --write
    python tools/review_ledger.py --pr 448 --json

Dependencies:
    - gh CLI (must be on PATH): https://cli.github.com/
    - Python 3.11+

Cross-platform: uses pathlib.Path and subprocess with list args. No shell=True.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = "iap/hermes-guide"
LEDGER_DIR = Path(".hermes")
LEDGER_FILE = "review-rounds.json"

BOT_PATTERNS = {
    "qodo": "qodo-code-review",
    "coderabbit": "coderabbit",
}


def _run_gh_graphql(query):
    result = subprocess.run(
        ["gh", "api", "graphql", "-f", "query=" + query],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("gh GraphQL failed: " + result.stderr.strip())
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"gh returned invalid JSON: {exc}") from exc


def _fetch_pr_threads(pr_number):
    query = f"""query {{ repository(owner: "iap", name: "hermes-guide") {{ pullRequest(number: {pr_number}) {{ headRefOid reviewThreads(first: 100) {{ nodes {{ id isResolved comments(first: 5) {{ nodes {{ author {{ login }} body path line createdAt }} }} }} }} }} }} }}"""
    data = _run_gh_graphql(query)
    pr = data["data"]["repository"]["pullRequest"]
    threads = pr["reviewThreads"]["nodes"]
    head_oid = pr["headRefOid"]
    return threads, head_oid


def _classify_bot(author_login):
    login_lower = author_login.lower()
    for bot_key, pattern in BOT_PATTERNS.items():
        if pattern in login_lower:
            return bot_key
    return None


def _extract_severity(body):
    body_lower = body.lower()
    first_line = body_lower.split(chr(10))[0] if body_lower else ""
    # Qodo uses emoji markers: red=high, orange=medium, yellow=low, green=minor
    if "🔴" in first_line or "red" in first_line:
        return "high"
    if "🟠" in first_line or "orange" in first_line:
        return "medium"
    if "🟡" in first_line or "yellow" in first_line:
        return "low"
    if "🟢" in first_line or "green" in first_line:
        return "minor"
    # Text-based fallback
    if "high" in first_line:
        return "high"
    if "medium" in first_line:
        return "medium"
    if "low" in first_line:
        return "low"
    if "trivial" in body_lower or "minor" in body_lower:
        return "minor"
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
    human_open_count = 0
    for thread in threads:
        comments = thread.get("comments", {}).get("nodes", [])
        if not comments:
            continue
        first = comments[0]
        author = first.get("author", {}).get("login", "")
        bot = _classify_bot(author)
        is_resolved = thread.get("isResolved", False)
        if bot is None:
            if not is_resolved:
                human_open_count += 1
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
            "status": "resolved" if is_resolved else "open",
            "resolved_commit": None,
            "created_at": first.get("createdAt"),
        }
        findings.append(finding)
    return findings, human_open_count


def unresolved_findings(findings):
    return [f for f in findings if f["status"] == "open"]


def build_ledger(pr_number, head_oid, findings):
    qodo_findings = [f for f in findings if f["bot"] == "qodo"]
    cr_findings = [f for f in findings if f["bot"] == "coderabbit"]

    qodo_open = [f for f in qodo_findings if f["status"] == "open"]
    cr_open = [f for f in cr_findings if f["status"] == "open"]

    qodo_clean = len(qodo_findings) > 0 and len(qodo_open) == 0
    coderabbit_clean = len(cr_findings) > 0 and len(cr_open) == 0

    if len(qodo_findings) == 0:
        qodo_clean = False
    if len(cr_findings) == 0:
        coderabbit_clean = False

    same_head = True
    merge_ready = (
        qodo_clean
        and coderabbit_clean
        and same_head
        and len(unresolved_findings(findings)) == 0
    )

    round_data = {
        "round": 1,
        "timestamp": datetime.now(UTC).isoformat(),
        "head_commit": head_oid,
        "findings": findings,
        "qodo_clean": qodo_clean,
        "coderabbit_clean": coderabbit_clean,
        "same_head": same_head,
        "merge_ready": merge_ready,
        "summary": {
            "total_findings": len(findings),
            "qodo_total": len(qodo_findings),
            "qodo_open": len(qodo_open),
            "coderabbit_total": len(cr_findings),
            "coderabbit_open": len(cr_open),
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
        threads, head_oid = _fetch_pr_threads(args.pr)
    except (RuntimeError, KeyError, TypeError, ValueError) as exc:
        print("error: " + str(exc), file=sys.stderr)
        return 2

    findings, human_open_count = _parse_threads(threads)
    ledger = build_ledger(args.pr, head_oid, findings, human_open_count)

    if args.write:
        if args.output:
            out_path = Path(args.output)
        else:
            out_path = LEDGER_DIR / LEDGER_FILE
        write_ledger(ledger, out_path)
        print("Ledger written to " + str(out_path))

    if args.json or not args.write:
        print(json.dumps(ledger, indent=2, ensure_ascii=False))

    if ledger["merge_ready"]:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
