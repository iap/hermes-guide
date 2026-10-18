#!/usr/bin/env python3
"""Fail when a hand-written scope list or check count drifts from `_CHECKS`.

`checks.py` `_CHECKS` is the source of truth for the plugin's health-check
scopes. Three files restate that set in prose that cannot be generated:

- `plugin.yaml` — the catalog description. `hermes plugins info` prints it, so
  it is a YAML scalar and can carry no BEGIN/END GENERATED markers.
- `README.md` — the "runs all nine checks" sentence under *Use the plugin*.
- `plugin-skills/start/SKILL.md` — the router skill's `Valid scopes:` line.

`tools/render_docs.py` generates the scope lists it can (the README and AGENTS
blocks) and `tools/test_skill_counts.py` no longer owns counts, so nothing read
these three. They drifted twice: the router skill's list was corrected seven to
nine on 2026-10-17 while `plugin.yaml`'s kept the same stale seven, and the
README count has never been checked at all.

Hermetic: an `ast` read of `checks.py` plus three file reads. No PyYAML, no
Hermes install, no network. The `_CHECKS` reader is duplicated from
`render_docs.py` on purpose — no script under `tools/` imports a sibling, so
each guard stays runnable on a bare interpreter in a commit hook.

Usage:
    python tools/check_scope_enumeration.py --selftest

Exit codes: 0 clean; 1 drift found; 2 `_CHECKS` (or a target file) unreadable.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CHECKS_PY = REPO / "checks.py"
PLUGIN_YAML = REPO / "plugin.yaml"
README = REPO / "README.md"
ROUTER_SKILL = REPO / "plugin-skills" / "start" / "SKILL.md"

# Prose style is word-numbers, never digits, so only a word in this set is
# treated as a count. That is what lets "read-only health checks" pass while
# "all nine checks" is checked: "health" is not a count word.
_NUM_WORDS = (
    "one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen twenty twenty-one "
    "twenty-two"
).split()

_COUNT_CHECKS = re.compile(r"(?i)\b([a-z]+(?:-[a-z]+)?)\s+checks\b")
_COUNT_SCOPES = re.compile(r"(?i)\b([a-z]+(?:-[a-z]+)?)\s+scopes\b")
# The list wraps across lines, so capture the paragraph, not the line.
_SCOPES_BLOCK = re.compile(r"(?is)\bValid scopes:(.*?)(?:\n[ \t]*\n|\Z)")
_BACKTICK = re.compile(r"`([^`]+)`")

# A label whose human spelling in plugin.yaml prose is not the label itself.
_ALIASES = {
    "config": re.compile(r"(?i)\bconfig(?:uration)?\b"),
    "mcp": re.compile(r"(?i)\bmcp\b"),
}


def check_labels(checks_py: Path = CHECKS_PY) -> list[str]:
    """The `_CHECKS` labels, read with `ast` and never imported."""
    tree = ast.parse(checks_py.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "_CHECKS" for t in node.targets):
            continue
        labels = [
            elt.elts[0].value
            for elt in node.value.elts  # type: ignore[attr-defined]
            if isinstance(elt.elts[0], ast.Constant)
            and isinstance(elt.elts[0].value, str)
        ]
        if labels:
            return labels
    raise SystemExit(f"error: could not read _CHECKS labels from {checks_py}")


def _word(n: int) -> str:
    """Spell `n` the way the prose does; digits past the table are accepted."""
    return _NUM_WORDS[n - 1] if 1 <= n <= len(_NUM_WORDS) else str(n)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def count_problems(text: str, expected: str, kind: str, where: str) -> list[str]:
    """Flag any `"<count-word> checks|scopes"` whose number is not `expected`."""
    pattern = _COUNT_CHECKS if kind == "checks" else _COUNT_SCOPES
    problems = []
    for match in pattern.finditer(text):
        word = match.group(1).lower()
        if word in _NUM_WORDS and word != expected:
            problems.append(
                f'{where}: says "{word} {kind}", but _CHECKS has {expected} '
                f'— correct the count or split the list'
            )
    return problems


def plugin_yaml_problems(labels: list[str], text: str) -> list[str]:
    """Every scope must be named in the catalog description.

    If the description ever stops enumerating the scopes, drop this assertion
    rather than the list — an unenumerated description cannot drift, but it
    also tells the catalog reader less.
    """
    problems = []
    for label in labels:
        pattern = _ALIASES.get(label, re.compile(rf"(?i)\b{re.escape(label)}\b"))
        if not pattern.search(text):
            problems.append(
                f"plugin.yaml: the description never names the `{label}` scope"
            )
    return problems


def router_skill_problems(labels: list[str], text: str) -> list[str]:
    """The `Valid scopes:` backtick run must equal the `_CHECKS` label set."""
    match = _SCOPES_BLOCK.search(text)
    if not match:
        return [f"{ROUTER_SKILL.name}: no 'Valid scopes:' block found"]
    listed = _BACKTICK.findall(match.group(1))
    missing = [label for label in labels if label not in listed]
    extra = [label for label in listed if label not in labels]
    if not missing and not extra:
        return []
    detail = []
    if missing:
        detail.append(f"missing {missing}")
    if extra:
        detail.append(f"unknown {extra}")
    return [
        f"plugin-skills/start/SKILL.md: the 'Valid scopes:' list does not match "
        f"_CHECKS ({'; '.join(detail)})"
    ]


def _collect() -> list[str]:
    labels = check_labels()
    expected = _word(len(labels))
    problems: list[str] = []
    for path, extra in (
        (PLUGIN_YAML, plugin_yaml_problems),
        (README, lambda ls, text: count_problems(text, expected, "checks", "README.md")),
        (ROUTER_SKILL, router_skill_problems),
    ):
        try:
            text = _read(path)
        except OSError as exc:
            problems.append(f"{path.name}: unreadable ({exc})")
            continue
        if path is ROUTER_SKILL:
            problems += count_problems(text, expected, "scopes", path.name)
        problems += extra(labels, text)
    return problems


def selftest() -> int:
    labels = ["config", "mcp", "skills"]
    all_named = "checks across config, MCP servers, skills"
    # (name, problems the guard should return, should it return any at all)
    cases: list[tuple[str, list[str], bool]] = [
        ("plugin: every label named", plugin_yaml_problems(labels, all_named), False),
        (
            "plugin: a label missing",
            plugin_yaml_problems(labels, "checks across config and skills"),
            True,
        ),
        (
            "router: list matches",
            router_skill_problems(labels, "Valid scopes: `config`, `mcp`,\n`skills`.\n\nNext."),
            False,
        ),
        (
            "router: an extra label",
            router_skill_problems(labels, "Valid scopes: `config`, `mcp`, `skills`, `update`."),
            True,
        ),
        (
            "count: correct",
            count_problems("runs all nine checks in-process", "nine", "checks", "README.md"),
            False,
        ),
        (
            "count: stale",
            count_problems("runs all seven checks in-process", "nine", "checks", "README.md"),
            True,
        ),
        (
            "count: a non-number adjective is ignored",
            count_problems("read-only health checks across", "nine", "checks", "README.md"),
            False,
        ),
    ]
    failures = 0
    for name, got, want_problem in cases:
        if bool(got) != want_problem:
            failures += 1
            print(
                f"SELFTEST FAIL ({name}): expected "
                f"{'a problem' if want_problem else 'no problem'}, got {got}",
                file=sys.stderr,
            )
    if failures:
        print(f"error: {failures}/{len(cases)} selftest case(s) failed", file=sys.stderr)
        return 1
    print(f"OK: selftest {len(cases)} case(s) passed")
    return 0


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    problems = _collect()
    if problems:
        print(
            "FAIL: a scope list or check count drifted from checks.py `_CHECKS`:",
            file=sys.stderr,
        )
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    count = len(check_labels())
    print(
        "OK: plugin.yaml, README.md and the router skill agree with "
        f"_CHECKS ({count} scopes)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
