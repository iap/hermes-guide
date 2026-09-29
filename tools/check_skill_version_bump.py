#!/usr/bin/env python3
"""Fail if a SKILL.md changed but its `version` frontmatter was not bumped.

Compares the current tree against `origin/master` (or the merge base of the
current branch). For every SKILL.md whose content changed, the `version` field
The comparison is ordered, not merely unequal: a version that went DOWN also
fails. A downgrade is as silent as no bump — users who installed the skill
never see the change — and it slipped through review once (1.1.2 -> 1.1.0,
PR #114) because only equality was tested. Ordering is enforced only when
both sides parse as plain `X.Y.Z`; anything else keeps the change-only rule.

Usage:
    python tools/check_skill_version_bump.py            # compare vs origin/master
    python tools/check_skill_version_bump.py <ref>      # compare vs <ref>
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


def _git(args: list[str]) -> str:
    proc = subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return proc.stdout or ""


def _merge_base(ref: str) -> str | None:
    out = _git(["merge-base", "HEAD", ref]).strip()
    return out or None


def _ref_exists(ref: str) -> bool:
    out = _git(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"]).strip()
    return bool(out)


def _semver(value: object) -> tuple[int, int, int] | None:
    """Parse `X.Y.Z` into an ordered tuple; None when not plain semver."""
    if not isinstance(value, str):
        return None
    m = re.match(r"^\s*(\d+)\.(\d+)\.(\d+)\s*$", value)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _changed_files(ref: str) -> list[str]:
    out = _git(["diff", "--name-only", ref, "--"])
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def _frontmatter_at(path: str, ref: str) -> dict | None:
    """Read the YAML frontmatter of `path` as it exists at `ref`, or None."""
    try:
        blob = _git(["show", f"{ref}:{path}"])
    except Exception:
        return None
    if not blob.startswith("---"):
        return None
    parts = blob.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        import yaml

        fm = yaml.safe_load(parts[1])
    except Exception:
        return None
    return fm if isinstance(fm, dict) else None


def _frontmatter_here(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            text = f.read()
    except Exception:
        return None
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        import yaml

        fm = yaml.safe_load(parts[1])
    except Exception:
        return None
    return fm if isinstance(fm, dict) else None


def main(argv: list[str]) -> int:
    ref = argv[1] if len(argv) > 1 else "origin/master"
    # Validate the ref BEFORE computing a base: an unresolvable ref makes the
    # diff below come back empty, which would look like "nothing changed" and
    # turn the guard green while enforcing nothing. Hard-fail instead.
    if not _ref_exists(ref):
        print(
            f"error: ref {ref!r} does not resolve; cannot run the version-bump check. "
            "Ensure full history is fetched (actions/checkout with fetch-depth: 0) "
            "or pass an explicit base ref.",
            file=sys.stderr,
        )
        return 2
    base = _merge_base(ref) if not argv[1:2] else ref
    if not base:
        print(
            f"error: could not resolve merge base against {ref!r}; "
            "cannot run the version-bump check.",
            file=sys.stderr,
        )
        return 2

    changed = _changed_files(base)
    skill_files = [f for f in changed if f.endswith("SKILL.md")]
    if not skill_files:
        print("No SKILL.md files changed; version-bump check skipped.")
        return 0

    failures: list[tuple[str, str]] = []
    for path in skill_files:
        before = _frontmatter_at(path, base)
        after = _frontmatter_here(path)
        if before is None or after is None:
            # New or deleted file — no bump required (new installs get it fresh).
            continue
        before_ver = before.get("version")
        after_ver = after.get("version")
        if before_ver == after_ver:
            failures.append((path, f"version still {before_ver!r}"))
            continue
        before_sem, after_sem = _semver(before_ver), _semver(after_ver)
        if before_sem and after_sem and after_sem < before_sem:
            failures.append((path, f"version went DOWN {before_ver!r} -> {after_ver!r}"))

    if failures:
        print("SKILL.md changed but its `version` was not properly bumped:", file=sys.stderr)
        for path, reason in failures:
            print(f"  {path} ({reason})", file=sys.stderr)
        print("Bump each changed SKILL.md to a version higher than the previous one.", file=sys.stderr)
        return 1

    print(f"OK: {len(skill_files)} SKILL.md change(s) all have a version bump.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
