#!/usr/bin/env python3
"""Hard gate: block merge until Qodo/CodeRabbit findings are resolved.

Usage:
    python tools/check_pr_review_clean.py <PR_NUMBER>
    python tools/check_pr_review_clean.py 423

Exit 0 only if there are zero unresolved review threads from bot reviewers
(coderabbitai, qodo-code-review) and no unaddressed CHANGES_REQUESTED from them.
CI green is NOT sufficient. "Skipping"/"pending" is treated as NOT clean.
"""

from __future__ import annotations

import json
import subprocess
import sys


BOT_LOGINS = {"coderabbitai", "qodo-code-review"}


def run(args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(args, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def main(argv: list[str]) -> int:
    if len(argv) == 1 and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if len(argv) != 1:
        print("usage: check_pr_review_clean.py <PR_NUMBER>", file=sys.stderr)
        return 2

    pr = argv[0]
    repo = run(["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"])
    if repo[0] != 0:
        print(f"FAIL: cannot determine repo: {repo[2]}", file=sys.stderr)
        return 2

    name_with_owner = repo[1].strip()
    owner, name = name_with_owner.split("/", 1)

    q = """query($owner:String!,$repo:String!,$pr:Int!){
      repository(owner:$owner,name:$repo){
        pullRequest(number:$pr){
          headRefOid
          reviews(first:100){
            nodes{state author{login} submittedAt commit{oid}}
          }
          reviewThreads(first:100){
            nodes{
              isResolved
              isOutdated
              comments(first:100){
                nodes{author{login} body}
              }
            }
          }
        }
      }
    }"""

    r = run([
        "gh", "api", "graphql",
        "-f", f"query={q}",
        "-F", f"owner={owner}",
        "-F", f"repo={name}",
        "-F", f"pr={int(pr)}",
    ])
    if r[0] != 0:
        print(f"FAIL: gh api graphql failed:\n{r[2]}", file=sys.stderr)
        return 2

    try:
        data = json.loads(r[1])
    except Exception as e:
        print(f"FAIL: cannot parse graphql response: {e}", file=sys.stderr)
        return 2

    pr_node = data.get("data", {}).get("repository", {}).get("pullRequest")
    if not pr_node:
        print("FAIL: pull request not found", file=sys.stderr)
        return 2

    head_sha = pr_node.get("headRefOid") or ""

    reviews = pr_node.get("reviews", {}).get("nodes", []) or []
    threads = pr_node.get("reviewThreads", {}).get("nodes", []) or []

    # Check for CHANGES_REQUESTED from bots not superseded by later APPROVED
    bot_reviews = []
    for rv in reviews:
        author = (rv.get("author") or {}).get("login") or ""
        if author in BOT_LOGINS:
            commit_sha = ((rv.get("commit") or {}).get("oid")) or ""
            bot_reviews.append((rv.get("submittedAt"), author, rv.get("state"), commit_sha))
    bot_reviews.sort(key=lambda x: x[0] or "")

    # If any bot has CHANGES_REQUESTED as latest state
    latest_by_bot = {}
    latest_commit_by_bot = {}
    for ts, author, state, csha in bot_reviews:
        latest_by_bot[author] = state
        latest_commit_by_bot[author] = csha
    for author, state in latest_by_bot.items():
        if state == "CHANGES_REQUESTED":
            print(f"BLOCK: {author} has CHANGES_REQUESTED and has not been superseded by APPROVED", file=sys.stderr)
            return 1
        if state == "DISMISSED":
            print(f"BLOCK: {author} review is DISMISSED and not a clean approval", file=sys.stderr)
            return 1
        if head_sha and latest_commit_by_bot.get(author) and latest_commit_by_bot[author] != head_sha:
            print(f"BLOCK: {author} review is on different commit (stale). Push new head and wait for re-review.", file=sys.stderr)
            return 1

    # Check unresolved threads from bots
    unresolved = []
    for t in threads:
        if t.get("isResolved"):
            continue
        # Don't skip outdated - check if bot commented (issue 9)
        comments = (t.get("comments") or {}).get("nodes") or []
        if not comments:
            continue
        # Check any comment in thread by bot
        thread_has_bot = False
        for c in comments:
            first_author = (c.get("author") or {}).get("login") or ""
            if first_author in BOT_LOGINS:
                thread_has_bot = True
                break
        if thread_has_bot:
            unresolved.append(t)

    if unresolved:
        print(f"BLOCK: {len(unresolved)} unresolved review thread(s) from bot reviewers (coderabbitai/qodo-code-review)", file=sys.stderr)
        print("Action: address each thread or get bot acceptance. Do NOT merge. Do NOT resolve manually.", file=sys.stderr)
        return 1

    # Require both bots to have reviewed the current head in proper order
    if "qodo-code-review" not in latest_by_bot:
        print("BLOCK: waiting for qodo-code-review to review current head first", file=sys.stderr)
        print("Action: Qodo reviews first per workflow. CodeRabbit triggers after Qodo is clean.", file=sys.stderr)
        return 1
    if latest_commit_by_bot.get("qodo-code-review") != head_sha:
        print("BLOCK: qodo-code-review review is not on current head commit. Wait for re-review.", file=sys.stderr)
        return 1
    # Check if Qodo has CHANGES_REQUESTED
    if latest_by_bot.get("qodo-code-review") == "CHANGES_REQUESTED":
        print("BLOCK: qodo-code-review has CHANGES_REQUESTED. Resolve before CodeRabbit/full review.", file=sys.stderr)
        return 1
    # Only require CodeRabbit if Qodo is clean/commented without blocking
    if "coderabbitai" not in latest_by_bot:
        print("BLOCK: waiting for coderabbitai to review after qodo-code-review", file=sys.stderr)
        print("Action: CodeRabbit triggers after Qodo is clean. Wait for full review.", file=sys.stderr)
        return 1
    if latest_commit_by_bot.get("coderabbitai") != head_sha:
        print("BLOCK: coderabbitai review is not on current head commit. Wait for re-review.", file=sys.stderr)
        return 1
    if latest_by_bot.get("coderabbitai") == "CHANGES_REQUESTED":
        print("BLOCK: coderabbitai has CHANGES_REQUESTED. Resolve findings.", file=sys.stderr)
        return 1

    print("OK: no unresolved bot findings (qodo-code-review + coderabbitai) on current head. Safe to merge only if other gates pass.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
