#!/usr/bin/env python3
"""Shared utilities for release-tag gates.

Stdlib-only git base, plus a best-effort read-only ``gh release view``
lookup. "In flight" is: the newest tag is recent (within the window) AND its
release has not been confirmed published. Tag age alone is a blunt proxy that
refuses every follow-up bump inside the window even after the previous
release fully published. When ``gh`` confirms a published release the tag is
not in flight regardless of age; when ``gh`` is unavailable or cannot
confirm, the guard falls back to the age-only refusal (fail closed, never
open). The ``gh`` lookup can only ever *clear* an active flag it can prove,
never raise one.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGIN_YAML = REPO / "plugin.yaml"


def plugin_version() -> str:
    """Read the proposed version verbatim from plugin.yaml."""
    text = PLUGIN_YAML.read_text(encoding="utf-8")
    m = re.search(r"^version:\s*(\S+)\s*$", text, re.MULTILINE)
    if not m:
        raise ValueError("plugin.yaml has no version: field")
    return m.group(1)


def _run(*args: str) -> tuple[int, str]:
    """Run a command, returning (returncode, stdout)."""
    try:
        proc = subprocess.run(
            list(args), capture_output=True, text=True, cwd=REPO, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    return proc.returncode, proc.stdout.strip()


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


def _git_tags() -> list[str]:
    """All git tags sorted newest-first (semantic version order)."""
    # Prefer tags merged into origin/master to avoid unrelated branch tags
    code, out = _run("git", "tag", "-l", "--sort=-version:refname", "--merged", "origin/master")
    if code == 0 and out:
        tags = [t for t in out.splitlines() if t.strip()]
        if tags:
            return tags
    # Fallback to all tags if origin/master not available or has no merged tags
    code, out = _run("git", "tag", "-l", "--sort=-version:refname")
    if code != 0:
        raise RuntimeError(f"git tag -l failed (exit {code}): {out}")
    return [t for t in out.splitlines() if t.strip()] if out else []


def _git_tag_date(tag: str) -> int | None:
    """Return the tagger/creator date (epoch seconds) for a tag."""
    code, out = _run("git", "for-each-ref", f"--format=%(creatordate:unix)", f"refs/tags/{tag}")
    if code == 0 and out:
        try:
            # Might have multiple lines in some cases, take first
            first = out.splitlines()[0].strip()
            if first and first.isdigit():
                return int(first)
        except ValueError:
            pass
    # Fallback to commit date
    code, out = _run("git", "log", "-1", "--format=%ct", tag)
    if code == 0 and out:
        try:
            first = out.splitlines()[0].strip()
            if first and first.isdigit():
                return int(first)
        except ValueError:
            pass
    return None


def parse_version(version: str) -> tuple[int, ...] | None:
    """'0.9.2' or 'v0.9.2' -> (0, 9, 2). None for non-dotted-numeric versions.

    Pre-release suffixes (e.g. '-rc.1', '-beta') are stripped so that
    '0.10.0-rc.1' -> (0, 10, 0) for ordering purposes.
    """
    if version.startswith('v'):
        version = version[1:]
    # Strip pre-release suffix for comparison
    version = re.sub(r'[-+].*$', '', version)
    if not re.fullmatch(r"\d+(?:\.\d+)*", version):
        return None
    return tuple(int(part) for part in version.split("."))


def is_prerelease(version: str) -> bool:
    """Return True if version has a pre-release suffix."""
    if version.startswith('v'):
        version = version[1:]
    return '-' in version or '+' in version


def duplicate_version(version: str) -> tuple[bool, str]:
    """(is_duplicate, detail). True when the tag v<version> already exists."""
    tag = f"v{version}"
    code, _ = _run("git", "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}")
    if code == 0:
        return True, f"version {tag!r} is already tagged (duplicate release)"
    return False, ""


def version_gap(version: str, latest_tag: str | None) -> tuple[bool, str]:
    """True when the proposal is NOT strictly greater than the latest tag or skips a version."""
    if latest_tag is None:
        return False, ""
    pv = parse_version(version)
    lt = parse_version(latest_tag)
    if pv is None or lt is None:
        return False, f"version {version!r} is not dotted-numeric, cannot compare"
    # Normalize to 3 components
    if len(pv) == 2:
        pv = pv + (0,)
    if len(lt) == 2:
        lt = lt + (0,)
    if pv <= lt:
        return True, (
            f"version {version!r} is not newer than latest tag {latest_tag}, "
            f"a gap release would drag CHANGELOG out of sync"
        )
    # Enforce no version skipping - must be exactly next version
    if len(pv) >= 3 and len(lt) >= 3:
        # If same major.minor, patch must increment by exactly 1
        if pv[0] == lt[0] and pv[1] == lt[1]:
            if pv[2] != lt[2] + 1:
                return True, (
                    f"version {version!r} skips from {latest_tag} (expected patch {lt[2]+1}), "
                    f"a gap release would drag CHANGELOG out of sync"
                )
            return False, ""
        # If major same but minor bumped, patch must be 0 and minor must be previous_minor + 1
        if pv[0] == lt[0] and pv[1] == lt[1] + 1 and pv[2] == 0:
            return False, ""
        # If major bumped, minor and patch must be 0
        if pv[0] == lt[0] + 1 and pv[1] == 0 and pv[2] == 0:
            return False, ""
        # Other transitions - also check if it's jumping over something
        # More generally, if it's a patch-level bump relative to latest, must be +1
        # If changing minor/major, must be exactly +1 at that level
        return True, (
            f"version {version!r} is not the next allowed release after {latest_tag}, "
            f"a gap release would drag CHANGELOG out of sync"
        )
    return False, ""


def active_release(latest_tag: str | None, window_hours: int) -> tuple[bool, str]:
    """True if a release is still in flight.

    In flight = the tag is recent (within the window) AND its release has not
    been confirmed published via ``gh release view``. A confirmed-published
    release is complete regardless of age, so age alone must not refuse the
    next bump. When publication cannot be confirmed (None), fall back to the
    age-only refusal (fail closed, never open).
    """
    if latest_tag is None:
        return False, ""
    date = _git_tag_date(latest_tag)
    if date is None:
        return True, f"cannot determine creation date of tag {latest_tag} (fail-closed)"
    age_hours = (time.time() - date) / 3600.0
    if age_hours < window_hours:
        if _release_published(latest_tag) is True:
            return False, (
                f"NOTE: {latest_tag} is {age_hours:.1f}h old but its release "
                f"is published — not treating as in flight"
            )
        return True, (
            f"ACTIVE RELEASE: latest tag {latest_tag} was created "
            f"{age_hours:.1f}h ago (window {window_hours}h)"
        )
    return False, ""


def _is_stable_version_tag(tag: str) -> bool:
    """Return True only for tags that parse as stable version tags (no prerelease)."""
    if tag.startswith('v'):
        tag_clean = tag[1:]
    else:
        tag_clean = tag
    # Must not be prerelease
    if '-' in tag_clean or '+' in tag_clean:
        return False
    # Must parse as dotted numeric version
    if parse_version(tag) is None:
        return False
    # Also ensure it's a version-like tag (starts with digit after optional v)
    if re.match(r'^v?\d+\.\d+', tag):
        return True
    return False


def get_latest_stable_tag() -> str | None:
    """Return the latest non-prerelease version tag, or None."""
    for tag in _git_tags():
        if _is_stable_version_tag(tag) and not is_prerelease(tag):
            return tag
    return None


def get_latest_tag() -> str | None:
    """Return the absolute latest tag (including prereleases)."""
    tags = _git_tags()
    return tags[0] if tags else None


def report_evidence(errors: list[str], label: str = "release-tag-gate") -> None:
    """Print all evidence lines with consistent formatting."""
    for line in errors:
        print(f"[{label}] REFUSE: {line}")


def print_ok(version: str, label: str = "release-tag-gate") -> None:
    print(f"[{label}] OK — v{version} is a fresh, untagged version")


def print_latest(latest: str | None, label: str = "release-tag-gate") -> None:
    if latest:
        print(f"[{label}] latest tag on origin/master: {latest}")


if __name__ == "__main__":
    # Quick self-test
    assert parse_version("0.9.2") == (0, 9, 2)
    assert parse_version("v0.9.2") == (0, 9, 2)
    assert parse_version("0.9.3-rc.1") == (0, 9, 3)
    assert parse_version("not.version") is None
    assert is_prerelease("0.9.3-rc.1") is True
    assert is_prerelease("0.9.2") is False
    print("shared utilities self-test PASS")