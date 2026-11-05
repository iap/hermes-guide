#!/usr/bin/env python3
"""Shared utilities for release-tag gates (hermetic, stdlib-only)."""

from __future__ import annotations

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
    """True if latest tag was created within the window."""
    if latest_tag is None:
        return False, ""
    date = _git_tag_date(latest_tag)
    if date is None:
        return True, f"cannot determine creation date of tag {latest_tag} (fail-closed)"
    age_hours = (time.time() - date) / 3600.0
    if age_hours < window_hours:
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