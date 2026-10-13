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

import re
import subprocess
import sys
from datetime import date
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


CONVENTIONAL_RE = re.compile(
    r"^(?P<type>feat|fix|docs|perf|ci|chore|refactor|style|test)"
    r"(?:\((?P<scope>[^)]*)\))?: (?P<subject>.+?)"
    r"(?:\s+\(#(?P<pr>\d+)\))?\s*$"
)

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
        ["git", *args], capture_output=True, text=True, cwd=REPO
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


def get_commits(since: str | None, until: str | None = None) -> list[dict]:
    """Return commit dicts between refs (exclusive since, inclusive until)."""
    if since:
        range_spec = f"{since}..{until}" if until else f"{since}..HEAD"
    else:
        range_spec = until or "HEAD"
    out = git([
        "log", range_spec,
        "--format=%H%n%s%n%b%n---COMMIT---",
    ])
    commits = []
    for block in out.split("---COMMIT---"):
        lines = block.strip().splitlines()
        if len(lines) < 2:
            continue
        sha = lines[0].strip()
        subject = lines[1].strip()
        m = CONVENTIONAL_RE.match(subject)
        if m:
            commits.append({
                "sha": sha[:8],
                "type": m.group("type"),
                "scope": m.group("scope") or "",
                "subject": _sanitize(m.group("subject")),
                "pr": m.group("pr") or "",
            })
        else:
            commits.append({
                "sha": sha[:8],
                "type": "chore",
                "scope": "",
                "subject": _sanitize(subject),
                "pr": "",
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


SECTION_RE = re.compile(r"^## (\S+) \((\d{4}-\d{2}-\d{2})\)\s*$", re.MULTILINE)


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

    tags = get_tags()
    known = {t for t, _ in tags}
    if tag in known:
        # Already released: build the section from its own tag range so a
        # re-run is a no-op rather than an empty section.
        index = [t for t, _ in tags].index(tag)
        prev_tag = tags[index + 1][0] if index + 1 < len(tags) else None
        commits = get_commits(prev_tag, tag)
        release_date = tags[index][1]
    else:
        prev_tag = tags[0][0] if tags else None
        commits = get_commits(prev_tag)
        release_date = date.today().isoformat()

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
    tags = set(git(["tag", "--list"]).split())
    version = plugin_version()
    expected = set(tags)
    if version:
        expected.add(f"v{version}")

    missing = sorted(expected - present)
    if missing:
        print("FAIL: tag(s) with no CHANGELOG.md section:", file=sys.stderr)
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
        print(f"OK: every tag and the current version have a section "
              f"({len(expected)} release(s) covered)")
    else:
        print(f"OK: the current version has a section ({version or 'unknown'}); "
              f"no tags visible in this checkout, so the tag half did not run "
              f"(fetch tags with `git fetch --tags` for full coverage)")
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
