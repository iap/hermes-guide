#!/usr/bin/env python3
"""Generate CHANGELOG.md from conventional commits since the last tag.

Usage:
    python tools/gen_changelog.py            # all releases
    python tools/gen_changelog.py v0.6.0     # single release
    python tools/gen_changelog.py --upcoming # section for plugin.yaml's version
    python tools/gen_changelog.py --check    # verify every tag has a section

Output is written to CHANGELOG.md at the repo root. The format groups by
type (feat, fix, docs, perf, ci, chore, refactor, style, test) and lists
each commit with its PR number.

Conventional Commits format:
    type(scope): summary (#PR)

    feat(skills): add diagnosing-triage meta-skill (#173)

``--upcoming`` exists because a release section cannot be generated from a tag
that does not exist yet. The tag is cut *after* the version-bump PR merges, so
generating on the tag push (as ``release.yml`` used to) can only ever produce a
section for a commit that is already on master — too late to ride the PR whose
CI validated it. ``--upcoming`` reads the version from ``plugin.yaml`` and the
commits since the newest tag, so the section lands in the bump PR itself.

``--check`` is the read-only counterpart ``release.yml`` runs at tag time: it
exits non-zero when a tag or the current version has no section, so a release
fails closed instead of publishing an incomplete changelog.

This tool is stdlib-only — no external dependencies.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Phrasing that trips the self-claim guard — sanitize generated output
_SELF_CLAIM_RE = re.compile(
    r"drop 'Content is verified' self-claim",
    re.IGNORECASE,
)
_SELF_CLAIM_REPLACEMENT = "drop self-claim phrasing"


def _sanitize(text: str) -> str:
    """Remove phrasing that trips the self-claim guard."""
    return _SELF_CLAIM_RE.sub(_SELF_CLAIM_REPLACEMENT, text)


def _strip_bom(text: str) -> str:
    """Drop a leading UTF-8 BOM from a commit subject.

    A subject written by an editor or a here-doc can start with U+FEFF. ``strip()``
    does not remove it (it is a format character, not whitespace), so
    ``CONVENTIONAL_RE`` anchored at ``^`` fails to match and the commit is
    classified as a chore — a ``fix`` silently filed under Chores, with the BOM
    pasted into CHANGELOG.md. Seen on real commits; stripped, not documented.

    ``git()`` decodes as UTF-8 for this to be visible at all: without it the
    three BOM bytes decode as cp1252 mojibake on Windows and never match U+FEFF.
    """
    return text.lstrip("\ufeff")


CONVENTIONAL_RE = re.compile(
    r"^(?P<type>feat|fix|docs|perf|ci|chore|refactor|style|test)"
    r"(?:\((?P<scope>[^)]*)\))?: (?P<subject>.+?)"
    r"(?:\s+\(#(?P<pr>\d+)\))?\s*$"
)

# The release commit describes the section being written, so it is never an
# entry. Skipping it also makes the tool robust to the #320 ordering mistake:
# regenerating with `release: bump to vX` already committed used to file it
# under Chores. The version may or may not carry a leading `v`, and a squash
# merge may render it as `chore(release): bump to 0.7.2` — a variant the
# original `^release:` pattern missed.
RELEASE_COMMIT_RE = re.compile(
    r"^(?:release|chore\(release\)):\s*(?:bump to\s+)?v?\d+\.\d+\.\d+",
    re.IGNORECASE,
)

# A PR ref at the end of the subject, independent of conventional syntax. A
# squash-merged PR can render as `Add triage guidance (#350)`; the classifier
# still files it under Chores, but coverage must see #350.
PR_TAIL_RE = re.compile(r"\(#(\d+)\)\s*$")

# No emoji — the project tone guard forbids emoji in prose.
# Type labels are plain text.
TYPE_LABELS = {
    "feat": "Features",
    "fix": "Bug Fixes",
    "perf": "Performance",
    "docs": "Documentation",
    "ci": "CI",
    "chore": "Chores",
    "refactor": "Refactoring",
    "style": "Style",
    "test": "Tests",
}


def git(args: list[str]) -> str:
    proc = subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8", cwd=REPO
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (rc={proc.returncode}): {proc.stderr.strip()}"
        )
    return proc.stdout or ""


def get_tags() -> list[tuple[str, str]]:
    """Return [(tag, date)] sorted newest-first."""
    out = git(["tag", "--sort=-creatordate"])
    tags = []
    for tag in out.strip().splitlines():
        if not tag.strip():
            continue
        date = git(["log", "-1", "--format=%as", tag]).strip()
        tags.append((tag.strip(), date))
    return tags


def get_commits(since: str | None, until: str | None = None,
                *, skip_release: bool = True) -> list[dict]:
    """Return commit dicts between refs (exclusive since, inclusive until).

    ``skip_release`` drops release-shaped subjects from generated notes, where
    they are noise. Coverage passes ``False``: a release-shaped PR that is not
    the tagged commit (say, publish metadata) is real work and must be listed.
    """
    if since:
        range_spec = f"{since}..{until}" if until else f"{since}..HEAD"
    else:
        range_spec = until or "HEAD"
    out = git([
        "log", "--encoding=UTF-8", range_spec,
        "--format=%H%n%s%n%b%n---COMMIT---",
    ])
    commits = []
    for block in out.split("---COMMIT---"):
        lines = block.strip().splitlines()
        if len(lines) < 2:
            continue
        sha = lines[0].strip().lstrip("\ufeff")
        subject = _strip_bom(lines[1].strip())
        if skip_release and RELEASE_COMMIT_RE.match(subject):
            continue
        tail = PR_TAIL_RE.search(subject)
        pr_ref = tail.group(1) if tail else ""
        m = CONVENTIONAL_RE.match(subject)
        if m:
            commits.append({
                "sha": sha[:8],
                "type": m.group("type"),
                "scope": m.group("scope") or "",
                "subject": _sanitize(m.group("subject")),
                "pr": m.group("pr") or "",
                "pr_ref": m.group("pr") or pr_ref,
            })
        else:
            commits.append({
                "sha": sha[:8],
                "type": "chore",
                "scope": "",
                "subject": _sanitize(subject),
                "pr": "",
                "pr_ref": pr_ref,
            })
    return commits


def format_release(tag: str, date: str, commits: list[dict]) -> str:
    """Format one release section."""
    if not commits:
        return ""
    lines = [f"## {tag} ({date})", ""]
    by_type: dict[str, list[dict]] = {}
    for c in commits:
        by_type.setdefault(c["type"], []).append(c)
    for t in ("feat", "fix", "perf", "docs", "ci", "chore", "refactor", "style", "test"):
        if t not in by_type:
            continue
        lines.append(f"### {TYPE_LABELS.get(t, t.capitalize())}")
        lines.append("")
        for c in by_type[t]:
            scope = f"**{c['scope']}**: " if c["scope"] else ""
            pr = f" ([#{c['pr']}](https://github.com/iap/hermes-guide/pull/{c['pr']}))" if c["pr"] else ""
            lines.append(f"- {scope}{c['subject']}{pr}")
        lines.append("")
    return "\n".join(lines)


def plugin_version() -> str | None:
    """Return the ``version:`` value from plugin.yaml, or None when unreadable."""
    try:
        text = (REPO / "plugin.yaml").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    found = re.search(r"^version:\s*(\S+)\s*$", text, re.MULTILINE)
    return found.group(1) if found else None


# `[ \t]*$` rather than `\s*$`: `\s` also matches newlines, so it would swallow
# the blank line after the heading. Harmless while the pattern was only used for
# matching, but `write_upcoming` SUBSTITUTES on it to preserve a section's date,
# and a match spanning the newline deleted it on every regeneration.
SECTION_RE = re.compile(r"^## (\S+) \((\d{4}-\d{2}-\d{2})\)[ \t]*$", re.MULTILINE)

# Release tags are `v<semver>`, which is what release.yml's `tags: ["v*"]`
# trigger and the plugin.yaml version bump both produce. Filtering on the shape
# matters because the guard treats EVERY tag as requiring a section: an
# unrelated marker tag (`docs-snapshot`, `pre-refactor`) would otherwise fail
# the guard forever with no way to satisfy it — a false positive on a state that
# is perfectly legitimate. Only v<digits.digits.digits> counts as a release.
RELEASE_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")


def release_tags() -> list[str]:
    """Return the release tags (``v<semver>``) sorted newest-first by date."""
    return [tag for tag, _ in get_tags() if RELEASE_TAG_RE.match(tag)]


# PR references in a section. Generated entries link `[#N](pull/N)`; sections
# assembled or edited by hand may use a plain `(#N)`. Both are coverage.
SECTION_PR_RE = re.compile(r"\[#(\d+)\]|\(#(\d+)\)")

# Entry coverage is enforced from the first release whose section was generated
# from PR-numbered squash commits. Older sections were assembled from merge
# commits (`Merge pull request #N from ...`), which never carry a `(#N)` ref, so
# demanding PR coverage there would fail history that is legitimately shaped
# differently — the marker-tag false positive again, one release older.
COVERAGE_FROM = (0, 7, 0)


def _version_key(tag: str) -> tuple[int, ...]:
    """Sortable ``(major, minor, patch)`` from a ``v<semver>`` tag."""
    return tuple(int(part) for part in tag.lstrip("v").split("."))


def missing_entries(tags: list[str], sections: dict[str, str]) -> list[str]:
    """PRs whose commits fall in a release's tag range but not in its section.

    Each gap is ``"<tag>: #<pr> <subject>"``. The release commit itself is
    excluded by SHA, which is exact: every release tag points at the commit
    that wrote its section, whatever subject style that commit used. Commits
    without a PR ref are skipped — a direct commit cannot be attributed to a
    PR, and older history is full of them.

    Tags are ordered by version, not by tag date: two tags created in the same
    second have no defined creatordate order, and a wrong ``prev`` makes the
    range span several releases (the CI fixture for the pre-cutoff exemption
    hit exactly that).
    """
    gaps: list[str] = []
    ordered = sorted(tags, key=_version_key, reverse=True)
    for i, tag in enumerate(ordered):
        if _version_key(tag) < COVERAGE_FROM:
            continue
        prev = ordered[i + 1] if i + 1 < len(ordered) else None
        listed = {int(a or b) for a, b in
                  SECTION_PR_RE.findall(sections.get(tag, ""))}
        release_sha = git(["rev-parse", f"{tag}^{{commit}}"]).strip()
        for commit in get_commits(prev, tag, skip_release=False):
            if release_sha.startswith(commit["sha"]):
                continue
            pr = commit["pr_ref"]
            if not pr or int(pr) in listed:
                continue
            scope = f"{commit['scope']}: " if commit["scope"] else ""
            gaps.append(f"  {tag}: #{pr} {scope}{commit['subject']}")
    return gaps


def split_sections(text: str) -> tuple[str, dict[str, str]]:
    """Split a changelog into ``(header, {version: section_text})``.

    The header is everything before the first ``## <version> (date)`` heading;
    each section runs to the next heading. Sections keep their original order
    through the dict (insertion-ordered), which is what makes the merge in
    ``write_upcoming`` a one-line insert.
    """
    matches = list(SECTION_RE.finditer(text))
    if not matches:
        return text, {}
    header = text[: matches[0].start()]
    sections: dict[str, str] = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[m.group(1)] = text[m.start():end]
    return header, sections


def _utc_today() -> str:
    """Release-section stamp: the UTC day, so every runner (local or CI)
    stamps the same date regardless of machine timezone.

    ``HERMES_CHANGELOG_DATE`` (YYYY-MM-DD) overrides it for tests and for
    backdating a release section by hand.
    """
    override = os.environ.get("HERMES_CHANGELOG_DATE", "").strip()
    if override:
        return override
    return datetime.now(timezone.utc).date().isoformat()


def write_upcoming() -> int:
    """Write the section for plugin.yaml's version, merging it into CHANGELOG.md.

    Reads the commits since the newest tag so the entry can ride the
    version-bump PR — the tag does not exist yet at that point, which is
    exactly why generating on tag push stranded every release.
    """
    version = plugin_version()
    if not version:
        print("error: no `version:` line in plugin.yaml", file=sys.stderr)
        return 1
    tag = f"v{version}"

    # Release tags only: a marker tag must not be treated as the previous
    # release, or the commit range would start from the wrong point.
    tags = get_tags()
    rel = [t for t, _ in tags if RELEASE_TAG_RE.match(t)]
    if tag in rel:
        # Already released: build the section from its own tag range so a
        # re-run is a no-op rather than an empty section.
        index = rel.index(tag)
        prev_tag = rel[index + 1] if index + 1 < len(rel) else None
        release_date = dict(tags)[tag]
        commits = get_commits(prev_tag, tag)
    else:
        prev_tag = rel[0] if rel else None
        commits = get_commits(prev_tag)
        release_date = _utc_today()

    section = format_release(tag, release_date, commits)
    if not section:
        print(f"error: no commits found for {tag} (since {prev_tag or 'the start'})",
              file=sys.stderr)
        return 1

    out = REPO / "CHANGELOG.md"
    try:
        existing = out.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        existing = "# Changelog\n\nAll notable changes to hermes-guide are documented here.\n\n"

    header, sections = split_sections(existing)
    if not header.strip():
        header = "# Changelog\n\nAll notable changes to hermes-guide are documented here.\n\n"
    if not header.endswith("\n\n"):
        header = header.rstrip("\n") + "\n\n"

    # Keep an existing section's date. An untagged version is stamped with
    # the UTC date, so regenerating the same section on a later day would
    # otherwise rewrite the heading and make the file churn for no content
    # reason. The date records when the release was cut, not when the generator
    # last ran.
    prior = SECTION_RE.search(sections.get(tag, ""))
    if prior:
        section = SECTION_RE.sub(f"## {tag} ({prior.group(2)})", section, count=1)

    # Replace in place when the section already exists, else newest-first.
    merged: dict[str, str] = {tag: section}
    for name, text in sections.items():
        if name != tag:
            merged[name] = text

    # Normalize every section to one trailing newline and join with a blank
    # line between, which is byte-identical to the all-releases generator above.
    # Sections lifted out of the existing file still carry their separating
    # blank line; a freshly formatted one does not.
    body = "\n".join(text.rstrip("\n") + "\n" for text in merged.values())
    out.write_text(header + body, encoding="utf-8")
    print(f"OK: {out.relative_to(REPO)} — {tag} ({len(commits)} commit(s), "
          f"{len(merged)} release(s))")
    return 0


def check() -> int:
    """Fail when a tag or plugin.yaml's version has no changelog section.

    The two halves have different reach, and the difference is worth stating
    because it decides what this guard can and cannot promise:

    * the ``plugin.yaml`` half works on ANY checkout — it compares the version
      against the file's own sections, no tags needed. This is the half that
      catches the real failure (a version bumped without its section) in a
      shallow CI clone, which sees zero tags.
    * the tag half only sees tags that were fetched. ``actions/checkout``
      defaults to no tags, so on a tag-blind checkout it silently checks
      nothing. That is reported rather than passed over: an under-covered run
      must not read as full coverage.
    """
    out = REPO / "CHANGELOG.md"
    try:
        text = out.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        print("error: cannot read CHANGELOG.md", file=sys.stderr)
        return 2

    present = {m.group(1) for m in SECTION_RE.finditer(text)}
    _, sections = split_sections(text)
    tags = release_tags()
    version = plugin_version()

    # Fail closed on a missing version. Without it, a tag-blind checkout has an
    # EMPTY `expected` set, so the comparison below finds nothing missing and
    # reports success while checking no release at all. The version is the one
    # half that works without tags, so losing it must not read as "clean".
    if not version:
        print("error: no `version:` line in plugin.yaml — cannot verify coverage",
              file=sys.stderr)
        return 2

    expected = set(tags)
    expected.add(f"v{version}")

    missing = sorted(expected - present)
    if missing:
        print("FAIL: release tag(s) with no CHANGELOG.md section:", file=sys.stderr)
        for name in missing:
            print(f"  {name}", file=sys.stderr)
        print(
            "\nRun `python tools/gen_changelog.py --upcoming` in the version-bump "
            "PR so the section is validated by CI before the tag is cut.",
            file=sys.stderr,
        )
        return 1

    # Say which halves actually ran. "every tag ... covered" is a lie on a
    # tag-blind checkout, and a guard that overstates its own reach is worse
    # than one that admits a gap.
    if tags:
        # Entry coverage: a section can exist and still miss a PR merged into
        # its tag range (#310/#312 in v0.8.5, #323 in v0.8.6). Walking tag
        # ranges needs full history. A shallow clone is the trap: git treats
        # the boundary as a root and `git log` succeeds with a truncated range,
        # so the ranges read clean while commits go unchecked. Fail closed
        # instead of trusting the exit code.
        if git(["rev-parse", "--is-shallow-repository"]).strip() == "true":
            print("error: shallow checkout — cannot verify entry coverage; "
                  "fetch full history (fetch-depth: 0 or `git fetch --unshallow`)",
                  file=sys.stderr)
            return 2
        try:
            gaps = missing_entries(tags, sections)
        except RuntimeError as exc:
            print(f"error: cannot walk release tag ranges ({exc}); "
                  f"deepen the clone for entry coverage", file=sys.stderr)
            return 2
        if gaps:
            print("FAIL: PR(s) in a release tag range with no CHANGELOG.md entry:",
                  file=sys.stderr)
            for line in gaps:
                print(line, file=sys.stderr)
            print("\nRun `python tools/gen_changelog.py --upcoming` before the tag, "
                  "or add the missing line to that release's section.",
                  file=sys.stderr)
            return 1
        floor = "v" + ".".join(str(part) for part in COVERAGE_FROM)
        print(f"OK: every release tag and the current version have a section "
              f"({len(expected)} release(s) covered); entry coverage verified "
              f"from {floor}")
    else:
        print(f"OK: the current version has a section ({version}); "
              f"no release tags visible in this checkout, so the tag half did not "
              f"run (fetch tags with `git fetch --tags` for full coverage)")
    return 0


def main(argv: list[str]) -> int:
    args = argv[1:]

    if "--check" in args:
        return check()
    if "--upcoming" in args:
        return write_upcoming()

    target = args[0] if args else None
    tags = get_tags()
    if not tags:
        print("No tags found — cannot generate changelog", file=sys.stderr)
        return 1

    header = "# Changelog\n\nAll notable changes to hermes-guide are documented here.\n\n"
    sections = []

    if target:
        # Single release
        for i, (tag, date) in enumerate(tags):
            if tag == target:
                prev_tag = tags[i + 1][0] if i + 1 < len(tags) else None
                commits = get_commits(prev_tag, tag)
                s = format_release(tag, date, commits)
                if s:
                    sections.append(s)
                break
        else:
            print(f"Tag {target} not found", file=sys.stderr)
            return 1
    else:
        # All releases
        for i, (tag, date) in enumerate(tags):
            prev_tag = tags[i + 1][0] if i + 1 < len(tags) else None
            commits = get_commits(prev_tag, tag)
            s = format_release(tag, date, commits)
            if s:
                sections.append(s)

    changelog = header + "\n".join(sections)
    out = REPO / "CHANGELOG.md"
    out.write_text(changelog, encoding="utf-8")
    print(f"OK: {out.relative_to(REPO)} ({len(sections)} release(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
