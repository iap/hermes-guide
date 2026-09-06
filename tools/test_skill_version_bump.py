#!/usr/bin/env python3
"""Regression coverage for tools/check_skill_version_bump.py exit contracts.

The guard's failure modes are easy to silently break in both directions:

  - An unresolvable ref used to SKIP the check (exit 0) — the guard then
    enforced nothing while CI stayed green. Now it must exit 2.
  - A changed SKILL.md without a bump must exit 1; with a bump, exit 0.

Builds a throwaway git repo per case and runs the guard as a subprocess,
asserting exit codes — no network, no GitHub, no state outside the fixture.

Run: python3 tools/test_skill_version_bump.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GUARD = REPO / "tools" / "check_skill_version_bump.py"

SKILL_V1 = "---\nname: sample\ndescription: sample skill\nversion: 1.0.0\n---\nbody\n"
SKILL_V2 = SKILL_V1.replace("version: 1.0.0", "version: 1.0.1")


def _git(repo: Path, *args: str) -> None:
    # Inherit the runner environment (PATH must survive on Windows, where git
    # lives outside /usr/bin) but cut global config: a developer's
    # core.hooksPath or identity must not run inside the fixture.
    env = os.environ.copy()
    env.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
                "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": str(repo / ".gitconfig-global")})
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True, env=env,
    )


def _make_repo(bump_version: bool) -> Path:
    """Repo with one committed SKILL.md (1.0.0) and a modified working tree."""
    repo = Path(tempfile.mkdtemp())
    (repo / ".gitconfig-global").touch()  # isolate from the developer's git config
    skill = repo / "skills" / "sample"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(SKILL_V1, encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    if bump_version:
        (skill / "SKILL.md").write_text(SKILL_V2, encoding="utf-8")
    else:
        (skill / "SKILL.md").write_text(
            SKILL_V1.replace("body", "changed body"), encoding="utf-8"
        )
    return repo


def _run_guard(repo: Path, *args: str) -> int:
    return subprocess.run(
        [sys.executable, str(GUARD), *args],
        cwd=repo, capture_output=True, text=True,
    ).returncode


def case_bogus_ref() -> None:
    """An unresolvable explicit ref must exit 2 (was: silent skip)."""
    repo = _make_repo(bump_version=True)
    rc = _run_guard(repo, "nonexistent-ref-xyz")
    assert rc == 2, f"bogus ref: expected exit 2, got {rc}"


def case_default_ref_missing() -> None:
    """The CI no-op regression: no origin/master ref -> exit 2, never 0.

    A depth-1 checkout has no origin/master; before the fail-hard fix the
    guard skipped (exit 0) and enforced nothing while CI stayed green.
    """
    repo = _make_repo(bump_version=True)
    rc = _run_guard(repo)  # default ref "origin/master" does not exist here
    assert rc == 2, f"missing default ref: expected exit 2, got {rc}"


def case_bumped_ok() -> None:
    """Changed SKILL.md WITH a version bump, checked against HEAD -> exit 0."""
    repo = _make_repo(bump_version=True)
    rc = _run_guard(repo, "HEAD")
    assert rc == 0, f"bumped change: expected exit 0, got {rc}"


def case_unbumped_fails() -> None:
    """Changed SKILL.md WITHOUT a bump -> exit 1 (the guard still bites)."""
    repo = _make_repo(bump_version=False)
    rc = _run_guard(repo, "HEAD")
    assert rc == 1, f"unbumped change: expected exit 1, got {rc}"


def main() -> int:
    cases = [case_bogus_ref, case_default_ref_missing, case_bumped_ok, case_unbumped_fails]
    failed = 0
    for case in cases:
        try:
            case()
            print(f"OK: {case.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL: {case.__name__}: {exc}", file=sys.stderr)
    if failed:
        print(f"{failed}/{len(cases)} case(s) failed", file=sys.stderr)
        return 1
    print(f"OK: {len(cases)} version-bump guard case(s) passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
