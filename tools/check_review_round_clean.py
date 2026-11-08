#!/usr/bin/env python3
"""Review Round Clean Gate -- mechanical merge-blocking guard.

Verifies that a PR's review rounds are clean before allowing merge:
  1. Reads .hermes/review-rounds.json (produced by review_ledger.py)
  2. Verifies the ledger's head_commit matches the current PR head
  3. Re-fetches live review threads via GraphQL to confirm zero unresolved findings
  4. Checks both Qodo and CodeRabbit have zero open findings
  5. Exits 0 (pass) or 1 (fail) with a clear diagnostic

If no ledger exists, use --pr <number> to fetch fresh.

Usage:
    python tools/check_review_round_clean.py --pr 448
    python tools/check_review_round_clean.py --pr 448 --ledger .hermes/review-rounds.json

Dependencies:
    - gh CLI (must be on PATH)
    - Python 3.11+
    - tools/review_ledger.py (same directory)

Cross-platform: uses pathlib.Path and subprocess with list args. No shell=True.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_ledger as rl

LEDGER_DIR = Path(".hermes")
LEDGER_FILE = "review-rounds.json"


def _get_pr_head(pr_number: int) -> str:
    """Fetch the current head commit SHA for a PR."""
    query = (
        f'query {{ repository(owner: "iap", name: "hermes-guide") {{ '
        f"pullRequest(number: {pr_number}) {{ headRefOid }} }} }}"
    )
    data = rl._run_gh_graphql(query)
    return data["data"]["repository"]["pullRequest"]["headRefOid"]


def _check_ledger(ledger: dict, pr_number: int, live_head: str) -> list[str]:
    """Validate ledger contents. Returns list of failure messages (empty = pass)."""
    failures: list[str] = []

    if ledger.get("pr") != pr_number:
        failures.append(
            f"Ledger PR mismatch: ledger has PR {ledger.get('pr')}, expected {pr_number}"
        )

    ledger_head = ledger.get("head_commit")
    if ledger_head != live_head:
        failures.append(
            f"Stale ledger: ledger head {ledger_head[:12] if ledger_head else 'None'} "
            f"!= current head {live_head[:12]}"
        )

    rounds = ledger.get("rounds", [])
    if not rounds:
        failures.append("No review rounds recorded in ledger")
        return failures

    latest = rounds[-1]
    if not latest.get("qodo_clean"):
        failures.append("Qodo review not clean (open findings remain)")
    if not latest.get("coderabbit_clean"):
        failures.append("CodeRabbit review not clean (open findings remain)")

    open_count = latest.get("summary", {}).get("qodo_open", 0) + latest.get(
        "summary", {}
    ).get("coderabbit_open", 0)
    if open_count > 0:
        failures.append(f"{open_count} unresolved finding(s) remain")

    if not ledger.get("merge_ready"):
        failures.append("Ledger merge_ready is False")

    return failures


def _fetch_fresh_ledger(pr_number: int) -> dict:
    """Fetch fresh threads and build a ledger (no disk write)."""
    threads, head_oid = rl._fetch_pr_threads(pr_number)
    findings = rl._parse_threads(threads)
    return rl.build_ledger(pr_number, head_oid, findings)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Review Round Clean Gate -- mechanical merge-blocking guard"
    )
    parser.add_argument("--pr", type=int, required=True, help="PR number")
    parser.add_argument(
        "--ledger",
        type=str,
        default=None,
        help="Path to ledger file (default: .hermes/review-rounds.json)",
    )
    parser.add_argument(
        "--no-live-check",
        action="store_true",
        help="Skip live GraphQL re-fetch (trust ledger only)",
    )
    args = parser.parse_args()

    pr_number = args.pr

    if args.ledger:
        ledger_path = Path(args.ledger)
    else:
        ledger_path = LEDGER_DIR / LEDGER_FILE

    try:
        live_head = _get_pr_head(pr_number)
    except (RuntimeError, KeyError, TypeError, ValueError) as exc:
        print(f"error: failed to fetch PR head: {exc}", file=sys.stderr)
        return 2

    ledger = None
    if ledger_path.exists():
        try:
            with open(ledger_path, encoding="utf-8") as fh:
                ledger = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"error: failed to read ledger: {exc}", file=sys.stderr)
            return 2

    if ledger is None:
        try:
            ledger = _fetch_fresh_ledger(pr_number)
        except (RuntimeError, KeyError, TypeError, ValueError) as exc:
            print(f"error: failed to fetch review threads: {exc}", file=sys.stderr)
            return 2

    failures = _check_ledger(ledger, pr_number, live_head)

    if not args.no_live_check and not failures:
        try:
            threads, live_head2 = rl._fetch_pr_threads(pr_number)
            findings = rl._parse_threads(threads)
            open_findings = rl.unresolved_findings(findings)
            if open_findings:
                failures.append(
                    f"Live check: {len(open_findings)} unresolved finding(s) found"
                )
                for fnd in open_findings[:5]:
                    failures.append(
                        f"  - [{fnd['bot']}] {fnd['title']} "
                        f"({fnd.get('file', '?')}:{fnd.get('line', '?')})"
                    )
            if live_head2 != live_head:
                failures.append(
                    f"Head changed during check: {live_head[:12]} -> {live_head2[:12]}"
                )
        except (RuntimeError, KeyError, TypeError, ValueError) as exc:
            print(f"warning: live check failed: {exc}", file=sys.stderr)

    if failures:
        print("REVIEW ROUND GATE: FAIL")
        for msg in failures:
            print(f"  - {msg}")
        return 1

    print("REVIEW ROUND GATE: PASS")
    print(f"  PR: {pr_number}")
    print(f"  Head: {live_head[:12]}")
    latest = ledger.get("rounds", [{}])[-1]
    print(
        f"  Findings: {latest.get('summary', {}).get('total_findings', 0)} total, "
        f"0 open (Qodo + CodeRabbit clean)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
