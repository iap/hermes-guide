#!/usr/bin/env python3
"""Regression test for tools/check_skill_provenance.py.

Exercises the guard on temp fixtures so it cannot silently stop detecting gaps
(e.g. a regex that matches anything). Also asserts the real repo is scanned.
"""
import importlib.util
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("check_skill_provenance", HERE / "check_skill_provenance.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _mk(root: Path, name: str, body: str) -> None:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(body, encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        goods = (
            "*Facts re-verified 2026-09-15 against upstream source at `abc`.*\n"
        )
        legacy = "*Facts verified 2026-09-14 against upstream source at `8aa219ef`.*\n"
        _mk(root, "alpha", "body\n\n---\n\n" + goods)
        _mk(root, "beta", "body\n\n" + legacy)
        _mk(root, "gamma", "no footer here\n")

        ok, missing = mod.scan(root)
        assert sorted(ok) == ["alpha", "beta"], ok
        assert missing == ["gamma"], missing

        # A vague, undated line must NOT satisfy the guard.
        _mk(root, "delta", "*Facts verified against upstream source.*\n")
        ok2, missing2 = mod.scan(root)
        assert "delta" in missing2, missing2

    # The real repo must be scannable.
    real_ok, real_missing = mod.scan(Path(mod.SKILLS_DIR))
    assert real_ok or real_missing, "repo scan returned nothing"

    assert mod._selftest() == 0
    print("provenance guard regression: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
