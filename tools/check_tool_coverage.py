#!/usr/bin/env python3
"""Fail if a guard or regression test in tools/ or tests/ is never run by CI.

A `tools/test_*.py` or `tools/check_*.py` file that no workflow references is
silent dead coverage: it passes or fails locally, nobody notices, and the bug
it was written for can return unnoticed. This repo shipped exactly that --
`test_skill_malformed_name.py` existed from #133 onward and no workflow ran it.

The scanner-hygiene guard lives under `tests/` (upstream install-scanner
verdict; see reusable-ci.yml), so both harness directories are scanned.

Scope: reference by filename anywhere in `.github/workflows/*.yml`. A step may
be gated, Linux-only, or matrix-conditional -- all still count as wired.
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

# `tools/<name>.py` (or `tests/<name>.py`) as written in a workflow `run:`
# block, captured as the repo-relative path: `tests/check_b.py` must not
# count as wiring `tools/check_b.py` — same basename, different script.
_MENTION = re.compile(r"((?:tools|tests)/[A-Za-z0-9_-]+\.py)(?![A-Za-z0-9_.])")

# Prefixes that must be executed. `tools/pr_metadata_labels.py` and friends are
# helpers invoked by their own step, so they are covered by the same rule.
_PREFIXES = ("test_", "check_")

# Executable helpers that are CI dependencies without being guards or tests.
# Each must be referenced by a workflow like the prefixed scripts above:
# `render_docs.py` renders the generated doc blocks CI enforces,
# `gen_changelog.py` runs in the release workflow, and `pr_metadata_labels.py`
# drives auto-labelling. An unreferenced helper is the same silent death.
_WIRED_HELPERS = ("render_docs", "gen_changelog", "pr_metadata_labels")


def find_orphans(tools_dir: Path, workflow_dir: Path) -> list[str]:
    """Return sorted entry-point paths (repo-relative) that no workflow runs."""
    referenced: set[str] = set()
    for workflow in sorted(workflow_dir.glob("*.yml")) + sorted(workflow_dir.glob("*.yaml")):
        referenced |= set(_MENTION.findall(workflow.read_text(encoding="utf-8")))

    # `is_file()` first: a *directory* named `check_helpers.py` would otherwise
    # be globbed, counted as a script, and reported as unwired forever.
    # Both harness directories are scanned: the scanner-hygiene guard lives
    # under tests/ (upstream install-scanner verdict).
    repo = tools_dir.parent
    harness_dirs = [tools_dir]
    tests_dir = repo / "tests"
    if tests_dir.is_dir():
        harness_dirs.append(tests_dir)
    on_disk = {
        str(p.relative_to(repo)).replace("\\", "/")
        for harness in harness_dirs
        for p in harness.glob("*.py")
        if p.is_file() and not p.name.startswith("_")
    }
    required = {
        n for n in on_disk
        if Path(n).stem.startswith(_PREFIXES) or Path(n).stem in _WIRED_HELPERS
    }
    return sorted(n for n in required if n not in referenced)


def selftest() -> int:
    cases = [
        # (tools files, workflow text, expected orphan paths)
        # Names may include a tests/ prefix; the temp tree mirrors the repo.
        (["test_a.py", "check_b.py"], "run: python tools/test_a.py", ["tools/check_b.py"]),
        (["test_a.py", "check_b.py"], "run: python tools/check_b.py", ["tools/test_a.py"]),
        (["test_a.py", "check_b.py"],
         "run: python tools/test_a.py && python tools/check_b.py", []),
        ([], "run: python tools/test_a.py", []),
        # Helpers in the wired list must be referenced too.
        (["render_docs.py"], "", ["tools/render_docs.py"]),
        (["render_docs.py", "gen_changelog.py"],
         "run: python tools/render_docs.py", ["tools/gen_changelog.py"]),
        # A helper outside the wired list stays exempt.
        (["some_helper.py"], "", []),
        # A leading underscore marks a shared module, not an entry point.
        (["_shared.py"], "", []),
        # Flags and args in the invocation still count as wired.
        (["test_a.py"], "run: python tools/test_a.py --selftest", []),
        # A hyphen is a legal filename character, not a word boundary.
        (["test_cli-v2.py"], "run: python tools/test_cli-v2.py", []),
        # A compound suffix is not a real invocation of the script.
        (["test_a.py"], "run: python tools/test_a.py.bak", ["tools/test_a.py"]),
        (["test_a.py"], "run: python tools/test_a.pyc", ["tools/test_a.py"]),
        # A directory named like a script is not a script.
        (["check_helpers.py/"], "", []),
        # Both harness directories count as wired references.
        (["test_a.py", "check_b.py"], "run: python tests/check_b.py", ["tools/check_b.py", "tools/test_a.py"]),
        # Same basename in the other dir does NOT wire this one: a
        # tests/check_b.py reference leaves tools/check_b.py orphaned.
        (["tools/check_b.py", "tests/check_b.py"], "run: python tests/check_b.py", ["tools/check_b.py"]),
        # ...and the reverse: tools/ reference leaves tests/ orphaned.
        (["tools/check_b.py", "tests/check_b.py"], "run: python tools/check_b.py", ["tests/check_b.py"]),
    ]
    failures = 0
    for names, workflow, expect in cases:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tools, wf = root / "tools", root / "workflows"
            tools.mkdir()
            wf.mkdir()
            for n in names:
                is_dir = n.endswith("/")
                rel = n.rstrip("/")
                target = root / rel if "/" in rel else tools / rel
                if is_dir:
                    target.mkdir()
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text("", encoding="utf-8")
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
        print("FAIL: harness script(s) never run by CI (repo-relative):", file=sys.stderr)
        for name in orphans:
            print(f"  {name}", file=sys.stderr)
        print(
            "\nAdd a step in .github/workflows/reusable-ci.yml, or delete the file "
            "if it is no longer needed. Unwired coverage is silently dead.",
            file=sys.stderr,
        )
        return 1
    print("OK: every tools/tests guard and regression test is wired into CI")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))