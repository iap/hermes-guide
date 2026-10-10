#!/usr/bin/env python3
"""Run the repo's hermetic gate suite — the fast tier CI already enforces.

Every gate below is a pure function of the working tree: no network, no ``git``
merge-base, no ``hermes`` CLI. That is what makes them safe on every commit,
which is the point — the five things that break when you add or edit a
``SKILL.md`` (documented counts, the install loop, the configuration map's
routing table, the provenance footer, the self-claim deny-list) are all
mechanical, and all of them are what CI rejects a PR for. This moves them from
"discovered in CI" to "refused locally".

Scope note: a convenience *runner*, not a new gate. It contains no checking
logic — every verdict comes from the neighbor script it invokes. Rename or drop
a gate here and CI still runs it; the only loss is the pre-commit fast path.

Usage:
    python tools/check_gates.py            # hermetic tier
    python tools/check_gates.py --quick    # counts + provenance only
    python tools/check_gates.py --list     # the tiering, and what CI keeps
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# script -> why it is safe to run on every commit.
_GATES: dict[str, str] = {
    "test_skill_counts.py": "pure file reads plus `git ls-files`; no network or Hermes",
    "render_docs.py": "regenerates doc blocks and diffs them; pure file reads",
    "check_skill_provenance.py": "regex over SKILL.md text",
    "check_self_claim.py": "deny-list scan over docs",
    "check_doc_style.py": "tone scan; `git ls-files` plus a tokenizer pass",
    "check_version_consistency.py": "compares manifest/entrypoint literals",
    "check_issue_templates.py": "reads .github/ISSUE_TEMPLATE/ and the docs beside it",
    "check_no_mutation.py": "AST parse; no imports executed",
    "check_scanner_hygiene.py": "regex over skills text; mirrors upstream guard patterns",
}

_QUICK = ("test_skill_counts.py", "render_docs.py", "check_skill_provenance.py")

_USAGE = (
    "run the hermetic gate tier (generated docs, counts, routing, provenance, "
    "self-claim, tone, read-only)"
)

# Gates CI runs that this tier leaves out, and the constraint that excludes it.
_SLOW: dict[str, str] = {
    "check_citation_integrity.py": "needs a Hermes checkout (--src / HERMES_AGENT_SRC)",
    "check_skill_version_bump.py": "needs an origin/master merge base",
    "test_readonly_runtime.py": "runs the hermes CLI, which can trigger a long build",
    "check_skill_dogfood.py": "runs read-only hermes commands against a live install",
    "tools/test_*.py (rest)": "regression suites — CI's job",
}


def _run(script: str) -> tuple[int, str]:
    """Return (returncode, combined output) for one gate."""
    path = REPO / "tools" / script
    if not path.is_file():
        return 127, f"error: missing gate script tools/{script}"
    proc = subprocess.run(
        [sys.executable, str(path)], capture_output=True, text=True, cwd=REPO
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _list() -> int:
    print("Hermetic tier — runs on every commit:")
    for script, why in _GATES.items():
        print(f"  tools/{script}\n      {why}")
    print("\nLeft to CI (why it is excluded):")
    for script, why in _SLOW.items():
        print(f"  tools/{script}\n      {why}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="check_gates.py", description=_USAGE)
    ap.add_argument("--list", action="store_true", help="show the tiering and exit")
    ap.add_argument("--quick", action="store_true", help="counts + provenance only")
    opts = ap.parse_args(argv[1:])

    if opts.list:
        return _list()

    gates = [g for g in _GATES if not opts.quick or g in _QUICK]
    failed: list[str] = []

    for script in gates:
        code, out = _run(script)
        if code == 0:
            # Neighbors print their own summary; keep theirs, don't restate.
            print(f"  ok    {script}  {out.splitlines()[0] if out else 'OK'}")
            continue
        print(f"  FAIL  {script}", file=sys.stderr)
        for line in out.splitlines():
            print(f"        {line}", file=sys.stderr)
        failed.append(script)

    if failed:
        print(
            f"\nFAIL: {len(failed)}/{len(gates)} gate(s) failed: {', '.join(failed)}",
            file=sys.stderr,
        )
        print("CI runs the same gates. `--list` shows what this tier omits.", file=sys.stderr)
        return 1

    print(f"OK: {len(gates)}/{len(gates)} hermetic gate(s) passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
