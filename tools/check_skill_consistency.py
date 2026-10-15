#!/usr/bin/env python3
"""One filename-anchored number must agree repo-wide (or carry scope).

Why this exists
---------------
Two skills cited different line counts for the same file in the same week
(`credential_pool.py` as 3057 vs 3083 lines) and nobody noticed: every
content gate is per-file, and nothing compares skill against skill. Counts
rot per upstream commit while symbols survive, so agreement here is also
the tripwire that pushes authors toward symbolic citations instead.

Scope (deliberate): integers directly associated with a backticked
filename on the same line (``(3057 lines)``, ``port 9119`` shapes are
out of scope — ports were never observed diverging). A line carrying an
explicit scope word (posix, windows, wsl, legacy, older, version,
transport, http, stdio, bundle, profile, platform, per-) is exempt:
legitimate per-context variance must be qualified, and the qualifier is
the fix this check demands.

Hermetic: pure file reads, no network, no Hermes. Safe for the fast tier,
but runs in CI alongside the other test_*.py suites (the hermetic
check_gates.py tier list is frozen to avoid churning its counts).

Only explicit count constructions anchor a number to a file:
`` `path/file.ext` (3057 lines) ``. Bare numbers sharing a line with a
filename (timeouts, exit codes, issue refs like #12912, versions) are
different quantities and must not compare — requiring the parenthesized
count form keeps those out by construction. Glob patterns (`*.py`) never
anchor anything.

Run: python3 tools/check_skill_consistency.py
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO / "skills"

FILE_RE = re.compile(r"`([^`*]*\.(?:json|yaml|yml|md|py|toml|lock|ts|tsx|js|jsx))`")
COUNT_RE = re.compile(
    r"\(\s*(\d[\d,]*)\s*(?:lines?|files?|skills?|rows?|entries|checks?|tests?|cases?)\s*\)")
COUNT_WINDOW = 60

# Words that scope a claim to one context; their presence exempts the line.
# Keep this list short and literal: every entry must be doing real work in
# at least one exempted line, or it becomes a blanket excuse.
SCOPE_WORDS = (
    "posix", "windows", "wsl", "macos", "linux", "legacy", "older",
    "version", "transport", "http", "stdio", "bundle", "profile",
    "platform", "per-",
)


def _numbers_near_filename(line: str) -> list[tuple[str, str]]:
    """(dir-key, basename, count) for explicit ``file (N unit)`` constructions."""
    # Scope words count only outside code spans: a filename like
    # `profile.yaml` must not exempt its own line.
    prose = re.sub(r"`[^`]*`", "", line)
    if any(w in prose.lower() for w in SCOPE_WORDS):
        return []
    out = []
    matches = list(FILE_RE.finditer(line))
    for idx, m in enumerate(matches):
        inner = m.group(1)
        parts = inner.split("/")
        base = parts[-1]
        # Bare basenames (no directory) match only each other: a bare
        # `config.yaml` never accuses `$HERMES_HOME/config.yaml` of
        # disagreeing, and vice versa.
        key = "/".join(parts[:-1])
        # A count following a second filename belongs to that file, not
        # this one: bound the window at the next filename match (and at
        # COUNT_WINDOW regardless, so distant numbers never attach).
        end = m.end() + COUNT_WINDOW
        if idx + 1 < len(matches):
            end = min(end, matches[idx + 1].start())
        window = line[m.end():end]
        for c in COUNT_RE.finditer(window):
            out.append((key, base, c.group(1).replace(",", "")))
    return out


def collect() -> list[tuple[str, int, str, str, str, str]]:
    """(skill, line, dir-key, filename, number, text) for anchored numbers."""
    out = []
    for f in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        skill = f.parent.name
        for i, line in enumerate(
                f.read_text(encoding="utf-8").splitlines(), 1):
            for key, base, num in _numbers_near_filename(line):
                out.append((skill, i, key, base, num, line.strip()))
    return out


def verify(rows) -> tuple[list[str], str]:
    """Group by (dir, filename); disagreeing numbers fail unless scoped."""
    by_file: dict[tuple[str, str], dict[str, list[str]]] = {}
    for skill, ln, key, base, num, text in rows:
        by_file.setdefault((key, base), {}).setdefault(num, []).append(
            "%s:%d" % (skill, ln))
    failures = []
    for (key, base) in sorted(by_file):
        if len(by_file[(key, base)]) > 1:
            shown = (key + "/" if key else "") + base
            parts = "; ".join(
                "%s at %s" % (num, ", ".join(locs))
                for num, locs in sorted(by_file[(key, base)].items()))
            failures.append(
                "%s: disagreeing numbers: %s "
                "(qualify one side with a scope word, or drop the count)" % (shown, parts))
    summary = "OK: %d filename-anchored number(s) agree across skills" % sum(
        len(v) for v in by_file.values())
    return failures, summary


def _selftest() -> int:
    assert _numbers_near_filename("`a.json` (3057 lines) x") == [("", "a.json", "3057")]
    assert _numbers_near_filename("POSIX `a.json` (1 lines) y") == []
    assert _numbers_near_filename("no file 42 here") == []
    assert _numbers_near_filename("`a.py` see #12912, timeout 300") == []
    assert _numbers_near_filename("`*.py` (4 files) globbed") == []
    assert _numbers_near_filename("`d/a.ts` (9 lines) z") == [("d", "a.ts", "9")]
    fails, _ = verify([("s1", 1, "", "a.json", "3057", "x"),
                       ("s2", 2, "", "a.json", "3083", "y")])
    assert len(fails) == 1 and "a.json" in fails[0]
    fails, _ = verify([("s1", 1, "", "a.json", "3057", "x")])
    assert not fails
    # Same basename, different dirs: no comparison.
    fails, _ = verify([("s1", 1, "$H", "config.yaml", "5", "x"),
                       ("s2", 2, "bot", "config.yaml", "7", "y")])
    assert not fails
    # Scope words inside backticked spans do not exempt the line.
    assert _numbers_near_filename("`profile.yaml` (120 lines) z") == [
        ("", "profile.yaml", "120")]
    # A count after a second filename belongs to the second file.
    assert _numbers_near_filename("`a.py` (10 lines), `b.py` (20 lines)") == [
        ("", "a.py", "10"), ("", "b.py", "20")]
    print("OK: skill-consistency selftest")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    failures, summary = verify(collect())
    print(summary)
    for f in failures:
        print("FAIL:", f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
