#!/usr/bin/env python3
"""Fail if a guard or regression test in tools/ is never run by CI.

A `tools/test_*.py` or `tools/check_*.py` file that no workflow references is
silent dead coverage: it passes or fails locally, nobody notices, and the bug
it was written for can return unnoticed. This repo shipped exactly that --
`test_skill_malformed_name.py` existed from #133 onward and no workflow ran it.

Scope: reference by filename anywhere in `.github/workflows/*.yml`. A step may
be gated, Linux-only, or matrix-conditional -- all still count as wired.
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

# `tools/<name>.py` as written in a workflow `run:` block. The name allows
# hyphens (scripts are not restricted to identifiers), and the trailing
# negative lookahead rejects compound suffixes so a `.py.bak` or `.pyc` left in
# the tree cannot stand in for a real invocation.
_MENTION = re.compile(r"tools/([A-Za-z0-9_-]+)\.py(?![A-Za-z0-9_.])")

# Prefixes that must be executed. `tools/pr_metadata_labels.py` and friends are
# helpers invoked by their own step, so they are covered by the same rule.
_PREFIXES = ("test_", "check_")


def find_orphans(tools_dir: Path, workflow_dir: Path) -> list[str]:
    """Return sorted names of tools/ scripts that no workflow references."""
    referenced: set[str] = set()
    for workflow in sorted(workflow_dir.glob("*.yml")) + sorted(workflow_dir.glob("*.yaml")):
        referenced |= set(_MENTION.findall(workflow.read_text(encoding="utf-8")))

    # `is_file()` first: a *directory* named `check_helpers.py` would otherwise
    # be globbed, counted as a script, and reported as unwired forever.
    on_disk = {
        p.stem
        for p in tools_dir.glob("*.py")
        if p.is_file() and not p.name.startswith("_")
    }
    return sorted(n for n in on_disk if n.startswith(_PREFIXES) and n not in referenced)


def selftest() -> int:
    cases = [
        # (tools files, workflow text, expected orphan stems)
        (["test_a.py", "check_b.py"], "run: python tools/test_a.py", ["check_b"]),
        (["test_a.py", "check_b.py"], "run: python tools/check_b.py", ["test_a"]),
        (["test_a.py", "check_b.py"],
         "run: python tools/test_a.py && python tools/check_b.py", []),
        ([], "run: python tools/test_a.py", []),
        # Not a guard or test: helpers are not required to be wired directly.
        (["pr_metadata_labels.py"], "", []),
        # A leading underscore marks a shared module, not an entry point.
        (["_shared.py"], "", []),
        # Flags and args in the invocation still count as wired.
        (["test_a.py"], "run: python tools/test_a.py --selftest", []),
        # A hyphen is a legal filename character, not a word boundary.
        (["test_cli-v2.py"], "run: python tools/test_cli-v2.py", []),
        # A compound suffix is not a real invocation of the script.
        (["test_a.py"], "run: python tools/test_a.py.bak", ["test_a"]),
        (["test_a.py"], "run: python tools/test_a.pyc", ["test_a"]),
        # A directory named like a script is not a script.
        (["check_helpers.py/"], "", []),
    ]
    failures = 0
    for names, workflow, expect in cases:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tools, wf = root / "tools", root / "workflows"
            tools.mkdir()
            wf.mkdir()
            for n in names:
                if n.endswith("/"):
                    (tools / n.rstrip("/")).mkdir()
                else:
                    (tools / n).write_text("", encoding="utf-8")
            (wf / "ci.yml").write_text(workflow, encoding="utf-8")
            got = find_orphans(tools, wf)
        if got != expect:
            failures += 1
            print(
                f"SELFTEST FAIL: expected {expect}, got {got} "
                f"for tools={names} workflow={workflow!r}",
                file=sys.stderr,
            )
    if failures:
        print(f"error: {failures}/{len(cases)} selftest case(s) failed", file=sys.stderr)
        return 1
    print(f"OK: selftest {len(cases)} case(s) passed")
    return 0


def main(argv: list[str]) -> int:
    repo = Path(__file__).resolve().parent.parent
    if "--selftest" in argv:
        return selftest()

    orphans = find_orphans(repo / "tools", repo / ".github" / "workflows")
    if orphans:
        print("FAIL: tools script(s) never run by CI:", file=sys.stderr)
        for name in orphans:
            print(f"  {name}.py", file=sys.stderr)
        print(
            "\nAdd a step in .github/workflows/reusable-ci.yml, or delete the file "
            "if it is no longer needed. Unwired coverage is silently dead.",
            file=sys.stderr,
        )
        return 1
    print("OK: every tools guard and regression test is wired into CI")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))