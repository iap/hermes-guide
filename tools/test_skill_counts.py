#!/usr/bin/env python3
"""Regression: skill/check counts stated in README.md, AGENTS.md, and
CONTRIBUTING.md match reality.

Manual counts were the repo's most recurring doc defect (AGENTS.md said "six
skills" when there were eight; README said "eight" when there were nine). Each
case here pins one count-bearing phrase against ground truth:

  - number of skills/ dirs with a SKILL.md (the actual skills)
  - number of check labels in checks._CHECKS (the actual checks)
  - README: "N troubleshooting skills" phrase, skill-table row count,
    "The other N skills" tap-install list
  - AGENTS.md: "bundles N SKILL.md files", "The N skills (one map + M
    diagnostics)", "The N read-only health checks" + its scope list
  - CONTRIBUTING.md: "bundles N SKILL.md files" (same phrase, same ground truth)

Word-numbers are expected (two..twenty); a digit in any of these phrases is
treated as a mismatch to keep the prose style consistent.

Run: python3 tools/test_skill_counts.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

_WORDS = [
    "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen", "twenty",
]
_NUM = {w: i + 2 for i, w in enumerate(_WORDS)}


def _word_num(n: int) -> str:
    try:
        return _WORDS[n - 2]
    except IndexError:
        raise AssertionError(f"no word for {n} — extend _WORDS in this test")


def _parse_wordNum(text: str, pattern: str, label: str) -> int:
    """Extract a word-number via `pattern` (one capture group) and convert."""
    m = re.search(pattern, text, re.IGNORECASE)
    assert m, f"{label}: phrase not found"
    word = m.group(1).lower()
    assert word in _NUM, f"{label}: expected a word-number, got {word!r}"
    return _NUM[word]


def main() -> int:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    contributing = (REPO / "CONTRIBUTING.md").read_text(encoding="utf-8")

    actual_skills = len(list(REPO.glob("skills/*/SKILL.md")))
    assert actual_skills >= 2, "sanity: no skills found"

    # The repo dir is hyphenated ("hermes-guide") so it can't be imported as a
    # package directly — mirror tools/test_readonly_runtime.py's shim.
    import shutil
    import tempfile

    td = Path(tempfile.mkdtemp())
    pkg = td / "hermes_guide"
    pkg.mkdir()
    for name in ("__init__.py", "checks.py", "constants.py"):
        shutil.copy(REPO / name, pkg / name)
    sys.path.insert(0, str(td))
    import hermes_guide.checks as checks_mod  # noqa: E402

    actual_checks = len(checks_mod.labels())
    actual_diagnostics = actual_skills - 1  # minus the map skill

    failures: list[str] = []

    def expect(label: str, stated: int, actual: int) -> None:
        if stated != actual:
            failures.append(f"{label}: stated {stated}, actual {actual}")

    # README — headline count and skill table
    expect(
        "README 'N troubleshooting skills'",
        _parse_wordNum(readme, r"\*\*([A-Za-z]+) troubleshooting skills\*\*", "README headline"),
        actual_skills,
    )
    table_rows = re.findall(r"^\| `(?:hermes-|diagnosing-|installing-)[a-z0-9-]+` \|", readme, re.M)
    expect("README skill-table rows", len(table_rows), actual_skills)
    expect(
        "README 'The other N skills'",
        _parse_wordNum(readme, r"The other ([A-Za-z]+) skills", "README tap list"),
        actual_skills - 1,
    )

    # README install-all loop identifiers must exactly match the shipped
    # skills/ inventory (a rename/add that skips the loop leaves it stale
    # while the count assertions above would still pass — #65 review P2).
    loop_m = re.search(r"for s in ([a-z0-9- ]+); do", readme)
    assert loop_m, "README: install-all loop not found"
    loop_ids = sorted(loop_m.group(1).split())
    dir_ids = sorted(p.parent.name for p in REPO.glob("skills/*/SKILL.md"))
    expect("README install-all loop identifiers", len(loop_ids), len(dir_ids))
    if loop_ids != dir_ids:
        failures.append(
            "README install-all loop identifiers differ from skills/ inventory: "
            f"loop-only={sorted(set(loop_ids) - set(dir_ids))} "
            f"inventory-only={sorted(set(dir_ids) - set(loop_ids))}"
        )

    # AGENTS.md — overview, structure rows
    expect(
        "AGENTS.md 'bundles N SKILL.md files'",
        _parse_wordNum(agents, r"bundles ([A-Za-z]+) SKILL\.md files", "AGENTS.md overview"),
        actual_skills,
    )
    expect(
        "AGENTS.md 'The N skills ship separately'",
        _parse_wordNum(agents, r"the ([A-Za-z]+) skills ship separately", "AGENTS.md init row"),
        actual_skills,
    )
    expect(
        "AGENTS.md skills row total",
        _parse_wordNum(agents, r"The ([A-Za-z]+) skills \(one map \+", "AGENTS.md skills row"),
        actual_skills,
    )
    expect(
        "AGENTS.md skills row diagnostics",
        _parse_wordNum(agents, r"one map \+ ([A-Za-z]+) diagnostics\)", "AGENTS.md skills row"),
        actual_diagnostics,
    )

    # AGENTS.md — checks row: count and the scope list must match checks.labels()
    expect(
        "AGENTS.md 'The N read-only health checks'",
        _parse_wordNum(agents, r"The ([A-Za-z]+) read-only health checks", "AGENTS.md checks row"),
        actual_checks,
    )
    m = re.search(r"The [A-Za-z]+ read-only health checks \(([a-z/]+)\)", agents)
    assert m, "AGENTS.md checks row: scope list not found"
    stated_scopes = m.group(1).split("/")
    if stated_scopes != checks_mod.labels():
        failures.append(
            f"AGENTS.md checks row scopes: stated {stated_scopes}, actual {checks_mod.labels()}"
        )

    # README — plugin capability line must list exactly the check labels.
    # Parse the documented scope list and compare names exactly (substring
    # matching would accept stale or renamed scopes like `memories-old`).
    m = re.search(r"read-only diagnostics across ([^.]+)\.", readme)
    assert m, "README: plugin diagnostics line not found"
    items = []
    for item in m.group(1).split(","):
        item = re.sub(r"\s*\(.*$", "", item.strip())   # trailing annotation
        item = re.sub(r"\s+—.*$", "", item).strip()    # em-dash tail
        item = re.sub(r"^and\s+", "", item)
        if item:
            items.append(item)
    if sorted(items) != sorted(checks_mod.labels()):
        failures.append(
            f"README plugin line scopes: stated {items}, actual {checks_mod.labels()}"
        )

    # CONTRIBUTING.md — overview count (same phrase as AGENTS.md; drifted
    # unnoticed in #69 because only README/AGENTS.md were guarded).
    expect(
        "CONTRIBUTING.md 'bundles N SKILL.md files'",
        _parse_wordNum(contributing, r"bundles ([A-Za-z]+) SKILL\.md files", "CONTRIBUTING.md overview"),
        actual_skills,
    )

    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        print(
            f"{len(failures)} count mismatch(es) — update README.md/AGENTS.md/CONTRIBUTING.md "
            f"(actual: {actual_skills} skills, {actual_diagnostics} diagnostics, "
            f"{actual_checks} checks: {_word_num(actual_skills)}/"
            f"{_word_num(actual_diagnostics)}/{_word_num(actual_checks)})",
            file=sys.stderr,
        )
        return 1
    print(
        f"OK: counts consistent ({actual_skills} skills, {actual_diagnostics} "
        f"diagnostics, {actual_checks} checks)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
