#!/usr/bin/env python3
"""Fail when a hand-written scope list, count or description length drifts.

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

_COUNT_NOUN = re.compile(r"(?i)\b(checks?|scopes?)\b")
# Count phrasing varies: "all nine checks" and "nine read-only health checks"
# both appear in this repo. So anchor on the noun and look back a few tokens
# for the nearest spelled number. Requiring adjacency would miss the qualified
# form; allowing inner words greedily would let "all" shadow "nine".
_WORD = re.compile(r"[A-Za-z]+(?:-[A-Za-z]+)?")
_LOOKBACK = 4
# A count belongs to the sentence holding its noun: "Twenty-two skills. Checks
# are read-only." must not read "twenty-two" as a check count. Sentence
# punctuation and a blank line (a paragraph break) bound the segment; a single
# Markdown soft wrap does not, so a stale "seven read-only health\nchecks" is
# still caught.
_CLAUSE_END = re.compile(r"[.!?;]|\n[ \t]*\n")
# The router skill wraps its list across lines, so capture the paragraph.
_SCOPES_BLOCK = re.compile(r"(?is)\bValid scopes:(.*?)(?:\n[ \t]*\n|\Z)")
_BACKTICK = re.compile(r"`([^`]+)`")
# The catalog's list is the folded `description:` scalar; searching the whole
# manifest would let the unrelated `config_schema:` key supply `config`.
_DESCRIPTION_KEY = re.compile(r"^description:[ \t]*[>|]?[-+]?[ \t]*$")


def _description_scalar(text: str) -> tuple[str, str] | None:
    """(raw block, folded value) for the block scalar under `description:`.

    Blank lines belong to a YAML block scalar, so the scan runs through them
    and stops at the first non-blank, non-indented line (the next top-level
    key). A regex over consecutive indented lines stops at the first blank
    line, which would hide a second paragraph from both the scope run and the
    length cap; `plugins list` wraps the whole value, so the cap must see it.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not _DESCRIPTION_KEY.match(line):
            continue
        raw: list[str] = []
        for following in lines[index + 1:]:
            if not following.strip():
                raw.append("")
            elif following[:1] in (" ", "\t"):
                raw.append(following)
            else:
                break
        while raw and not raw[-1].strip():
            raw.pop()
        return "\n".join(raw), " ".join(part.strip() for part in raw)
    return None
# The catalog enumerates scopes as a backticked, comma/and-separated run after
# "checks across". Capture the run itself — not the rest of the sentence — so a
# scope dropped from the list cannot be rescued by a later backticked mention
# in the same sentence (e.g. "…`update`, plus a `config` playbook.").
_LABEL = r"`[^`]+`"
_SEP = r"(?:\s*,\s*(?:and\s+)?|\s+and\s+)"
_ENUM = re.compile(rf"(?i)\bchecks across\s+({_LABEL}(?:{_SEP}{_LABEL})*)")

# `hermes plugins list` renders this field in a ~20-column cell with no
# truncation: the 658-character v0.8.5 description produced 41 rows for one
# plugin. The cap keeps a row scannable; the longer mission text lives in
# README, which has no column to wrap.
MAX_DESCRIPTION_CHARS = 200


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
    """Flag a spelled count before "checks"/"scopes" that is not `expected`.

    Only the nearest spelled number in the ``_LOOKBACK`` words preceding the
    noun — and only within the noun's own sentence — is judged, and only when it
    is in the number vocabulary. So "read-only health checks" carries no count
    and is ignored, a number in an earlier sentence is not mistaken for one, and
    a phrase a Markdown renderer soft-wraps is still read as one phrase.
    """
    problems = []
    singular = kind.rstrip("s")
    for match in _COUNT_NOUN.finditer(text):
        if not match.group(1).lower().startswith(singular):
            continue
        segment = _CLAUSE_END.split(text[:match.start()])[-1]
        tokens = _WORD.findall(segment)[-_LOOKBACK:]
        nearest = next((t for t in reversed(tokens) if t.lower() in _NUM_WORDS), None)
        if nearest and nearest.lower() != expected:
            problems.append(
                f'{where}: says "{nearest} {kind}", but _CHECKS has {expected} '
                f"— correct the count or split the list"
            )
    return problems


def _set_problems(labels: list[str], listed: list[str], where: str) -> list[str]:
    """Compare a backticked run to `_CHECKS` in both directions."""
    missing = [label for label in labels if label not in listed]
    extra = [label for label in listed if label not in labels]
    if not missing and not extra:
        return []
    detail = []
    if missing:
        detail.append(f"missing {missing}")
    if extra:
        detail.append(f"unknown {extra}")
    return [f"{where}: the scope list does not match _CHECKS ({'; '.join(detail)})"]


def plugin_yaml_problems(labels: list[str], text: str) -> list[str]:
    """The description's backticked scope run must equal the `_CHECKS` set.

    If the description ever stops enumerating the scopes, drop this assertion
    rather than the list — an unenumerated description cannot drift, but it
    also tells the catalog reader less.

    Note the catalog labels are the identifiers (`mcp`), not the old prose
    names ("MCP servers"): a run can be compared as a set, whereas prose cannot
    — a whole-description search accepted "checks config files" as a listing of
    the `config` scope, and could never reject an unsupported extra scope.

    The folded scalar is also length-capped: `plugins list` gives it a narrow
    cell and no ellipsis, so a paragraph turns one row into dozens.
    """
    block = _description_scalar(text)
    if block is None:
        return ["plugin.yaml: no folded `description:` block found"]
    raw, value = block
    enum = _ENUM.search(raw)
    if not enum:
        return ["plugin.yaml: no 'checks across ...' scope list in the description"]
    problems = _set_problems(labels, _BACKTICK.findall(enum.group(1)), "plugin.yaml description")
    if len(value) > MAX_DESCRIPTION_CHARS:
        problems.append(
            f"plugin.yaml: description is {len(value)} characters; "
            f"the list column cap is {MAX_DESCRIPTION_CHARS}"
        )
    return problems


def router_skill_problems(labels: list[str], text: str) -> list[str]:
    """The `Valid scopes:` backtick run must equal the `_CHECKS` label set."""
    match = _SCOPES_BLOCK.search(text)
    if not match:
        return [f"{ROUTER_SKILL.name}: no 'Valid scopes:' block found"]
    where = "plugin-skills/start/SKILL.md 'Valid scopes:'"
    return _set_problems(labels, _BACKTICK.findall(match.group(1)), where)


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

    def manifest(scope_line: str) -> str:
        return (
            "name: hermes-guide\n"
            "description: >-\n"
            "  Executable diagnostics for Hermes configuration.\n"
            f"{scope_line}\n"
            "manifest_version: 1\n"
        )

    enumerated = manifest("  Deterministic health checks across `config`, `mcp`, `skills`.")
    # Prose naming a scope must NOT stand in for listing it: "config files" in
    # the intro cannot satisfy a list that omits `config`.
    prose_only = manifest("  Reads config files. Health checks across `mcp`, `skills`.")
    # An unsupported extra scope must fail, not pass.
    with_extra = manifest("  Health checks across `config`, `mcp`, `skills`, `tokens`.")
    # A backticked mention AFTER the list must not rescue a dropped label.
    rescued = manifest("  Health checks across `mcp`, `skills`, plus a `config` playbook.")
    # `plugins list` wraps without truncation, so a long scalar costs rows.
    too_long = manifest(
        "  Health checks across `config`, `mcp`, `skills`. " + "Detail. " * 30
    )
    # A blank line inside the block scalar must not hide the second paragraph
    # from the cap, and the scope run may live after the break.
    two_paragraphs = manifest(
        "  Intro paragraph.\n"
        "\n"
        "  Health checks across `config`, `mcp`, `skills`. " + "Detail. " * 30
    )
    enum_after_break = manifest(
        "  Intro paragraph.\n\n  Health checks across `config`, `mcp`, `skills`."
    )

    # (name, problems the guard should return, should it return any at all)
    cases: list[tuple[str, list[str], bool]] = [
        ("plugin: every label listed", plugin_yaml_problems(labels, enumerated), False),
        ("plugin: a label dropped from the list", plugin_yaml_problems(labels, prose_only), True),
        ("plugin: an extra unsupported label", plugin_yaml_problems(labels, with_extra), True),
        ("plugin: a dropped label later in the sentence", plugin_yaml_problems(labels, rescued), True),
        ("plugin: no description block", plugin_yaml_problems(labels, "name: x\n"), True),
        ("plugin: description over the list column cap", plugin_yaml_problems(labels, too_long), True),
        (
            "plugin: cap still applies after a blank line",
            plugin_yaml_problems(labels, two_paragraphs),
            True,
        ),
        (
            "plugin: scope run after a blank line",
            plugin_yaml_problems(labels, enum_after_break),
            False,
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
            "count: adjacent, correct",
            count_problems("runs all nine checks in-process", "nine", "checks", "README.md"),
            False,
        ),
        (
            "count: adjacent, stale",
            count_problems("runs all seven checks in-process", "nine", "checks", "README.md"),
            True,
        ),
        (
            "count: qualified, stale",
            count_problems("seven read-only health checks", "nine", "checks", "README.md"),
            True,
        ),
        (
            "count: qualified, correct",
            count_problems("nine read-only health checks", "nine", "checks", "README.md"),
            False,
        ),
        (
            "count: an adjective-only phrase carries no count",
            count_problems("read-only health checks across", "nine", "checks", "README.md"),
            False,
        ),
        (
            "count: a number in an earlier sentence is not this noun's count",
            count_problems("Twenty-two skills. Checks are read-only.", "nine", "checks", "README.md"),
            False,
        ),
        (
            "count: a soft-wrapped phrase is still one phrase",
            count_problems("seven read-only health\nchecks", "nine", "checks", "README.md"),
            True,
        ),
        (
            "count: a paragraph break bounds the segment",
            count_problems("Twenty-two skills\n\nChecks are read-only.", "nine", "checks", "README.md"),
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
