#!/usr/bin/env python3
"""Require a dated provenance footer in every ``skills/*/SKILL.md``.

Why this exists
---------------
This guide's value proposition is that each skill's facts were **verified against
a named upstream revision**. The existing ``tools/check_citation_integrity.py``
proves a cited symbol still resolves — but it cannot tell you *when* a skill was
last checked, or whether the file was ever checked at all. In the 2026-09 review
programme two skills shipped without any provenance line, and the wording was
split between "Facts verified …" and "Facts re-verified …", so a grep for one
form silently missed files using the other.

This guard makes the footer a requirement, so provenance cannot regress: adding a
skill, or editing one, keeps (or adds) a dated, upstream-anchored line.

A footer is a final line matching (case-insensitive on "facts"):
    Facts verified YYYY-MM-DD against upstream …
    Facts re-verified YYYY-MM-DD against upstream …

Usage
-----
    python tools/check_skill_provenance.py            # enforce (exit 1 on any gap)
    python tools/check_skill_provenance.py --warn      # report only (exit 0)
    python tools/check_skill_provenance.py --selftest  # fixture test, no repo scan

Exit code is 0 when every skill carries a footer (or when ``--warn`` is set),
1 otherwise.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO / "skills"

# Accept both the legacy and the canonical wording; require a date and an
# upstream anchor so the line can't be a vague "verified" with no when/where.
FOOTER_RE = re.compile(
    r"facts\s+(?:re-)?verified\s+\d{4}-\d{2}-\d{2}\b[^\n]*\bupstream\b",
    re.IGNORECASE,
)


def has_footer(text: str) -> bool:
    return FOOTER_RE.search(text) is not None


def scan(skills_dir: Path) -> tuple[list[str], list[str]]:
    """Return (ok, missing) lists of "skill-name" for each SKILL.md present."""
    ok: list[str] = []
    missing: list[str] = []
    if not skills_dir.is_dir():
        return ok, missing
    for path in sorted(skills_dir.glob("*/SKILL.md")):
        name = path.parent.name
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            missing.append(name)
            continue
        (ok if has_footer(text) else missing).append(name)
    return ok, missing


def _selftest() -> int:
    good = "Body.\n\n---\n\n*Facts re-verified 2026-09-15 against upstream source at `abc123`.*\n"
    good_legacy = "*Facts verified 2026-09-14 against upstream source at `8aa219ef` (x).*"
    bad = "Body only, no provenance line at the end.\n"
    bad_undated = "*Facts verified against upstream source.*\n"
    cases = [(good, True), (good_legacy, True), (bad, False), (bad_undated, False)]
    for text, expected in cases:
        got = has_footer(text)
        if got != expected:
            print(f"selftest FAIL: expected {expected}, got {got} for {text!r}")
            return 1
    print(f"selftest OK ({len(cases)} cases)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--warn", action="store_true", help="report gaps but exit 0")
    ap.add_argument("--selftest", action="store_true", help="run the parser fixture test")
    ap.add_argument("--skills-dir", default=str(SKILLS_DIR))
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    ok, missing = scan(Path(args.skills_dir))
    total = len(ok) + len(missing)
    print(f"skill provenance: {len(ok)}/{total} skills carry a dated upstream footer")
    if missing:
        for name in missing:
            print(f"  MISSING: skills/{name}/SKILL.md")
        print(
            "Add a final line, e.g.:\n"
            "  *Facts re-verified YYYY-MM-DD against upstream source at `<rev>` "
            "(<files/symbols>); plus the issue tracker. Re-verify before reuse.*"
        )
        return 0 if args.warn else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
