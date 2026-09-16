#!/usr/bin/env python3
"""Require a dated, upstream-anchored provenance footer in every ``skills/*/SKILL.md``.

Why this exists
---------------
This guide's value proposition is that each skill's facts were **verified against
a named upstream revision**. ``tools/check_citation_integrity.py`` proves a cited
symbol still resolves — but it cannot tell you *when* a skill was last checked, or
whether it ever was. In the 2026-09 programme two skills shipped with no
provenance line, and the wording split between "Facts verified …" and
"Facts re-verified …", so a grep for one form silently missed the other.

This guard makes the footer a requirement so provenance cannot regress.

What counts as a footer
-----------------------
The **final non-empty line** of the file must:
1. start the provenance clause ``Facts (re-)verified YYYY-MM-DD`` (case-insensitive
   on "facts");
2. carry a **real calendar date** (``2026-99-99`` is rejected);
3. name an **upstream anchor** (the word "upstream");
4. reference a **revision** — a backticked hex sha (``8aa219ef``), or the words
   ``commit`` / ``baseline`` / ``main``.

Requiring it on the *final line* (not "anywhere in the file") is deliberate:
provenance buried mid-document is not provenance.

Usage
-----
    python tools/check_skill_provenance.py            # enforce (exit 1 on any gap)
    python tools/check_skill_provenance.py --warn      # report only (exit 0)
    python tools/check_skill_provenance.py --selftest  # fixture test, no repo scan

Exit codes: 0 ok / clean; 1 a skill is missing or malformed; 2 the scan target is
unusable (missing directory, or zero SKILL.md found — never reported as "clean",
so a mistyped ``--skills-dir`` cannot silently bypass the check).
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO / "skills"

# "Facts (re-)verified <date>" + the remainder of the line.
FOOTER_RE = re.compile(r"facts\s+(?:re-)?verified\s+(\d{4})-(\d{2})-(\d{2})\b([^\n]*)", re.IGNORECASE)
# A revision reference: a backticked hex sha, or the words commit / baseline / main.
REV_RE = re.compile(r"`[0-9a-f]{7,40}`|\b(?:commit|baseline|main)\b", re.IGNORECASE)


def _final_line(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def footer_problem(text: str) -> str | None:
    """None when compliant, else a short reason (for actionable output)."""
    line = _final_line(text)
    m = FOOTER_RE.search(line)
    if not m:
        # Distinguish "no footer at all" from "a footer that isn't the final line".
        anywhere = FOOTER_RE.search(text)
        return "provenance line is not the final line" if anywhere else "no provenance footer"
    try:
        datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return "provenance date is not a real calendar date"
    rest = m.group(4)
    if "upstream" not in rest.lower():
        return "provenance line has no upstream anchor"
    if REV_RE.search(rest) is None:
        return "provenance line names no revision (sha / commit / baseline / main)"
    return None


def has_footer(text: str) -> bool:
    return footer_problem(text) is None


def scan(skills_dir: Path) -> tuple[list[str], list[tuple[str, str]]]:
    """Return (ok, problems) where problems is [(skill, reason)]. Raises if the
    directory is unusable (missing dir, or zero SKILL.md found)."""
    if not skills_dir.is_dir():
        raise FileNotFoundError(str(skills_dir))
    paths = sorted(skills_dir.glob("*/SKILL.md"))
    if not paths:
        raise ValueError(f"no SKILL.md found under {skills_dir}")
    ok: list[str] = []
    problems: list[tuple[str, str]] = []
    for path in paths:
        name = path.parent.name
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            problems.append((name, f"unreadable ({type(exc).__name__})"))
            continue
        reason = footer_problem(text)
        if reason is None:
            ok.append(name)
        else:
            problems.append((name, reason))
    return ok, problems


_SELFTEST_CASES = [
    # (text, expected)
    ("Body.\n\n---\n\n*Facts re-verified 2026-09-15 against upstream source at `cedf4a3d`.*\n", True),
    ("*Facts verified 2026-09-14 against upstream source at `8aa219ef` (x).*", True),
    ("*Facts re-verified 2026-09-14 against upstream source at current main.*", True),
    ("Body only, no provenance line.\n", False),
    ("*Facts verified against upstream source.*\n", False),                       # undated
    ("*Facts verified 2026-99-99 against upstream.*\n", False),                  # bad date
    ("*Facts verified 2026-09-15 against upstream.*\n", False),                  # no revision ref
    ("*Facts verified 2026-09-15 against upstream at `abcd1234`.*\n\nmore text follows\n", False),  # not final line
]


def _selftest() -> int:
    for text, expected in _SELFTEST_CASES:
        got = has_footer(text)
        if got != expected:
            print(f"selftest FAIL: expected {expected}, got {got} for {text!r}")
            return 1
    print(f"selftest OK ({len(_SELFTEST_CASES)} cases)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--warn", action="store_true", help="report gaps but exit 0")
    ap.add_argument("--selftest", action="store_true", help="run the parser fixture test")
    ap.add_argument("--skills-dir", default=str(SKILLS_DIR))
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    skills_dir = Path(args.skills_dir)
    try:
        ok, problems = scan(skills_dir)
    except (FileNotFoundError, ValueError) as exc:
        # Never report an unusable scan as "clean" (a mistyped path must fail the job).
        print(f"error: unusable skills dir: {exc}", file=sys.stderr)
        return 2

    total = len(ok) + len(problems)
    print(f"skill provenance: {len(ok)}/{total} skills carry a dated upstream footer")
    if problems:
        for name, reason in problems:
            print(f"  {name}: {reason}")
        print(
            "Add or fix the final line, e.g.:\n"
            "  *Facts re-verified YYYY-MM-DD against upstream source at `<rev>` "
            "(<files/symbols>); plus the issue tracker. Re-verify before reuse.*"
        )
        return 0 if args.warn else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
