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

import importlib.util
import os
import re
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

    def check_admits_tag_blind_coverage() -> str | None:
        """With no tags fetched, --check must say so, not claim full coverage.

        actions/checkout defaults to no tags, so the tag half silently checks
        nothing in a shallow CI clone. The version half still catches the real
        failure, but the success line must not overstate what ran — a guard that
        reads as full coverage while checking one release is the bug this
        guards against.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)                      # no tags created
            _commit(root, "feat: thing (#1)")
            (root / "CHANGELOG.md").write_text(
                HEADER + "## v1.0.0 (2026-01-01)\n\n### Features\n\n- thing (#1)\n",
                encoding="utf-8",
            )
            code, out = _run(root, "--check")
            if code != 0:
                return f"--check on a tag-blind tree expected 0, got {code}: {out}"
            if "no release tags visible" not in out:
                return f"--check hid the tag-blind gap: {out}"
            if "every release tag" in out:
                return f"--check claimed full tag coverage with no tags: {out}"
        return None

    def check_still_catches_bumped_version_without_tags() -> str | None:
        """The version half must work with zero tags — that is the CI shape."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            (root / "CHANGELOG.md").write_text(
                HEADER + "## v0.9.0 (2026-01-01)\n\n### Features\n\n- old\n",
                encoding="utf-8",
            )
            # plugin.yaml says 1.0.0, which has no section; no tags exist.
            code, out = _run(root, "--check")
            if code != 1:
                return f"tag-blind bumped version expected 1, got {code}: {out}"
            if "v1.0.0" not in out:
                return f"did not name the uncovered version: {out}"
        return None

    def check_fails_without_a_version() -> str | None:
        """No version and no tags must not read as 'clean'.

        `expected` is built from tags + the plugin.yaml version. With both
        absent the set is empty, every() finds nothing missing, and the guard
        exits 0 having checked no release at all — a green run that verified
        nothing. Reported by CodeRabbit on the PR; pinned here.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            (root / "plugin.yaml").write_text("name: demo\n", encoding="utf-8")
            (root / "CHANGELOG.md").write_text(HEADER, encoding="utf-8")
            code, out = _run(root, "--check")
            if code != 2:
                return f"--check with no version and no tags expected 2, got {code}: {out}"
            if "cannot verify coverage" not in out:
                return f"--check did not explain the refusal: {out}"
        return None

    def marker_tags_are_not_release_tags() -> str | None:
        """A non-v<semver> tag must not demand a section (false positive).

        The guard treats every tag as needing a section, so a marker tag like
        `docs-snapshot` would fail it forever with no way to satisfy it.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            _commit(root, "feat: thing (#1)")
            (root / "CHANGELOG.md").write_text(
                HEADER + "## v1.0.0 (2026-01-01)\n\n### Features\n\n- thing (#1)\n",
                encoding="utf-8",
            )
            _git(root, "tag", "v1.0.0")
            _git(root, "tag", "docs-snapshot")
            _git(root, "tag", "pre-refactor")
            code, out = _run(root, "--check")
            if code != 0:
                return f"marker tags caused a false positive: exit={code}: {out}"
            if "docs-snapshot" in out:
                return f"marker tag leaked into the report: {out}"
        return None

    def release_tags_still_fail_when_uncovered() -> str | None:
        """The marker-tag filter must not weaken real detection."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root, version="2.0.0")
            _commit(root, "feat: thing (#1)")
            (root / "CHANGELOG.md").write_text(
                HEADER + "## v1.0.0 (2026-01-01)\n\n### Features\n\n- thing (#1)\n",
                encoding="utf-8",
            )
            _git(root, "tag", "v1.0.0")
            _git(root, "tag", "v1.5.0")          # release tag, no section
            _git(root, "tag", "docs-snapshot")   # marker tag
            code, out = _run(root, "--check")
            if code != 1:
                return f"uncovered release tags expected 1, got {code}: {out}"
            if "v1.5.0" not in out or "v2.0.0" not in out:
                return f"did not name both uncovered releases: {out}"
            if "docs-snapshot" in out:
                return f"marker tag wrongly reported: {out}"
        return None

    def upcoming_preserves_section_date() -> str | None:
        """Regenerating must not re-stamp an existing section's date.

        An untagged version is dated with the UTC day, so a rerun on a later day
        would rewrite the heading and churn the file for no content reason.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            _commit(root, "feat: first (#1)")
            _git(root, "tag", "v1.0.0")
            (root / "CHANGELOG.md").write_text(
                HEADER + "## v1.0.0 (2026-01-01)\n\n### Features\n\n- first (#1)\n",
                encoding="utf-8",
            )
            _commit(root, "fix: second (#2)")
            (root / "plugin.yaml").write_text("name: demo\nversion: 1.1.0\n", encoding="utf-8")
            code, _ = _run(root, "--upcoming")
            if code != 0:
                return f"first --upcoming failed: exit={code}"
            first = (root / "CHANGELOG.md").read_text(encoding="utf-8")
            # Rewrite the heading to a different day, then regenerate: the
            # existing date must survive, and the body must not lose a blank line.
            stamped = re.sub(r"^## v1\.1\.0 \(\d{4}-\d{2}-\d{2}\)$",
                             "## v1.1.0 (2020-01-01)", first, flags=re.M)
            (root / "CHANGELOG.md").write_text(stamped, encoding="utf-8")
            code, _ = _run(root, "--upcoming")
            if code != 0:
                return f"second --upcoming failed: exit={code}"
            second = (root / "CHANGELOG.md").read_text(encoding="utf-8")
            if "## v1.1.0 (2020-01-01)" not in second:
                return f"existing date was re-stamped:\n{second}"
            if "## v1.1.0 (2020-01-01)\n\n### " not in second:
                return f"blank line after the heading was consumed:\n{second}"
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

    def upcoming_stamps_utc_date() -> str | None:
        """A new section carries the UTC day, never the machine-local day.

        Deterministic via HERMES_CHANGELOG_DATE: a wall-clock assertion
        here would flake when UTC midnight falls between stamp and check.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            _commit(root, "feat: first (#1)")
            os.environ["HERMES_CHANGELOG_DATE"] = "2031-05-17"
            try:
                code, out = _run(root, "--upcoming")
            finally:
                del os.environ["HERMES_CHANGELOG_DATE"]
            if code != 0:
                return f"--upcoming expected 0, got {code}: {out}"
            text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
            if "## v1.0.0 (2031-05-17)" not in text:
                return f"--upcoming did not stamp the override date:\n{text}"
        return None

    def utc_helper_ignores_local_day() -> str | None:
        """_utc_today() follows UTC even when the local day differs.

        23:30 UTC is already tomorrow east of UTC+1 — date.today() would
        stamp the wrong day there.
        """
        from datetime import datetime as _dt
        from datetime import timezone as _tz
        spec = importlib.util.spec_from_file_location("gen_changelog_probe", TOOL)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        class _Fixed(_dt):
            @classmethod
            def now(cls, tz=None):
                return _dt(2031, 5, 17, 23, 30, tzinfo=_tz.utc)

        mod.datetime = _Fixed
        if mod._utc_today() != "2031-05-17":
            return f"_utc_today() did not follow UTC: {mod._utc_today()}"
        return None

    def upcoming_never_stamps_local_date() -> str | None:
        """The generator must not call date.today() (local-day stamp)."""
        src = TOOL.read_text(encoding="utf-8")
        if "date.today(" in src:
            return "gen_changelog.py still calls date.today()"
        return None

    return [
        ("--upcoming then --check is clean", check_clean_after_upcoming),
        ("--check fails on a tag with no section", check_fails_on_missing_section),
        ("--check fails on an untagged plugin.yaml version", check_fails_on_untagged_version),
        ("--upcoming is idempotent and newest-first", upcoming_is_idempotent),
        ("--check reports an unreadable CHANGELOG.md as unusable", check_reports_unreadable_changelog),
        ("--check admits tag-blind coverage", check_admits_tag_blind_coverage),
        ("--check catches a bumped version with no tags", check_still_catches_bumped_version_without_tags),
        ("--check refuses when no version and no tags", check_fails_without_a_version),
        ("marker tags are not release tags", marker_tags_are_not_release_tags),
        ("uncovered release tags still fail", release_tags_still_fail_when_uncovered),
        ("--upcoming preserves an existing section date", upcoming_preserves_section_date),
        ("--upcoming fails without a plugin.yaml version", upcoming_fails_without_version),
        ("--upcoming stamps the UTC date", upcoming_stamps_utc_date),
        ("_utc_today ignores the local day", utc_helper_ignores_local_day),
        ("--upcoming never calls date.today", upcoming_never_stamps_local_date),
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
