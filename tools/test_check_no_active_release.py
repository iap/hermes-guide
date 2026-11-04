#!/usr/bin/env python3
"""Behavioral regression test for tools/check_no_active_release.py.

Hermetic: stdlib only, fixtures in tempdirs, no network, no real git repo.
The test imports the guard's pure helpers and exercises the verdict paths by
monkeypatching the git/changelog readers.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load_guard():
    """Import check_no_active_release.py as a module (it lives in tools/)."""
    path = REPO / "tools" / "check_no_active_release.py"
    spec = importlib.util.spec_from_file_location("check_no_active_release", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_parse_version_tag():
    mod = _load_guard()
    assert mod.parse_version_tag("v0.9.2") == (0, 9, 2)
    assert mod.parse_version_tag("0.9.2") == (0, 9, 2)
    assert mod.parse_version_tag("v1.0.0") == (1, 0, 0)
    assert mod.parse_version_tag("not-a-version") is None
    assert mod.parse_version_tag("v1.2") is None
    print("OK: parse_version_tag")


def test_read_changelog_versions(tmp_path):
    mod = _load_guard()
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n## v0.9.2 (2026-11-04)\n\n## v0.9.1 (2026-11-03)\n\n## v0.8.0 (2026-10-01)\n",
        encoding="utf-8",
    )
    old = mod.CHANGELOG
    mod.CHANGELOG = changelog
    try:
        versions = mod.read_changelog_versions()
        assert versions == ["0.9.2", "0.9.1", "0.8.0"], versions
    finally:
        mod.CHANGELOG = old
    print("OK: read_changelog_versions")


def test_check_release_guard_new_version_no_active():
    """New version, no active release, not tagged -> exit 0."""
    mod = _load_guard()
    mod.get_sorted_tags = lambda: ["v0.9.2", "v0.9.1", "v0.9.0"]
    mod.get_tag_dates = lambda: {
        "v0.9.2": 0.0,
        "v0.9.1": 0.0,
        "v0.9.0": 0.0,
    }
    code, evidence = mod.check_release_guard(proposed_version="0.9.3", window_hours=48)
    assert code == 0, evidence
    assert not any("REDUNDANT" in e for e in evidence), evidence
    print("OK: new version, no active release")


def test_check_release_guard_already_tagged():
    """Proposed version already tagged -> exit 1 (redundant release)."""
    mod = _load_guard()
    mod.get_sorted_tags = lambda: ["v0.9.2", "v0.9.1", "v0.9.0"]
    mod.get_tag_dates = lambda: {"v0.9.2": 0.0, "v0.9.1": 0.0, "v0.9.0": 0.0}
    code, evidence = mod.check_release_guard(proposed_version="0.9.2", window_hours=48)
    assert code == 1, evidence
    assert any("REDUNDANT" in e for e in evidence), evidence
    print("OK: already-tagged version refused")


def test_documented_version_is_not_refused(tmp_path):
    """A CHANGELOG section for the proposed version is REQUIRED by the bump PR,
    so it must NOT trigger a redundant-release refusal (Qodo finding 1)."""
    mod = _load_guard()
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "## v0.9.3 (2026-11-05)\n\n## v0.9.2 (2026-11-04)\n", encoding="utf-8"
    )
    old = mod.CHANGELOG
    mod.CHANGELOG = changelog
    try:
        mod.get_sorted_tags = lambda: ["v0.9.2", "v0.9.1"]
        mod.get_tag_dates = lambda: {"v0.9.2": 0.0, "v0.9.1": 0.0}
        code, evidence = mod.check_release_guard(proposed_version="0.9.3", window_hours=48)
        assert code == 0, evidence
        assert not any("DOCUMENTED" in e for e in evidence), evidence
    finally:
        mod.CHANGELOG = old
    print("OK: documented-but-untagged version is allowed")


def test_check_release_guard_active_release():
    """A tag created inside the window -> exit 1 (active release)."""
    mod = _load_guard()
    mod.get_sorted_tags = lambda: ["v0.9.2", "v0.9.1"]
    mod.get_tag_dates = lambda: {
        "v0.9.2": time.time() - 3600,  # one hour ago
        "v0.9.1": 0.0,
    }
    code, evidence = mod.check_release_guard(proposed_version="0.9.3", window_hours=48)
    assert code == 1, evidence
    assert any("ACTIVE RELEASE" in e for e in evidence), evidence
    print("OK: active release refused")


def test_check_release_guard_empty_tags():
    """No tags -> exit 1 (cannot verify)."""
    mod = _load_guard()
    mod.get_sorted_tags = lambda: []
    code, evidence = mod.check_release_guard(window_hours=48)
    assert code == 1, evidence
    assert any("no git tags" in e for e in evidence), evidence
    print("OK: empty tags -> refuse")


def test_check_release_guard_unreadable_dates():
    """Tag dates unreadable -> exit 1, never a silent pass (Qodo finding 5)."""
    mod = _load_guard()
    mod.get_sorted_tags = lambda: ["v0.9.2", "v0.9.1"]
    mod.get_tag_dates = lambda: {}
    code, evidence = mod.check_release_guard(proposed_version="0.9.3", window_hours=48)
    assert code == 1, evidence
    assert any("fails closed" in e for e in evidence), evidence
    print("OK: unreadable tag dates -> fail closed")


def test_get_tag_dates_parses_for_each_ref():
    """get_tag_dates() must read %(creatordate:unix) from one for-each-ref call."""
    mod = _load_guard()
    calls = []

    def fake_run_git(*args):
        calls.append(args)
        if args[0] == "for-each-ref":
            return 0, "v0.9.2\t1700000000\nv0.9.1\t1690000000\n"
        return 1, ""

    old = mod._run_git
    mod._run_git = fake_run_git
    try:
        dates = mod.get_tag_dates()
    finally:
        mod._run_git = old
    assert dates == {"v0.9.2": 1700000000.0, "v0.9.1": 1690000000.0}, dates
    assert any(a[0] == "for-each-ref" for a in calls), calls
    print("OK: get_tag_dates uses for-each-ref")


def test_selftest_alias_accepted():
    """The workflow may spell it --selftest; argparse must accept both."""
    mod = _load_guard()
    assert mod._parse_args(["--selftest"]).self_test is True
    assert mod._parse_args(["--self-test"]).self_test is True
    print("OK: --selftest and --self-test both accepted")


def test_prerelease_is_not_a_duplicate():
    """v0.10.0-rc.1 must not parse as (0,10,0) and collide with v0.10.0."""
    mod = _load_guard()
    assert mod.parse_version_tag("v0.10.0-rc.1") is None
    assert mod.parse_version_tag("v0.10.0") == (0, 10, 0)
    print("OK: prerelease tags are not duplicate versions")


def test_duplicate_tags_detected_without_version():
    """The no-version audit must refuse when two tags parse to one version.

    Only reachable for the same version spelled two ways (``v0.9.2`` and
    ``0.9.2``); a suffixed tag like ``v0.9.2-dup`` is deliberately NOT a
    duplicate (see test_prerelease_is_not_a_duplicate).
    """
    mod = _load_guard()
    mod.get_sorted_tags = lambda: ["v0.9.2", "0.9.2", "v0.9.1"]
    mod.get_tag_dates = lambda: {"v0.9.2": 0.0, "0.9.2": 0.0, "v0.9.1": 0.0}
    code, evidence = mod.check_release_guard(window_hours=48)
    assert code == 1, evidence
    assert any("duplicate version" in e for e in evidence), evidence
    print("OK: duplicate tags refused without --version")


def test_duplicate_audit_clean_tree():
    """The no-version audit must allow a tree with no duplicate tags."""
    mod = _load_guard()
    mod.get_sorted_tags = lambda: ["v0.9.2", "v0.9.1", "v0.9.0"]
    mod.get_tag_dates = lambda: {"v0.9.2": 0.0, "v0.9.1": 0.0, "v0.9.0": 0.0}
    code, evidence = mod.check_release_guard(window_hours=48)
    assert code == 0, evidence
    print("OK: no duplicates -> allowed")


def main() -> int:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        test_parse_version_tag()
        test_read_changelog_versions(tmp_path)
        test_check_release_guard_new_version_no_active()
        test_check_release_guard_already_tagged()
        test_documented_version_is_not_refused(tmp_path)
        test_check_release_guard_active_release()
        test_check_release_guard_empty_tags()
        test_check_release_guard_unreadable_dates()
        test_get_tag_dates_parses_for_each_ref()
        test_selftest_alias_accepted()
        test_prerelease_is_not_a_duplicate()
        test_duplicate_tags_detected_without_version()
        test_duplicate_audit_clean_tree()

    print("PASS: check_no_active_release regression suite")
    return 0


if __name__ == "__main__":
    sys.exit(main())