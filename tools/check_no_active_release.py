#!/usr/bin/env python3
"""Release-guard for the action bot: refuse a version bump when a release is
already active or the proposed version is a redundant (already-tagged) release.

Stdlib-only git base, plus a best-effort read-only ``gh release view``
lookup. Runs before bumping the plugin version or re-pointing a tag, so a
bump/repin can be refused if:

  1. an ACTIVE release exists — a release still in flight; or
  2. the proposed version is already a git tag (a REDUNDANT release).

"Still in flight" is: the newest tag is recent (within ``--window-hours``,
default 48h) AND its release has not been confirmed published. Tag age alone
is a blunt proxy — a release stays "recent" for the whole window after it is
fully published, so age alone would refuse every follow-up bump inside it.
When ``gh`` confirms the release is published the tag is not in flight
regardless of age. When ``gh`` is unavailable or cannot confirm, the guard
falls back to the age-only refusal (fail closed, never open). The ``gh``
lookup can only ever *clear* an active flag it can prove, never raise one:
it never widens the allow path beyond what it can verify.

Verdict contract (like ``check_release_readiness.py``): exit 0 = safe to bump;
exit 1 = refuse the bump/repin, with machine-readable evidence on stdout.
A guard that cannot read tag dates fails closed (exit 1), never open.

Note: a ``## vX.Y.Z`` section in CHANGELOG.md is deliberately NOT a refusal
signal. The version-bump PR is required to add that section before merge, so
treating it as "already released" would refuse every valid bump.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CHANGELOG = REPO / "CHANGELOG.md"

DEFAULT_WINDOW_HOURS = 48


def _run_git(*args: str) -> tuple[int, str]:
    """Run a git command. Returns (returncode, stdout).

    A missing git binary or a hung process must not crash the guard with a
    traceback, so both are turned into a non-zero code with the cause on
    stderr; the caller then fails closed.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO)] + list(args),
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"git {' '.join(args)} could not run: {exc}", file=sys.stderr)
        return 1, ""
    return proc.returncode, proc.stdout.strip()


def get_sorted_tags() -> list[str]:
    """Return git tags sorted by semantic version (newest first)."""
    code, out = _run_git("tag", "-l", "--sort=-version:refname")
    if code != 0:
        return []
    return [t for t in out.splitlines() if t.strip()]


def get_tag_dates() -> dict[str, float]:
    """Map tag -> creation date (epoch seconds).

    ``%(creatordate:unix)`` is the tagger date for annotated tags and the commit
    date for lightweight tags — closer to "when was this release cut" than
    ``%ct`` alone, which is always the commit date and misses a freshly pushed
    tag that points at an older commit.

    One ``for-each-ref`` call, not one ``git show`` per tag, so a large tag list
    does not multiply subprocesses. A tag whose date cannot be read is omitted;
    the caller fails closed when no dates remain.
    """
    code, out = _run_git(
        "for-each-ref",
        "--format=%(refname:short)\t%(creatordate:unix)",
        "refs/tags/",
    )
    dates: dict[str, float] = {}
    if code != 0:
        return dates
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        tag, raw = parts[0].strip(), parts[1].strip()
        if not tag:
            continue
        try:
            dates[tag] = float(raw)
        except ValueError:
            continue
    return dates


def get_latest_tag() -> str | None:
    tags = get_sorted_tags()
    return tags[0] if tags else None


def parse_version_tag(tag: str) -> tuple[int, ...] | None:
    """'v0.9.2' -> (0, 9, 2). Returns None for anything else.

    Anchored (``fullmatch``) so a prerelease like ``v0.10.0-rc.1`` does not
    parse as ``(0, 10, 0)`` and masquerade as a duplicate of ``v0.10.0``.
    """
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", tag.strip())
    if not m:
        return None
    return tuple(int(g) for g in m.groups())


def read_changelog_versions() -> list[str]:
    """Return the version strings found in CHANGELOG.md sections, newest first."""
    if not CHANGELOG.exists():
        return []
    text = CHANGELOG.read_text(encoding="utf-8")
    # Match '## vX.Y.Z' headings, newest-first.
    return re.findall(r"^## v?(\d+\.\d+\.\d+)", text, re.MULTILINE)


def _run_gh(*args: str) -> tuple[int, str]:
    """Run a ``gh`` command, returning (returncode, stdout).

    Used read-only (``release view``). Runs with ``cwd=REPO`` so ``gh``
    resolves the same repository whose tags the gate reads — running from an
    arbitrary directory could resolve a different repo's release of the same
    tag name. A missing binary or a timeout must not crash the guard, so both
    become a non-zero code; the caller treats that as "publication unknown"
    and falls back to the age check.
    """
    try:
        proc = subprocess.run(
            ["gh", *args], capture_output=True, text=True, cwd=REPO, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""
    return proc.returncode, proc.stdout


def _release_published(tag: str) -> bool | None:
    """True if `tag` has a published GitHub release, else None.

    One boolean-ish answer covers two distinct "not confirmed" cases, on
    purpose: ``gh release view`` failing (no such release, or ``gh`` itself
    unavailable) cannot distinguish "release not created yet" from "release
    failed" from "no network" — and none of those prove the release is
    finished. So any non-zero result is folded to None, and the caller falls
    back to the age check. A *success* is not enough either: a draft release
    is a successful lookup but is still unpublished. Only an explicitly
    non-draft release with a publication timestamp counts as published.
    """
    code, out = _run_gh(
        "release", "view", tag, "--json", "isDraft,publishedAt"
    )
    if code != 0:
        return None
    try:
        data = json.loads(out)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(data, dict) and data.get("isDraft") is False and data.get("publishedAt"):
        return True
    return None


def check_release_guard(
    proposed_version: str | None = None,
    window_hours: int = DEFAULT_WINDOW_HOURS,
) -> tuple[int, list[str]]:
    """Return (exit_code, list_of_evidence_lines)."""
    evidence: list[str] = []
    exit_code = 0  # safe to bump/repin unless contradicted below

    tags = get_sorted_tags()
    if not tags:
        evidence.append("no git tags found — release guard cannot verify")
        return (1, evidence)

    # 1. Active release check: a tag created within the last N hours.
    #    Fail closed when the dates cannot be read: a guard that cannot see the
    #    release state must not report "safe to bump".
    tag_dates = get_tag_dates()
    if not tag_dates:
        evidence.append(
            "cannot read any tag creation dates — release guard fails closed"
        )
        return (1, evidence)

    latest_tag = max(tag_dates, key=lambda t: tag_dates[t])
    latest_date = tag_dates[latest_tag]
    now = datetime.now(timezone.utc).timestamp()
    age_hours = (now - latest_date) / 3600.0
    if age_hours < window_hours:
        # A recent tag is "in flight" only until its release is confirmed
        # published. A published release is complete regardless of age, so
        # age alone must not refuse the next bump. When publication cannot
        # be confirmed (None), fall back to the age-only refusal.
        if _release_published(latest_tag) is True:
            evidence.append(
                f"NOTE: {latest_tag} is {age_hours:.1f}h old but its "
                f"release is published — not treating as in flight"
            )
        else:
            evidence.append(
                f"ACTIVE RELEASE: latest tag {latest_tag} was created "
                f"{age_hours:.1f}h ago (window {window_hours}h)"
            )
            exit_code = 1

    # 2. Redundant release: the proposed version is already a tag.
    if proposed_version:
        if f"v{proposed_version}" in tags:
            evidence.append(
                f"REDUNDANT RELEASE: proposed version v{proposed_version} "
                f"already tagged"
            )
            exit_code = 1
    else:
        # No version proposed: flag exact-duplicate tags (two tags share the
        # same major.minor.patch) — the only "redundant" case detectable
        # without a proposed version.
        seen: dict[tuple[int, ...], list[str]] = {}
        for tag in tags:
            pv = parse_version_tag(tag)
            if pv is not None:
                seen.setdefault(pv, []).append(tag)
        for pv, tlist in seen.items():
            if len(tlist) > 1:
                evidence.append(
                    f"REDUNDANT RELEASE: duplicate version {pv} tagged "
                    f"({', '.join(sorted(tlist))})"
                )
                exit_code = 1

    return exit_code, evidence


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Release-guard for the action bot: refuse a bump when a "
        "release is active or the proposed version is already tagged."
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Proposed new version, e.g. 0.9.3.",
    )
    parser.add_argument(
        "--window-hours",
        type=int,
        default=DEFAULT_WINDOW_HOURS,
        help=f"Hours to consider a release 'active' (default {DEFAULT_WINDOW_HOURS}).",
    )
    parser.add_argument(
        "--self-test",
        "--selftest",
        dest="self_test",
        action="store_true",
        help="Run internal consistency checks and exit.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.self_test:
        return _self_test()

    if args.version and not re.match(r"^\d+\.\d+\.\d+$", args.version):
        print(
            f"ERROR: --version must be semver (major.minor.patch), got {args.version!r}",
            file=sys.stderr,
        )
        return 2

    exit_code, evidence = check_release_guard(
        proposed_version=args.version,
        window_hours=args.window_hours,
    )
    for line in evidence:
        print(line)
    return exit_code


def _self_test() -> int:
    """Internal consistency checks. Returns 0 if self-test passes."""
    print("self-test: checking read_changelog_versions()...")
    versions = read_changelog_versions()
    if not versions:
        print("self-test: FAIL — no versions found in CHANGELOG.md")
        return 1
    print(f"self-test: OK — found {len(versions)} version(s) in CHANGELOG")

    print("self-test: checking get_sorted_tags()...")
    tags = get_sorted_tags()
    if not tags:
        print("self-test: FAIL — no tags found in git")
        return 1
    print(f"self-test: OK — found {len(tags)} tag(s)")

    print("self-test: checking get_tag_dates()...")
    dates = get_tag_dates()
    if not dates:
        print("self-test: FAIL — could not read any tag creation dates")
        return 1
    print(f"self-test: OK — read creation dates for {len(dates)} tag(s)")

    latest_tag = get_latest_tag()
    if latest_tag and latest_tag in {"v" + v for v in versions}:
        print("self-test: OK — latest tag matches CHANGELOG")
    else:
        print(
            f"self-test: WARN — latest tag {latest_tag} not explicitly in CHANGELOG"
        )

    print("self-test: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())