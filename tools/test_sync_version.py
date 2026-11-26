#!/usr/bin/env python3
"""Regression coverage for tools/sync_version.py.

Pins the writer's contract: all three derived sites move to plugin.yaml's
version, the SECURITY table keeps its history with exactly one supported row,
a non-standard layout fails closed without touching any file, and a second run
is a no-op. No network.

Run: python3 tools/test_sync_version.py
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("sync_version", HERE / "sync_version.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _fixture(root: Path, *, version: str = "1.2.3",
             init_version: str = "1.2.2", project_version: str = "1.2.2",
             security_version: str = "1.2.2",
             rows: list[tuple[str, str]] | None = None) -> None:
    (root / "plugin.yaml").write_text(f"name: x\nversion: {version}\n", encoding="utf-8")
    (root / "__init__.py").write_text(
        f'"""x"""\n__version__ = "{init_version}"\n', encoding="utf-8")
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "x"\nversion = "{project_version}"\n\n'
        '[tool.other]\nversion = "9.9.9"\n', encoding="utf-8")
    if rows is None:
        rows = [(security_version, ":white_check_mark:"), ("1.1.0", ":x:")]
    table = "\n".join(f"| {v} | {m} |" for v, m in rows)
    (root / "SECURITY.md").write_text(
        "# Security Policy\n\n## Supported Versions\n\n"
        f"Only the latest published version (`{security_version}`) receives security fixes.\n\n"
        f"| Version | Supported |\n| --- | --- |\n{table}\n", encoding="utf-8")


def _read(root: Path, name: str) -> str:
    return (root / name).read_text(encoding="utf-8")


def test_syncs_all_sites():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _fixture(root)
        version, edits, problems = mod.plan(root)
        assert version == "1.2.3" and not problems and len(edits) == 3, (version, problems, edits)
        mod.apply(edits)
        assert '__version__ = "1.2.3"' in _read(root, "__init__.py")
        project = _read(root, "pyproject.toml")
        assert 'version = "1.2.3"' in project
        assert 'version = "9.9.9"' in project, "other TOML tables must not move"
        security = _read(root, "SECURITY.md")
        assert "latest published version (`1.2.3`)" in security
        assert "| 1.2.3 | :white_check_mark: |" in security
        assert "| 1.2.2 | :x: |" in security


def test_dry_run_does_not_write():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _fixture(root)
        before = {p.name: p.read_text(encoding="utf-8") for p in root.iterdir()}
        _, edits, problems = mod.plan(root)
        assert edits and not problems
        after = {p.name: p.read_text(encoding="utf-8") for p in root.iterdir()}
        assert before == after


def test_idempotent_after_write():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _fixture(root)
        _, edits, _ = mod.plan(root)
        mod.apply(edits)
        _, again, problems = mod.plan(root)
        assert not again and not problems, (again, problems)


def test_new_version_goes_to_top_and_previous_is_demoted():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _fixture(root)
        _, edits, _ = mod.plan(root)
        mod.apply(edits)
        assert _read(root, "SECURITY.md").index("| 1.2.3 | :white_check_mark: |") < \
            _read(root, "SECURITY.md").index("| 1.2.2 | :x: |")
        # A second bump keeps the history and demotes the prior release.
        text = _read(root, "plugin.yaml").replace("version: 1.2.3", "version: 1.3.0")
        (root / "plugin.yaml").write_text(text, encoding="utf-8")
        _, edits, problems = mod.plan(root)
        assert not problems
        mod.apply(edits)
        security = _read(root, "SECURITY.md")
        assert "| 1.3.0 | :white_check_mark: |" in security
        assert "| 1.2.3 | :x: |" in security
        assert "| 1.2.2 | :x: |" in security


def test_invalid_version_refuses_without_writing():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _fixture(root, version="1.2")
        before = {p.name: p.read_text(encoding="utf-8") for p in root.iterdir()}
        old_repo = mod.REPO
        mod.REPO = root
        try:
            code = mod.main(["--write"])
        finally:
            mod.REPO = old_repo
        assert code == 2, code
        after = {p.name: p.read_text(encoding="utf-8") for p in root.iterdir()}
        assert before == after


def test_missing_site_fails_closed():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _fixture(root)
        (root / "__init__.py").unlink()
        before = {p.name: p.read_text(encoding="utf-8") for p in root.iterdir()}
        old_repo = mod.REPO
        mod.REPO = root
        try:
            code = mod.main(["--write"])
        finally:
            mod.REPO = old_repo
        assert code == 2, code
        after = {p.name: p.read_text(encoding="utf-8") for p in root.iterdir()}
        assert before == after


def test_table_without_rows_fails_closed():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _fixture(root, rows=[])
        _, edits, problems = mod.plan(root)
        assert problems and not edits, (edits, problems)


def test_single_quoted_project_version_preserves_quotes():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _fixture(root, project_version="1.2.2")
        text = _read(root, "pyproject.toml").replace('version = "1.2.2"', "version = '1.2.2'")
        (root / "pyproject.toml").write_text(text, encoding="utf-8")
        _, edits, _ = mod.plan(root)
        mod.apply(edits)
        assert "version = '1.2.3'" in _read(root, "pyproject.toml")


def main() -> int:
    cases = [
        test_syncs_all_sites,
        test_dry_run_does_not_write,
        test_idempotent_after_write,
        test_new_version_goes_to_top_and_previous_is_demoted,
        test_invalid_version_refuses_without_writing,
        test_missing_site_fails_closed,
        test_table_without_rows_fails_closed,
        test_single_quoted_project_version_preserves_quotes,
    ]
    failed = 0
    for case in cases:
        try:
            case()
            print(f"ok: {case.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL: {case.__name__}: {exc}")
    print(f"{'FAIL' if failed else 'OK'}: {len(cases) - failed}/{len(cases)} sync-version cases")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
