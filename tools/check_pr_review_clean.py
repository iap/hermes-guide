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
          reviews(first:100){
            nodes{state author{login} submittedAt}
          }
          reviewThreads(first:250){
            nodes{
              isResolved
              isOutdated
              comments(first:5){
                nodes{author{login}}
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

    reviews = pr_node.get("reviews", {}).get("nodes", []) or []
    threads = pr_node.get("reviewThreads", {}).get("nodes", []) or []

    # Check for CHANGES_REQUESTED from bots not superseded by later APPROVED
    bot_reviews = []
    for rv in reviews:
        author = (rv.get("author") or {}).get("login") or ""
        if author in BOT_LOGINS:
            bot_reviews.append((rv.get("submittedAt"), author, rv.get("state")))
    bot_reviews.sort(key=lambda x: x[0] or "")

    # If any bot has CHANGES_REQUESTED as latest state
    latest_by_bot = {}
    for ts, author, state in bot_reviews:
        latest_by_bot[author] = state
    for author, state in latest_by_bot.items():
        if state == "CHANGES_REQUESTED":
            print(f"BLOCK: {author} has CHANGES_REQUESTED and has not been superseded by APPROVED", file=sys.stderr)
            return 1

    # Check unresolved threads from bots
    unresolved = []
    for t in threads:
        if t.get("isResolved"):
            continue
        comments = (t.get("comments") or {}).get("nodes") or []
        if not comments:
            continue
        first_author = (comments[0].get("author") or {}).get("login") or ""
        if first_author in BOT_LOGINS:
            unresolved.append(t)

    if unresolved:
        print(f"BLOCK: {len(unresolved)} unresolved review thread(s) from bot reviewers (coderabbitai/qodo-code-review)", file=sys.stderr)
        print("Action: address each thread or get bot acceptance. Do NOT merge. Do NOT resolve manually.", file=sys.stderr)
        return 1

    # If bots never reviewed
    if not bot_reviews:
        print("BLOCK: no reviews found from coderabbitai or qodo-code-review yet", file=sys.stderr)
        print("Action: wait for bot reviews to complete. 'skipping'/pending is NOT clean.", file=sys.stderr)
        return 1

    print("OK: no unresolved bot findings (coderabbitai/qodo-code-review). Safe to merge only if other gates pass.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
