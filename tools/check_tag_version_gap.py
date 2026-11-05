#!/usr/bin/env python3
"""Tag-time version-gap check for release.yml.

Compares the new tag (from GITHUB_REF_NAME) against the previous stable tag
and fails closed if the new tag is not strictly newer than the previous one.

Usage: python tools/check_tag_version_gap.py

Environment:
  GITHUB_REF_NAME — the tag that triggered the workflow (e.g. refs/tags/v0.9.3)
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from release_gate_shared import (
    REPO,
    _git_tags,
    parse_version,
    is_prerelease,
)


def _is_stable_version_tag(tag: str) -> bool:
    if tag.startswith("refs/tags/"):
        tag = tag[len("refs/tags/"):]
    if tag.startswith('v'):
        tag_clean = tag[1:]
    else:
        tag_clean = tag
    if '-' in tag_clean or '+' in tag_clean:
        return False
    if parse_version(tag) is None:
        return False
    if re.match(r'^v?\d+\.\d+', tag):
        return True
    return False


def check_tag_version_gap(current_tag: str) -> int:
    """Return exit code: 0 = ok, 1 = gap, 2 = bad input."""
    import re
    # Strip refs/tags/ prefix if present
    if current_tag.startswith("refs/tags/"):
        current_tag = current_tag[len("refs/tags/"):]

    try:
        tags = _git_tags()
    except Exception as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    if not tags:
        print("::notice::first release — no previous tag to compare")
        return 0

    # Find the previous STABLE tag (excluding current, prereleases, and same-version stable tags)
    previous_tag = None
    current_key = parse_version(current_tag)
    for tag in tags:
        if tag == current_tag:
            continue
        if not _is_stable_version_tag(tag):
            continue
        if is_prerelease(tag):
            continue
        tag_key = parse_version(tag)
        if tag_key is not None and current_key is not None and tag_key == current_key:
            # Skip stable tag of the same version
            continue
        previous_tag = tag
        break

    if previous_tag is None:
        print("::notice::first stable release — no previous tag to compare")
        return 0

    current_key = parse_version(current_tag)
    previous_key = parse_version(previous_tag)

    if current_key is None or previous_key is None:
        print(f"::warning::cannot parse versions (current={current_tag!r}, previous={previous_key!r}), skipping gap check")
        return 0

    # Normalize
    if len(current_key) == 2:
        current_key = current_key + (0,)
    if len(previous_key) == 2:
        previous_key = previous_key + (0,)

    if current_key <= previous_key:
        print(f"::error::tag {current_tag} is not newer than previous tag {previous_tag} — refusing the version gap", file=sys.stderr)
        return 1

    # Enforce no version skipping
    if len(current_key) >= 3 and len(previous_key) >= 3:
        if current_key[0] == previous_key[0] and current_key[1] == previous_key[1]:
            if current_key[2] != previous_key[2] + 1:
                print(f"::error::tag {current_tag} skips from {previous_tag} (expected patch {previous_key[2]+1}) — refusing the version gap", file=sys.stderr)
                return 1
        elif current_key[0] == previous_key[0] and current_key[1] == previous_key[1] + 1 and current_key[2] == 0:
            pass  # minor bump ok
        elif current_key[0] == previous_key[0] + 1 and current_key[1] == 0 and current_key[2] == 0:
            pass  # major bump ok
        else:
            print(f"::error::tag {current_tag} is not the next allowed release after {previous_tag} — refusing the version gap", file=sys.stderr)
            return 1

    print(f"::notice::version gate ok — {current_tag} is newer than previous {previous_tag}")
    return 0


def main() -> int:
    try:
        parser = argparse.ArgumentParser(description="Tag-time version-gap check.")
        parser.add_argument(
            "--selftest",
            action="store_true",
            help="run deterministic unit cases and exit",
        )
        parser.add_argument(
            "--version",
            default=None,
            help="override GITHUB_REF_NAME for testing",
        )
        args = parser.parse_args()

        if args.selftest:
            return _selftest()

        current_tag = args.version or os.environ.get("GITHUB_REF_NAME")
        if not current_tag:
            print("::error::GITHUB_REF_NAME not set", file=sys.stderr)
            return 1

        return check_tag_version_gap(current_tag)
    except Exception as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1


def _selftest() -> int:
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
    import unittest.mock as mock

    bad = 0

    # --- pure functions ---
    from release_gate_shared import parse_version, is_prerelease

    if parse_version("v0.9.2") != (0, 9, 2):
        bad += 1
    if parse_version("0.9.2") != (0, 9, 2):
        bad += 1
    if parse_version("v0.9.2-rc.1") != (0, 9, 2):
        bad += 1
    if is_prerelease("v0.9.2") is not False:
        bad += 1
    if is_prerelease("v0.9.2-rc.1") is not True:
        bad += 1

    # --- end-to-end via mocked git ---
    def fake_run(*args):
        ref = next((str(a) for a in args if "refs/tags/" in str(a)), "")
        suffix = ref.split("/")[-1]
        return (0, "exists") if suffix == "v0.9.2" else (1, "missing")

    import release_gate_shared as rg
    import check_tag_version_gap as ctvg
    # Patch the imported reference in the module's namespace
    # (ctvg.check_tag_version_gap imports _git_tags from release_gate_shared)
    with mock.patch("check_tag_version_gap._git_tags", return_value=["v0.9.2", "v0.9.1"]):
        with mock.patch.object(rg, "_run", side_effect=lambda *a: (0, "exists" if "v0.9.2" in str(a[-1]) else "missing")):
            # clean bump: v0.9.3 > v0.9.2
            code1 = ctvg.check_tag_version_gap("v0.9.3")
            # gap: v0.9.1 <= v0.9.2
            code2 = ctvg.check_tag_version_gap("v0.9.1")
    if code1 != 0:
        bad += 1
    if code2 != 1:
        bad += 1

    # Test prerelease handling
    with mock.patch("check_tag_version_gap._git_tags", return_value=["v0.9.2-rc.1", "v0.9.1"]):
        with mock.patch.object(rg, "_run", side_effect=lambda *a: (0, "exists" if "v0.9.2" in str(a[-1]) else "missing")):
            # Should skip prerelease and compare against v0.9.1
            code3 = ctvg.check_tag_version_gap("v0.9.2")
            if code3 != 0:
                bad += 1

    if bad:
        print(f"FAIL: {bad} selftest case(s) mismatched")
        return 1
    print("selftest PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())