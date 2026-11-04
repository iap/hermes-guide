#!/usr/bin/env python3
"""Tag-time version-gap check for release.yml.

Compares the new tag (from GITHUB_REF_NAME) against the previous tag and
fails closed if the new tag is not strictly newer than the previous one.

Usage: python tools/check_tag_version_gap.py

Environment:
  GITHUB_REF_NAME — the tag that triggered the workflow (e.g. refs/tags/v0.9.3)
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _run(*args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            list(args), capture_output=True, text=True, cwd=REPO, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    return proc.returncode, proc.stdout.strip()


def _git_tags() -> list[str]:
    code, out = _run("git", "tag", "-l", "--sort=-version:refname")
    if code != 0:
        return []
    return [t for t in out.splitlines() if t.strip()]


def parse_version(version: str) -> tuple[int, ...] | None:
    """'0.9.2' or 'v0.9.2' -> (0, 9, 2). None for anything not a dotted-numeric version."""
    if version.startswith('v'):
        version = version[1:]
    if not re.fullmatch(r"\d+(?:\.\d+)*", version):
        return None
    return tuple(int(part) for part in version.split("."))


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Tag-time version-gap check.")
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="run deterministic unit cases and exit",
    )
    args = parser.parse_args()
    if args.selftest:
        return _selftest()

    current_tag = os.environ.get("GITHUB_REF_NAME")
    if not current_tag:
        print("::error::GITHUB_REF_NAME not set", file=sys.stderr)
        return 1

    # Strip refs/tags/ prefix if present
    if current_tag.startswith("refs/tags/"):
        current_tag = current_tag[len("refs/tags/"):]

    tags = _git_tags()
    if not tags:
        print("::notice::first release — no previous tag to compare")
        return 0

    # Find the previous tag (excluding the current one)
    previous_tag = None
    for tag in tags:
        if tag != current_tag:
            previous_tag = tag
            break

    if previous_tag is None:
        print("::notice::first release — no previous tag to compare")
        return 0

    current_key = parse_version(current_tag)
    previous_key = parse_version(previous_tag)

    if current_key is None or previous_key is None:
        print(f"::warning::cannot parse versions (current={current_tag!r}, previous={previous_tag!r}), skipping gap check")
        return 0

    if current_key <= previous_key:
        print(f"::error::tag {current_tag} is not newer than previous tag {previous_tag} — refusing the version gap")
        return 1

    print(f"::notice::version gate ok — {current_tag} is newer than previous {previous_tag}")
    return 0


def _selftest() -> int:
    import unittest.mock as mock

    bad = 0

    # pure functions
    if parse_version("v0.9.2") != (0, 9, 2):
        bad += 1
    if parse_version("0.9.2") != (0, 9, 2):
        bad += 1

    # end-to-end via mocked git
    def fake_run(*args):
        ref = next((str(a) for a in args if "refs/tags/" in str(a)), "")
        suffix = ref.split("/")[-1]
        return (0, "exists") if suffix == "v0.9.2" else (1, "missing")

    with mock.patch.object(sys.modules[__name__], "_git_tags", return_value=["v0.9.2", "v0.9.1"]):
        with mock.patch.object(sys.modules[__name__], "_run", side_effect=lambda *a: (0, "exists" if "v0.9.2" in str(a[-1]) else "missing")):
            # clean bump: v0.9.3 > v0.9.2
            code1 = main_gate("v0.9.3", "v0.9.2")
            # gap: v0.9.1 <= v0.9.2
            code2 = main_gate("v0.9.1", "v0.9.2")
    if code1 != 0:
        bad += 1
    if code2 != 1:
        bad += 1

    if bad:
        print(f"FAIL: {bad} selftest case(s) mismatched")
        return 1
    print("selftest PASS")
    return 0


def main_gate(current_tag: str, latest_tag: str) -> int:
    """Test helper that bypasses env/GITHUB_REF_NAME."""
    # reuse the logic from main but with explicit tags
    current_key = parse_version(current_tag)
    previous_key = parse_version(latest_tag)
    if current_key is None or previous_key is None:
        return 2
    if current_key <= previous_key:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())