#!/usr/bin/env python3
"""Fail if a doc claims an inventory the repo does not have, or hides one.

Why this exists
---------------
This guard used to pin the *wording* of three files. Regexes matched sentences
like "bundles six SKILL.md files" and "The other eighteen skills", because
hand-maintained counts in prose drift (AGENTS.md once said six when there were
eight) and the maintainers wanted CI to catch it.

That worked, but it also froze the prose: rephrasing a sentence broke the build,
so the documentation could be corrected but never improved. `tools/render_docs.py`
now generates every count-bearing line into a marker-delimited block, and this
guard covers what generation cannot — the three hand-written inventories:

  1. The README skill table lists exactly the skills that ship — no missing row,
     no renamed leftover, no row for a skill that was deleted.
  2. The skill-drift issue template offers one option per shipped skill, and no
     ghost option for a deleted one.
  3. Every `diagnosing-*` skill is reachable from the configuration map's Routing
     section. An unrouted skill is unreachable, and no count catches that.
  4. The AGENTS.md layout table mentions every tracked top-level path and every
     CI workflow. It went stale for six files before this check existed, and a
     structure table that omits a file is worse than no table.

Checks 1-3 are set equality — an extra entry is a ghost that sends readers (and
issue reporters) to something that no longer exists. Check 4 is coverage only:
the layout table deliberately groups and globs (`tools/check_*.py`), so it is
allowed to say more than the file list, but never less.

Counts and scope lists are no longer checked here; render_docs.py owns them.

Run: python tools/test_skill_counts.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Frontmatter `name:` values the README skill table keys on.
_TABLE_ROW = re.compile(r"^\| `([a-z0-9-]+)` \|", re.M)


def section(text: str, heading: str) -> str:
    """The body of `## heading`, up to the next top-level heading."""
    if heading not in text:
        return ""
    return re.split(r"\n## ", text.split(heading, 1)[1], maxsplit=1)[0]


def skill_ids() -> list[str]:
    return sorted(p.parent.name for p in REPO.glob("skills/*/SKILL.md"))


def git_ls_files() -> list[str]:
    """Tracked paths. Raises on failure — an empty inventory must not read as clean."""
    proc = subprocess.run(
        ["git", "-C", str(REPO), "ls-files"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git ls-files failed: {proc.stderr.strip() or proc.returncode}"
        )
    return [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]


def expected_paths(tracked: list[str]) -> list[str]:
    """Tracked paths the AGENTS.md layout table must mention.

    Every top-level entry (a file, or a directory) plus every file under
    `.github/`. Skills and tools children are not enumerated: the table covers
    those with one globbed row each.
    """
    out: set[str] = set()
    for path in tracked:
        out.add(path if path.startswith(".github/") else path.split("/", 1)[0])
    return sorted(out)


def documented_names(layout: str) -> set[str]:
    """Every inline-code span in the layout section — the names the table claims."""
    return set(re.findall(r"`([^`]+)`", layout))


def _uncovered(paths: list[str], layout: str) -> list[str]:
    """Tracked paths the layout table never names.

    A path counts as covered by a mention of its full path, its basename, or any
    ancestor directory. The table is allowed to cover `tools/` with one row rather
    than twenty, and `.github/workflows/label-prs.yml, label-pr-metadata.yml` is
    one row naming two files — but a workflow nothing mentions is still a gap.
    """
    names = documented_names(layout)
    uncovered = []
    for path in paths:
        if path in names or path.rsplit("/", 1)[-1] in names:
            continue
        parts = path.split("/")
        # An ancestor directory token (`tools/`) covers everything beneath it,
        # and a token that descends from `path` (`skills/<name>/SKILL.md`)
        # covers the directory itself.
        if any(f"{'/'.join(parts[: i + 1])}/" in names for i in range(len(parts))):
            continue
        if any(n.startswith(f"{path}/") for n in names):
            continue
        uncovered.append(path)
    return uncovered


def _equality_problems(label: str, expected: set[str], actual: set[str]) -> list[str]:
    problems = []
    missing = sorted(expected - actual)
    ghosts = sorted(actual - expected)
    if missing:
        problems.append(f"{label}: missing " + ", ".join(missing))
    if ghosts:
        problems.append(f"{label}: lists " + ", ".join(ghosts) + " - not shipped")
    return problems


def main() -> int:
    try:
        tracked = git_ls_files()
    except RuntimeError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    if not tracked:
        print(
            "FAIL: git ls-files returned nothing; refusing to report clean",
            file=sys.stderr,
        )
        return 2

    ids = skill_ids()
    if len(ids) < 2:
        print(
            f"FAIL: sanity: found {len(ids)} skills, expected the full library",
            file=sys.stderr,
        )
        return 2

    readme = (REPO / "README.md").read_text(encoding="utf-8")
    agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    expected_ids = set(ids)

    failures: list[str] = []

    # 1. README skill table vs the shipped inventory.
    failures += _equality_problems(
        "README skill table", expected_ids, set(_TABLE_ROW.findall(readme))
    )

    # 2. skill-drift issue template: one option per shipped skill.
    template = (REPO / ".github" / "ISSUE_TEMPLATE" / "skill-drift.yml").read_text(
        encoding="utf-8"
    )
    options = set(re.findall(r"^\s+- ([a-z0-9-]+)$", template, re.M))
    failures += _equality_problems("skill-drift issue template", expected_ids, options)

    # 3. Configuration-map routing: every diagnosing-* skill reachable.
    guide = (REPO / "skills" / "hermes-configuration-guide" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    routing = section(guide, "## Routing")
    if not routing:
        failures.append("configuration map has no `## Routing` section")
    unrouted = [
        i for i in ids if i.startswith("diagnosing-") and f"`{i}`" not in routing
    ]
    if unrouted:
        failures.append("configuration map routing omits: " + ", ".join(unrouted))

    # 4. AGENTS.md layout table: coverage of the tracked tree.
    layout = section(agents, "## Layout")
    if not layout:
        failures.append("AGENTS.md has no `## Layout` section")
    expected = expected_paths(tracked)
    gaps = _uncovered(expected, layout)
    if gaps:
        failures.append("AGENTS.md layout table never mentions: " + ", ".join(gaps))

    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        print(
            "Counts and scope lists are generated - run `python tools/render_docs.py --write`. "
            "The inventory rows themselves are hand-written.",
            file=sys.stderr,
        )
        return 1

    print(
        f"OK: {len(ids)} skills consistent across README table, issue template and "
        f"config-map routing; {len(expected)} tracked paths covered by the "
        f"AGENTS.md layout table"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
