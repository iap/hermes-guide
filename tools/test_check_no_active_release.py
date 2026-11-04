#!/usr/bin/env python3
"""Behavioral regression test for tools/check_no_active_release.py.

Hermetic: stdlib only, fixtures in tempdirs, no network, no real git repo.
The test imports the guard's pure helpers and exercises the verdict paths by
monkeypatching the git/changelog readers.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load_guard():
    """Import check_no_active_release.py as a module (it lives in tools/)."""
    path = REPO / "tools" / "check_no_active_release.py"
    spec = importlib.util.spec_from_file_location("check_no_active_release", path)
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


def test_check_release_guard_new_version_no_active(tmp_path):
    """New version, no active release, not tagged -> exit 0."""
    mod = _load_guard()
    mod.get_sorted_tags = lambda: ["v0.9.2", "v0.9.1", "v0.9.0"]
    mod.get_latest_tag = lambda: "v0.9.2"
    mod.get_latest_tag_date = lambda: 0.0  # epoch -> not active in any window
    code, evidence = mod.check_release_guard(proposed_version="0.9.3", window_hours=48)
    assert code == 0, evidence
    assert not any("REDUNDANT" in e for e in evidence), evidence
    print("OK: new version, no active release")


def test_check_release_guard_already_tagged(tmp_path):
    """Proposed version already tagged -> exit 1 (redundant release)."""
    mod = _load_guard()
    mod.get_sorted_tags = lambda: ["v0.9.2", "v0.9.1", "v0.9.0"]
    mod.get_latest_tag = lambda: "v0.9.2"
    mod.get_latest_tag_date = lambda: 0.0
    code, evidence = mod.check_release_guard(proposed_version="0.9.2", window_hours=48)
    assert code == 1, evidence
    assert any("REDUNDANT" in e for e in evidence), evidence
    print("OK: already-tagged version refused")


def test_check_release_guard_already_documented(tmp_path):
    """Proposed version untagged but already in CHANGELOG -> exit 1."""
    mod = _load_guard()
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## v0.9.3 (2026-11-05)\n\n## v0.9.2 (2026-11-04)\n", encoding="utf-8")
    old = mod.CHANGELOG
    mod.CHANGELOG = changelog
    try:
        mod.get_sorted_tags = lambda: ["v0.9.2", "v0.9.1"]
        mod.get_latest_tag = lambda: "v0.9.2"
        mod.get_latest_tag_date = lambda: 0.0
        code, evidence = mod.check_release_guard(proposed_version="0.9.3", window_hours=48)
        assert code == 1, evidence
        assert any("DOCUMENTED" in e for e in evidence), evidence
    finally:
        mod.CHANGELOG = old
    print("OK: already-documented version refused")


def test_check_release_guard_active_release(tmp_path):
    """A tag created inside the window -> exit 1 (active release)."""
    import time

    mod = _load_guard()
    mod.get_sorted_tags = lambda: ["v0.9.2", "v0.9.1"]
    mod.get_latest_tag = lambda: "v0.9.2"
    mod.get_latest_tag_date = lambda: time.time() - 3600  # one hour ago
    code, evidence = mod.check_release_guard(proposed_version="0.9.3", window_hours=48)
    assert code == 1, evidence
    assert any("ACTIVE RELEASE" in e for e in evidence), evidence
    print("OK: active release refused")


def test_check_release_guard_empty_tags(tmp_path):
    """No tags -> exit 1 (cannot verify)."""
    mod = _load_guard()
    mod.get_sorted_tags = lambda: []
    code, evidence = mod.check_release_guard(window_hours=48)
    assert code == 1, evidence
    assert any("no git tags" in e for e in evidence), evidence
    print("OK: empty tags -> refuse")


def main() -> int:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        test_parse_version_tag()
        test_read_changelog_versions(tmp_path)
        test_check_release_guard_new_version_no_active(tmp_path)
        test_check_release_guard_already_tagged(tmp_path)
        test_check_release_guard_already_documented(tmp_path)
        test_check_release_guard_active_release(tmp_path)
        test_check_release_guard_empty_tags(tmp_path)

    print("PASS: check_no_active_release regression suite")
    return 0


if __name__ == "__main__":
    sys.exit(main())