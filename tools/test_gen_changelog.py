#!/usr/bin/env python3
"""Behavioral coverage for gen_changelog.py's ``--upcoming`` and ``--check`` modes.

Both modes exist to fix one failure: a release section generated on tag push
lands on a branch no one merges, so CHANGELOG.md falls a release behind. The
tag-coverage guard (``--check``) is what makes that impossible to ship again,
and a guard is only worth having if it can fail — so every case below runs the
real entry point against a throwaway repo and asserts the exit code.

The repo is built with ``git init`` in a temp dir and the tool is invoked with
``cwd`` inside it, because both modes resolve ``REPO`` from ``__file__``. A
symlink into the temp tree keeps the tool's own ``REPO`` pointing there without
copying the file, so the test exercises the shipped source, not a fixture copy.

Stdlib only — no PyYAML, no Hermes, no network. Safe for the fast tier.

Usage:
    python tools/test_gen_changelog.py

Exit codes: 0 clean, 1 a case failed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "gen_changelog.py"

HEADER = "# Changelog\n\nAll notable changes to demo are documented here.\n\n"


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=root, check=True,
        capture_output=True, text=True,
        env={**os.environ,
             "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"},
    )


def _commit(root: Path, message: str) -> None:
    (root / "f.txt").write_text(message, encoding="utf-8")
    _git(root, "add", "f.txt")
    _git(root, "commit", "-m", message)


def _run(root: Path, *args: str) -> tuple[int, str]:
    """Run the real tool with its REPO resolving to *root*.

    The source is copied rather than symlinked: the tool derives ``REPO`` from
    ``Path(__file__).resolve()``, which follows a symlink straight back to the
    real checkout, so a link would test the repo instead of the fixture.
    """
    tools = root / "tools"
    tools.mkdir(exist_ok=True)
    target = tools / "gen_changelog.py"
    if not target.exists():
        shutil.copy2(TOOL, target)
    proc = subprocess.run(
        [sys.executable, str(target), *args],
        cwd=root, capture_output=True, text=True,
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _fixture(root: Path, version: str = "1.0.0") -> None:
    _git(root, "init", "--quiet", "-b", "main")
    (root / "plugin.yaml").write_text(f"name: demo\nversion: {version}\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text(HEADER, encoding="utf-8")
    _commit(root, "chore: initial commit")


def _cases() -> list[tuple[str, Callable[[], str | None]]]:
    def check_clean_after_upcoming() -> str | None:
        """--upcoming writes a section; --check then passes on it."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            _commit(root, "feat(api): add a thing (#1)")
            code, out = _run(root, "--upcoming")
            if code != 0:
                return f"--upcoming expected 0, got {code}: {out}"
            text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
            if "## v1.0.0 (" not in text:
                return f"--upcoming did not write the section:\n{text}"
            if "**api**: add a thing" not in text:
                return f"section missing the commit subject:\n{text}"
            code, out = _run(root, "--check")
            if code != 0:
                return f"--check after --upcoming expected 0, got {code}: {out}"
        return None

    def check_fails_on_missing_section() -> str | None:
        """The guard fires when a tag has no section — the real drift."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            _commit(root, "feat: something (#1)")
            _git(root, "tag", "v1.0.0")
            code, out = _run(root, "--check")
            if code != 1:
                return f"--check with a missing section expected 1, got {code}: {out}"
            if "v1.0.0" not in out:
                return f"--check did not name the missing tag: {out}"
        return None

    def check_fails_on_untagged_version() -> str | None:
        """plugin.yaml's version counts even before the tag exists."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root, version="2.0.0")
            _commit(root, "feat: next release (#2)")
            # A section exists for v1.0.0 only; v2.0.0 is untagged and uncovered.
            (root / "CHANGELOG.md").write_text(
                HEADER + "## v1.0.0 (2026-01-01)\n\n### Features\n\n- x\n",
                encoding="utf-8",
            )
            code, out = _run(root, "--check")
            if code != 1:
                return f"--check with uncovered plugin.yaml version expected 1, got {code}: {out}"
            if "v2.0.0" not in out:
                return f"--check did not name the uncovered version: {out}"
        return None

    def upcoming_is_idempotent() -> str | None:
        """Re-running --upcoming must not duplicate or reorder sections."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            _commit(root, "feat: first (#1)")
            _git(root, "tag", "v1.0.0")
            # v1.0.0 is released, so its section is already in the file.
            (root / "CHANGELOG.md").write_text(
                HEADER + "## v1.0.0 (2026-01-01)\n\n### Features\n\n- first (#1)\n",
                encoding="utf-8",
            )
            _commit(root, "fix: second (#2)")
            (root / "plugin.yaml").write_text(
                "name: demo\nversion: 1.1.0\n", encoding="utf-8"
            )
            code, out = _run(root, "--upcoming")
            if code != 0:
                return f"first --upcoming expected 0, got {code}: {out}"
            first = (root / "CHANGELOG.md").read_text(encoding="utf-8")
            code, out = _run(root, "--upcoming")
            if code != 0:
                return f"second --upcoming expected 0, got {code}: {out}"
            second = (root / "CHANGELOG.md").read_text(encoding="utf-8")
            if first != second:
                return ("--upcoming is not idempotent:\n"
                        f"--- first ---\n{first}\n--- second ---\n{second}")
            if second.count("## v1.1.0") != 1:
                return f"section duplicated:\n{second}"
            # Newest release must come first, matching the all-releases layout.
            if second.index("## v1.1.0") > second.index("## v1.0.0"):
                return f"newest section is not first:\n{second}"
        return None

    def check_reports_unreadable_changelog() -> str | None:
        """A missing CHANGELOG.md is unusable input (2), not drift (1)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            (root / "CHANGELOG.md").unlink()
            code, out = _run(root, "--check")
            if code != 2:
                return f"--check without CHANGELOG.md expected 2, got {code}: {out}"
        return None

    def upcoming_fails_without_version() -> str | None:
        """No version in plugin.yaml is an error, not a silent empty write."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            (root / "plugin.yaml").write_text("name: demo\n", encoding="utf-8")
            code, out = _run(root, "--upcoming")
            if code != 1:
                return f"--upcoming without a version expected 1, got {code}: {out}"
        return None

    return [
        ("--upcoming then --check is clean", check_clean_after_upcoming),
        ("--check fails on a tag with no section", check_fails_on_missing_section),
        ("--check fails on an untagged plugin.yaml version", check_fails_on_untagged_version),
        ("--upcoming is idempotent and newest-first", upcoming_is_idempotent),
        ("--check reports an unreadable CHANGELOG.md as unusable", check_reports_unreadable_changelog),
        ("--upcoming fails without a plugin.yaml version", upcoming_fails_without_version),
    ]


def main() -> int:
    failures = 0
    cases = _cases()
    for name, fn in cases:
        problem = fn()
        if problem:
            failures += 1
            print(f"FAIL: {name}: {problem}", file=sys.stderr)
    if failures:
        print(f"error: {failures}/{len(cases)} case(s) failed", file=sys.stderr)
        return 1
    print(f"OK: gen_changelog {len(cases)} case(s) passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
