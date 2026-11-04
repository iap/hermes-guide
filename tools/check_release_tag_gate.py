#!/usr/bin/env python3
"""Release-tag protection gate for the action bot.

Fail-closed rule for cutting a ``v<plugin.yaml version>`` tag. Refuses the
bump/repin when:

  1. the proposed version is ALREADY a tag (a duplicate release — exact
     ``v<major.minor.patch>`` spelled the same way); or
  2. the proposed version is NOT strictly newer than the latest tag (a
     "gap" release, e.g. bumping v0.9.1 -> v0.9.3 while v0.9.2 was skipped),
     which drags the CHANGELOG out of sync.

Return codes (hermetic, stdlib-only, no network):

  0 — safe to bump/repin: no duplicate and no gap.
  1 — refuse: a duplicate release or a version gap.
  2 — bad input (malformed version), never 0.

Usage::

    python tools/check_release_tag_gate.py              # approve the bump in
                                                         # plugin.yaml (failed: "no tags yet")
    python tools/check_release_tag_gate.py --version 0.9.3
                                                         # approve the bump in
                                                         # plugin.yaml (ok)
    python tools/check_release_tag_gate.py --version 0.9.2  # refused: duplicate
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGIN_YAML = REPO / "plugin.yaml"


def _run(*args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            list(args), capture_output=True, text=True, cwd=REPO, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    return proc.returncode, proc.stdout.strip()


def _git_tags() -> list[str]:
    """All git tags sorted newest-first."""
    code, out = _run("git", "tag", "-l", "--sort=-version:refname")
    if code != 0:
        return []
    return [t for t in out.splitlines() if t.strip()] if out else []


def plugin_version() -> str:
    """Read the proposed version verbatim from plugin.yaml."""
    text = PLUGIN_YAML.read_text(encoding="utf-8")
    m = re.search(r"^version:\s*(\S+)\s*$", text, re.MULTILINE)
    if not m:
        raise ValueError("plugin.yaml has no version: field")
    return m.group(1)


def parse_version(version: str) -> tuple[int, ...] | None:
    """'0.9.2' or 'v0.9.2' -> (0, 9, 2). None for anything not a dotted-numeric version."""
    if version.startswith('v'):
        version = version[1:]
    if not re.fullmatch(r"\d+(?:\.\d+)*", version):
        return None
    return tuple(int(part) for part in version.split("."))


def duplicate_version(version: str) -> tuple[bool, str]:
    """(is_duplicate, detail). True when the tag v<version> already exists."""
    tag = f"v{version}"
    code, _ = _run("git", "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}")
    if code == 0:
        return True, f"version {tag!r} is already tagged (duplicate release)"
    return False, ""


def version_gap(version: str, latest_tag: str | None) -> tuple[bool, str]:
    """True when the proposal is NOT strictly greater than the latest tag."""
    if latest_tag is None:
        return False, ""
    if parse_version(version) is None or parse_version(latest_tag) is None:
        return False, f"version {version!r} is not dotted-numeric, cannot compare"
    if parse_version(version) <= parse_version(latest_tag):
        return True, (
            f"version {version!r} is not newer than latest tag {latest_tag}, "
            f"a gap release would drag CHANGELOG out of sync"
        )
    return False, ""


def check_release_tag_gate(version: str | None) -> tuple[int, str]:
    """Return (exit_code, evidence). exit 0 = safe to bump; 1 = refuse."""
    errors: list[str] = []
    if version is None:
        # Standalone run (no --version): the bump is proposed by editing
        # plugin.yaml, so read the version from the file.
        try:
            version = plugin_version()
        except ValueError as exc:
            return 2, str(exc)
        print(f"[release-tag-gate] proposed version from plugin.yaml: v{version}")
    try:
        v = parse_version(version)
    except Exception:
        return 2, f"proposed version {version!r} is not dotted-numeric"
    if v is None:
        return 2, f"proposed version {version!r} is not dotted-numeric"

    latest = _git_tags()[0] if _git_tags() else None
    dup, det = duplicate_version(version)
    if dup:
        errors.append(det)
    gap, det = version_gap(version, latest)
    if gap:
        errors.append(det)
    if latest:
        print(f"[release-tag-gate] latest tag on origin/master: {latest}")
    for line in errors:
        print(f"[release-tag-gate] REFUSE: {line}")
    if errors:
        return 1, "\n".join(errors)
    print(f"[release-tag-gate] OK — v{version} is a fresh, untagged version")
    return 0, ""


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Release-tag protection gate.")
    parser.add_argument(
        "--version",
        default=None,
        help="the version the bump proposes (default: read plugin.yaml)",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="run deterministic unit cases and exit",
    )
    return parser.parse_args(argv)


def _selftest() -> int:
    import sys
    import unittest.mock as mock

    bad = 0

    # --- pure functions ---
    r = parse_version("0.9.2") != (0, 9, 2)
    if r:
        bad += 1
    r = parse_version("0.9.3-rc") is not None
    if r:
        bad += 1
    r = parse_version("not.version") is not None
    if r:
        bad += 1
    r = version_gap("0.9.1", "v0.9.2")[0] is not True
    if r:
        bad += 1
    r = version_gap("0.9.3", "v0.9.2")[0] is not False
    if r:
        bad += 1

    # end-to-end via mocked git readers
    def fake_run(*args):
        ref = next((str(a) for a in args if "refs/tags/" in str(a)), "")
        suffix = ref.split("/")[-1]
        return (0, "exists") if suffix == "v0.9.2" else (1, "missing")

    mod = sys.modules[__name__]
    with mock.patch.object(sys.modules[__name__], "_git_tags", return_value=["v0.9.2"]):
        with mock.patch.object(sys.modules[__name__], "_run", side_effect=fake_run):
            code1 = check_release_tag_gate("0.9.3")  # clean bump -> 0
            code2 = check_release_tag_gate("0.9.2")  # duplicate -> 1
    if code1[0] != 0:
        bad += 1
    if code2[0] != 1:
        bad += 1

    if bad:
        print(f"FAIL: {bad} selftest case(s) mismatched")
        return 1
    print("selftest PASS")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.selftest:
        return _selftest()
    code, evidence = check_release_tag_gate(args.version)
    if code != 0 and evidence:
        print("FAIL: release-tag gate blocked the bump")
        for line in evidence.splitlines():
            print(f"  - {line}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
