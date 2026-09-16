#!/usr/bin/env python3
"""Regression test for tools/check_skill_provenance.py.

Covers the classification rules (final-line placement, real date, upstream
anchor, revision reference) and the scan-target guards (missing / empty
directory must NOT be reported as a clean scan). Fixture-based so it runs in CI
without the upstream tree.
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
    # 1. Classification rules -------------------------------------------------
    cases = [
        ("*Facts re-verified 2026-09-15 against upstream source at `cedf4a3d`.*", True),
        ("*Facts verified 2026-09-14 against upstream source at `8aa219ef`.*", True),
        ("*Facts re-verified 2026-09-14 against upstream source at current main.*", True),
        ("no footer here", False),
        ("*Facts verified against upstream source.*", False),                 # undated
        ("*Facts verified 2026-99-99 against upstream.*", False),            # impossible date
        ("*Facts verified 2026-09-15 against upstream.*", False),            # no revision ref
        # footer present but NOT the final line -> not provenance
        ("*Facts verified 2026-09-15 against upstream at `abcd1234`.*\n\ntrailing text", False),
    ]
    for text, expected in cases:
        assert mod.has_footer(text) is expected, (text, mod.has_footer(text), expected)

    # 2. Directory scan -------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        _mk(root, "alpha", "body\n\n---\n\n*Facts re-verified 2026-09-15 against upstream source at `abc1234`.*\n")
        _mk(root, "gamma", "no footer here\n")
        ok, problems = mod.scan(root)
        assert sorted(ok) == ["alpha"], ok
        assert [n for n, _ in problems] == ["gamma"], problems

        # missing dir and empty dir must raise, never scan clean
        for bad in (Path(tmp) / "does-not-exist", Path(tmp) / "empty"):
            if bad.name == "empty":
                bad.mkdir()
            try:
                mod.scan(bad)
                raise AssertionError(f"scan({bad}) should have raised")
            except (FileNotFoundError, ValueError):
                pass

    # 3. main() exit codes ----------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        _mk(root, "alpha", "body\n\n*Facts re-verified 2026-09-15 against upstream source at `abc1234`.*\n")
        assert mod.main(["--skills-dir", str(root)]) == 0            # clean
        _mk(root, "bud", "no footer\n")
        assert mod.main(["--skills-dir", str(root)]) == 1            # gap -> enforce
        assert mod.main(["--skills-dir", str(root), "--warn"]) == 0  # gap -> warn
        assert mod.main(["--skills-dir", str(Path(tmp) / "nope")]) == 2  # unusable -> error

    # 4. The real repo must scan, and the selftest must pass.
    real_ok, real_problems = mod.scan(Path(mod.SKILLS_DIR))
    assert real_ok or real_problems, "repo scan returned nothing"
    assert mod._selftest() == 0

    print("provenance guard regression: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
