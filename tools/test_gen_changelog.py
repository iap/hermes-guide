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
        capture_output=True, text=True, encoding="utf-8", errors="replace",
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
    def bom_prefixed_subject_keeps_its_type() -> str | None:
        """A BOM before `fix:` must not demote the commit to a chore.

        ``str.strip()`` leaves U+FEFF alone, so the anchored type regex misses
        and a real fix is filed under Chores — with the BOM pasted into
        CHANGELOG.md. Hit on real release commits (#300, #305) and pinned here.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            msg = root / "msg.txt"
            msg.write_text("\ufefffix(api): bom subject (#7)", encoding="utf-8")
            (root / "f.txt").write_text("x", encoding="utf-8")
            _git(root, "add", "f.txt")
            _git(root, "commit", "-F", "msg.txt")
            code, out = _run(root, "--upcoming")
            if code != 0:
                return f"--upcoming expected 0, got {code}: {out}"
            text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
            if "\ufeff" in text:
                return f"a BOM leaked into the changelog:\n{text!r}"
            idx = text.find("- **api**: bom subject")
            if idx == -1:
                return f"section missing the subject:\n{text}"
            # The heading that governs our line is the last one before it; the
            # fixture's own `chore: initial commit` legitimately opens a Chores
            # section, so assert placement rather than the absence of one.
            heading = text[:idx].rsplit("### ", 1)[-1].splitlines()[0].strip()
            if heading != "Bug Fixes":
                return f"the fix landed under {heading!r}, not Bug Fixes:\n{text}"
        return None

    def log_encoding_overrides_configured_output() -> str | None:
        """A legacy `i18n.logOutputEncoding` must not mangle a subject.

        `git log` honours that config, so without `--encoding=UTF-8` the tool
        decodes legacy bytes as UTF-8 — the run dies or the subject loses
        characters. The flag makes git transcode before Python reads it.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            msg = root / "msg.txt"
            msg.write_text("fix(api): café (#8)", encoding="utf-8")
            (root / "f.txt").write_text("x", encoding="utf-8")
            _git(root, "add", "f.txt")
            _git(root, "commit", "-F", "msg.txt")
            # Set after the commit: the config only affects `git log` output,
            # and applying it earlier makes git's own commit summary bytes
            # non-UTF-8 in the helper's captured stdout.
            _git(root, "config", "i18n.logOutputEncoding", "ISO-8859-1")
            code, out = _run(root, "--upcoming")
            if code != 0:
                return f"--upcoming expected 0, got {code}: {out}"
            text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
            if "café" not in text:
                return f"the subject was mangled under a legacy log encoding:\n{text!r}"
        return None

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

    def check_fails_on_missing_entry() -> str | None:
        """A section can exist and still omit a PR merged into its tag range.

        This is the v0.8.6 failure: #323 was in the tag but not in the
        section, and section-existence alone read clean. Plain `(#N)` refs
        count as coverage, so only the genuinely missing PR is reported.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            _commit(root, "feat(api): real change (#1)")
            _commit(root, "fix(api): second change (#2)")
            _commit(root, "release: bump to v1.0.0 with changelog section")
            _git(root, "tag", "v1.0.0")
            (root / "CHANGELOG.md").write_text(
                HEADER + "## v1.0.0 (2026-01-01)\n\n### Features\n\n"
                "- **api**: real change (#1)\n",
                encoding="utf-8",
            )
            code, out = _run(root, "--check")
            if code != 1:
                return f"missing entry expected 1, got {code}: {out}"
            if "#2" not in out:
                return f"did not name the omitted PR: {out}"
            if "#1" in out:
                return f"reported a PR the section already lists: {out}"
        return None

    def release_commit_needs_no_entry() -> str | None:
        """The tag's own commit is the section, in either subject style.

        Squash merges render the bump as `chore(release): bump to 0.7.2 (#250)`;
        excluding by SHA covers that without a subject heuristic.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            _commit(root, "feat: thing (#1)")
            _commit(root, "chore(release): bump to 1.1.0 (#2)")
            _git(root, "tag", "v1.1.0")
            (root / "plugin.yaml").write_text(
                "name: demo\nversion: 1.1.0\n", encoding="utf-8"
            )
            (root / "CHANGELOG.md").write_text(
                HEADER + "## v1.1.0 (2026-01-01)\n\n### Features\n\n- thing (#1)\n",
                encoding="utf-8",
            )
            code, out = _run(root, "--check")
            if code != 0:
                return f"release commit wrongly required an entry: {code}: {out}"
        return None

    def pre_cutoff_tags_are_exempt() -> str | None:
        """Merge-commit-era releases carry no PR refs; demanding one is noise.

        Coverage starts at the first PR-generated section (v0.7.0). An older
        section without `(#N)` refs must not fail the guard.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            _commit(root, "feat: old (#3)")
            _git(root, "tag", "v0.6.0")
            _commit(root, "feat: new (#4)")
            _commit(root, "release: bump to v1.0.0")
            _git(root, "tag", "v1.0.0")
            (root / "CHANGELOG.md").write_text(
                HEADER
                + "## v1.0.0 (2026-01-01)\n\n### Features\n\n- new (#4)\n\n"
                + "## v0.6.0 (2025-01-01)\n\n### Features\n\n- old\n",
                encoding="utf-8",
            )
            code, out = _run(root, "--check")
            if code != 0:
                return f"pre-cutoff tag caused a false positive: {code}: {out}"
        return None

    def coverage_ranges_follow_version_not_tag_date() -> str | None:
        """Caller tag order must not decide which range a PR belongs to.

        ``git tag --sort=-creatordate`` cannot order two tags created in the
        same second, and a wrong ``prev`` makes one release's range swallow
        another's commits. CI hit this on the pre-cutoff fixture, where both
        tags were created within the same second locally and reported #3
        under v1.0.0. The guard sorts by version, so the order passed in is
        irrelevant.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            _commit(root, "feat: old (#3)")
            _git(root, "tag", "v0.6.0")
            _commit(root, "feat: new (#4)")
            _commit(root, "release: bump to v1.0.0")
            _git(root, "tag", "v1.0.0")
            spec = importlib.util.spec_from_file_location("gen_changelog_order", TOOL)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.REPO = root
            sections = {"v1.0.0": "- new (#4)", "v0.6.0": "- old"}
            for order in (["v0.6.0", "v1.0.0"], ["v1.0.0", "v0.6.0"]):
                gaps = mod.missing_entries(order, sections)
                if gaps:
                    return f"tag order {order} produced gaps: {gaps}"
        return None

    def shallow_checkout_fails_closed() -> str | None:
        """A shallow clone must not read as full entry coverage.

        Git treats the shallow boundary as a root, so `git log <prev>..<tag>`
        succeeds with a truncated range when the tags are present. The guard
        asks `--is-shallow-repository` first and exits 2 instead of claiming
        verified coverage from partial history.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "src"
            root.mkdir()
            _fixture(root)
            _commit(root, "feat: new (#4)")
            (root / "CHANGELOG.md").write_text(
                HEADER + "## v1.0.0 (2026-01-01)\n\n### Features\n\n- new (#4)\n",
                encoding="utf-8",
            )
            _git(root, "add", "-A")
            _git(root, "commit", "-m", "track fixture files")
            _git(root, "tag", "v1.0.0")
            clone = Path(tmp) / "clone"
            _git(Path(tmp), "clone", "--depth", "1", root.as_uri(), str(clone))
            code, out = _run(clone, "--check")
            if code != 2:
                return f"shallow clone expected 2, got {code}: {out}"
            if "shallow" not in out.lower():
                return f"shallow clone error did not name the cause: {out}"
        return None

    def nonconventional_squash_commit_is_covered() -> str | None:
        """A PR ref counts even when the subject is not a conventional commit.

        A squash merge can render as `Add triage guidance (#5)`; the parser
        files it under Chores with no `pr`, so coverage has to read the
        trailing ref from the raw subject instead of trusting the classifier.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            _commit(root, "Add triage guidance (#5)")
            _commit(root, "release: bump to v1.0.0")
            _git(root, "tag", "v1.0.0")
            (root / "CHANGELOG.md").write_text(
                HEADER + "## v1.0.0 (2026-01-01)\n\n### Chores\n\n"
                "- triage guidance\n",
                encoding="utf-8",
            )
            code, out = _run(root, "--check")
            if code != 1:
                return f"non-conventional PR expected 1, got {code}: {out}"
            if "#5" not in out:
                return f"did not name the uncovered PR: {out}"
        return None

    def release_shaped_pr_before_tag_is_covered() -> str | None:
        """Only the tagged commit is exempt, not every release-shaped subject.

        `chore(release): 0.8.7 publish metadata (#6)` is ordinary work that
        happens to look like a bump; dropping it during parsing hid #6 from
        coverage even though the tag points at a different commit.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            _commit(root, "chore(release): 0.8.7 publish metadata (#6)")
            _commit(root, "release: bump to v1.0.0")
            _git(root, "tag", "v1.0.0")
            (root / "CHANGELOG.md").write_text(
                HEADER + "## v1.0.0 (2026-01-01)\n\n### Chores\n\n- notes\n",
                encoding="utf-8",
            )
            code, out = _run(root, "--check")
            if code != 1:
                return f"release-shaped PR expected 1, got {code}: {out}"
            if "#6" not in out:
                return f"did not name the uncovered PR: {out}"
        return None

    def prose_mention_does_not_count_as_entry() -> str | None:
        """Only a bullet's trailing ref is its own; section prose is not coverage.

        Scanning the whole section for `(#N)` let a sentence mentioning another
        PR stand in for that PR's missing entry.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            _commit(root, "feat(api): real change (#1)")
            _commit(root, "fix(api): other change (#2)")
            _commit(root, "release: bump to v1.0.0")
            _git(root, "tag", "v1.0.0")
            (root / "CHANGELOG.md").write_text(
                HEADER + "## v1.0.0 (2026-01-01)\n\n### Features\n\n"
                "- **api**: real change (#1)\n\n"
                "This supersedes the work in (#2).\n",
                encoding="utf-8",
            )
            code, out = _run(root, "--check")
            if code != 1:
                return f"prose mention expected 1, got {code}: {out}"
            if "#2" not in out:
                return f"prose mention satisfied coverage for #2: {out}"
            if "#1" in out:
                return f"reported the bullet's own PR: {out}"
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

    def release_bump_is_not_a_changelog_entry() -> str | None:
        """The bump commit describes the section it writes; it is not an entry.

        A regeneration after the bump (the #320 ordering mistake) used to file
        `release: bump to vX` under Chores.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            _commit(root, "fix(api): real change (#9)")
            (root / "plugin.yaml").write_text(
                "name: demo\nversion: 1.0.1\n", encoding="utf-8"
            )
            _commit(root, "release: bump to v1.0.1 with changelog section")
            code, out = _run(root, "--upcoming")
            if code != 0:
                return f"--upcoming expected 0, got {code}: {out}"
            text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
            if "release: bump" in text:
                return f"the release commit leaked into the section:\n{text}"
            if "real change" not in text:
                return f"the real change is missing:\n{text}"
        return None

    def upcoming_never_stamps_local_date() -> str | None:
        """The generator must not call date.today() (local-day stamp)."""
        src = TOOL.read_text(encoding="utf-8")
        if "date.today(" in src:
            return "gen_changelog.py still calls date.today()"
        return None

    return [
        ("--upcoming then --check is clean", check_clean_after_upcoming),
        ("a BOM-prefixed subject keeps its type", bom_prefixed_subject_keeps_its_type),
        ("--upcoming transcodes a legacy log encoding", log_encoding_overrides_configured_output),
        ("--check fails on a tag with no section", check_fails_on_missing_section),
        ("--check fails on an untagged plugin.yaml version", check_fails_on_untagged_version),
        ("--check fails on a PR missing from its release section", check_fails_on_missing_entry),
        ("the tag's own release commit needs no entry", release_commit_needs_no_entry),
        ("pre-cutoff releases are exempt from entry coverage", pre_cutoff_tags_are_exempt),
        ("coverage ranges follow version, not tag date", coverage_ranges_follow_version_not_tag_date),
        ("a shallow clone fails closed", shallow_checkout_fails_closed),
        ("a non-conventional squash commit is covered", nonconventional_squash_commit_is_covered),
        ("release-shaped non-tag commits are covered", release_shaped_pr_before_tag_is_covered),
        ("a prose mention is not an entry", prose_mention_does_not_count_as_entry),
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
        ("the release bump is not a changelog entry", release_bump_is_not_a_changelog_entry),
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
