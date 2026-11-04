#!/usr/bin/env python3
"""Release-tag protection gate for PR-time (action bot).

Fail-closed rule for cutting a ``v<plugin.yaml version>`` tag. Refuses the
bump/repin when:

  1. the proposed version is ALREADY a tag (a duplicate release — exact
     ``v<major.minor.patch>`` spelled the same way); or
  2. the proposed version is NOT strictly newer than the latest stable tag
     (a "gap" release, e.g. bumping v0.9.1 -> v0.9.3 while v0.9.2 was skipped),
     which drags the CHANGELOG out of sync.
  3. an ACTIVE release exists — a stable tag created within the last
     ``--window-hours`` (default 48h).

Return codes (hermetic, stdlib-only, no network):

  0 — safe to bump/repin: no duplicate, no gap, no active release.
  1 — refuse: a duplicate release, a version gap, or active release.
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
import sys
from release_gate_shared import (
    REPO,
    PLUGIN_YAML,
    plugin_version,
    duplicate_version,
    version_gap,
    active_release,
    get_latest_stable_tag,
    get_latest_tag,
    _git_tags,
    print_ok,
    print_latest,
)

import unittest.mock


def check_release_tag_gate(version: str | None, window_hours: int = 48) -> tuple[int, list[str]]:
    """Return (exit_code, list_of_evidence_lines)."""
    errors: list[str] = []
    if version is None:
        # Standalone run (no --version): read version from plugin.yaml
        try:
            version = plugin_version()
        except ValueError as exc:
            return 2, [str(exc)]
        print(f"[release-tag-gate] proposed version from plugin.yaml: v{version}")

    latest_stable = get_latest_stable_tag()
    latest_any = get_latest_tag()

    # 1) Duplicate check
    dup, det = duplicate_version(version)
    if dup:
        errors.append(det)

    # 2) Gap check (against latest tag of any kind)
    gap, det = version_gap(version, get_latest_tag())
    if gap:
        errors.append(det)

    # 3) Active release check (stable tags only)
    if latest_stable:
        act, det = active_release(latest_stable, 48)
        if act:
            errors.append(det)

    # Output
    print_latest(get_latest_tag())
    for line in errors:
        print(f"[release-tag-gate] REFUSE: {line}")
    if errors:
        return 1, errors

    print_ok(version)
    return 0, []


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Release-tag protection gate.")
    parser.add_argument(
        "--version",
        default=None,
        help="the version the bump proposes (default: read plugin.yaml)",
    )
    parser.add_argument(
        "--window-hours",
        type=int,
        default=48,
        help="Hours to consider a release 'active' (default 48).",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="run deterministic unit cases and exit",
    )
    return parser.parse_args()


def _selftest() -> int:
    import unittest.mock as mock

    bad = 0

    # --- pure functions ---
    from release_gate_shared import parse_version

    if parse_version("0.9.2") != (0, 9, 2):
        print("FAIL: parse_version('0.9.2')")
        return 1
    if parse_version("0.9.3-rc.1") != (0, 9, 3):
        print("FAIL: parse_version('0.9.3-rc.1')")
        return 1
    if parse_version("not.version") is not None:
        return 1

    # --- mocked end-to-end ---
    import release_gate_shared as rg

    def fake_run(*args):
        ref = next((str(a) for a in args if "refs/tags/" in str(a)), "")
        suffix = ref.split("/")[-1]
        return (0, "exists") if suffix == "v0.9.2" else (1, "missing")

    with unittest.mock.patch.object(rg, "_git_tags", return_value=["v0.9.2"]):
        with unittest.mock.patch.object(rg, "_run", side_effect=fake_run):
            # clean bump
            code1 = check_release_tag_gate("0.9.3", window_hours=0)
            code2 = check_release_tag_gate("0.9.2", window_hours=0)
            if code1[0] != 0:
                print(f"FAIL: clean bump returned {code1}")
                return 1
            if code2[0] != 1:
                print(f"FAIL: duplicate returned {code2}")
                return 1

    print("selftest PASS")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Release-tag protection gate.")
    parser.add_argument("--version", default=None, help="the version the bump proposes")
    parser.add_argument("--window-hours", type=int, default=48, help="active window")
    parser.add_argument("--selftest", action="store_true", help="run unit cases")
    args = parser.parse_args(argv)

    if args.selftest:
        return _selftest()

    code, evidence = check_release_tag_gate(args.version, args.window_hours)
    if code != 0 and evidence:
        print("FAIL: release-tag gate blocked the bump")
        for line in evidence:
            print(f"  - {line}")
    return code


if __name__ == "__main__":
    import argparse
    raise SystemExit(main())