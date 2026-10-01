#!/usr/bin/env python3
"""Derive PR metadata labels (OS, priority, area) from a PR description.

Why this is not `.github/labeler.yml`: `actions/labeler` v5 matches changed
files, base branch and head branch only. Its match surface is `changed-files`
(four glob combinations), `base-branch` and `head-branch` -- there is no title
matcher and no body matcher, and `changed-title` was dropped in v5. So the
`## Environment` block and any `Priority:` line in a PR body are structurally
unreachable from the labeler config, and a separate reader is the only way to
honour them.

This reads the same `## Environment` section the PR template asks for:

    - OS / shell: macOS + zsh (POSIX) / Windows native + PowerShell

and an optional priority line, then maps them to labels that already exist (or
that the workflow creates on demand). The area labels stay in `labeler.yml`,
where changed-files is the correct matcher -- this tool does not duplicate them.

Design constraints, all deliberate:

* **Fail open.** A missing, empty or unrecognised description yields no labels
  and exit 0. A labelling helper must never fail a PR over a parse detail.
* **HTML comments are ignored.** The template's own guidance comments contain
  example values like `e.g. macOS`; reading them would label every PR as macOS.
* **No execution of description text.** The body is untrusted input, so values
  are matched against a fixed vocabulary with word boundaries rather than being
  interpolated into anything.
* **First match wins, per family.** A description naming two platforms labels
  both, because "verified on macOS, needs Windows confirmation" is a real
  cross-platform PR and collapsing it to one platform loses the signal.

Usage:
    python tools/pr_metadata_labels.py --body-file <path>   # read a file
    python tools/pr_metadata_labels.py --body-file -         # read stdin
    python tools/pr_metadata_labels.py --body - --json      # -body works too:
                                                       # argparse prefix-matches
    python tools/pr_metadata_labels.py --selftest

Exit codes: 0 labels produced or nothing to label (never a failure), 2 unusable
input (no body source given).
"""

from __future__ import annotations

import argparse
import json
import re
import sys

# Label vocabulary. Values are lowercase because GitHub labels are
# case-insensitive for matching but the repo's existing labels are lowercase
# (`windows`, not `Windows`), and a label that differs only in case is a second
# label in the UI.
OS_LABELS = ("macos", "linux", "windows", "wsl")
PRIORITY_LABELS = ("P1", "P2", "P3")

# Word-boundary patterns, longest/most specific first. Ordering matters only in
# that `wsl` must be tested before `linux`: "WSL" is a distinct environment, not
# a Linux host, and this repo maintains it separately from native Linux.
_OS_PATTERNS = (
    ("wsl", re.compile(r"\bwsl\b", re.I)),
    ("windows", re.compile(r"\bwindows\b", re.I)),
    ("macos", re.compile(r"\bmac\s?os\b|\bos\s?x\b|\bdarwin\b", re.I)),
    ("linux", re.compile(r"\blinux\b|\bubuntu\b|\bfedora\b|\bdebian\b", re.I)),
)

# Built from PRIORITY_LABELS so the vocabulary lives in exactly one place. A
# hand-written p[0-3] here would drift from the tuple above and silently accept
# a P0, which is not a label this repo defines.
_PRIORITY_LINE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?\s*priority\s*(?:\(p([0-3])\))?\s*(?:\*\*)?\s*:?\s*"
    r"(?:\*\*)?\s*(p([0-3]))?\b",
    re.I,
)

# The environment assertion is a specific line, not a phrase anywhere. Without
# anchoring to the key, a code sample or a discussion sentence mentioning
# another platform would label the PR with an environment the author never
# claimed. ``[e.g. macOS + zsh (POSIX) / Linux + bash / ...]`` is the template's
# own placeholder form, so a value still bracketed is not read as a claim.
_OS_LINE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?\s*OS\s*(?:/|and)\s*shell\s*(?:\*\*)?\s*:\s*"
    r"(?P<value>.+?)\s*$",
    re.I,
)
_PLACEHOLDER_RE = re.compile(r"[\[<]")

# A fenced block is an example, not an assertion. ``~~~`` fences are valid
# Markdown too, and an info string (```text) is common on a shell example.
FENCE_RE = re.compile(r"^\s*(?:```|~~~)")

_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def strip_comments(text: str) -> str:
    """Drop HTML comments so the template's own examples are not read as values."""
    return _COMMENT_RE.sub("", text)


def os_labels(body: str) -> list[str]:
    """Every platform the body actually asserts, in vocabulary order.

    Three rules keep it from over-labelling, each from a real false positive:

    * Only the ``OS / shell:`` line counts, and only the value after it. The PR
      template ships that line as a bracketed placeholder --
      ``- OS / shell: [e.g. macOS + zsh (POSIX) / Linux + bash / ...]`` -- so an
      unfilled template would otherwise name all four platforms and stamp every
      untouched PR with four contradictory OS labels.
    * A value still inside ``[]`` or ``<>`` is a placeholder, not a claim.
    * Fenced code blocks are skipped. A PR that documents a Windows example
      (`````\\n- OS / shell: Windows native + PowerShell\\n`````) is describing
      something, not asserting its own environment, and would otherwise collect
      both platforms.
    """
    found: set[str] = set()
    in_fence = False
    for line in body.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _OS_LINE_RE.match(line)
        if not match:
            continue
        value = match.group("value")
        if _PLACEHOLDER_RE.search(value):
            continue
        for name, pattern in _OS_PATTERNS:
            if pattern.search(value):
                found.add(name)
    return [label for label in OS_LABELS if label in found]


def priority_label(body: str) -> str | None:
    """First ``Priority: PN`` line outside a fenced block, if any.

    Fenced blocks are skipped for the same reason ``os_labels`` skips them: a PR
    that shows a priority line as an example is documenting it, not claiming it.

    The regex only recognises the shape; this is what enforces that the value is
    a label this repo actually defines.
    """
    in_fence = False
    for line in body.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _PRIORITY_LINE_RE.match(line)
        if not match:
            continue
        value = match.group(2) or match.group(1)
        if value is None:
            continue
        candidate = value.upper()
        if candidate in PRIORITY_LABELS:
            return candidate
    return None


def derive_labels(body: str) -> list[str]:
    """OS and priority labels for a raw PR description.

    Ordered OS then priority, which is the order the template presents them and
    keeps output stable across runs.
    """
    text = strip_comments(body or "")
    labels = os_labels(text)
    priority = priority_label(text)
    if priority:
        labels.append(priority)
    return labels


def _selftest() -> int:
    # (description, expected, note)
    cases = [
        ("- OS / shell: macOS + zsh (POSIX)", ["macos"], "template's first example"),
        ("- OS / shell: Windows native + PowerShell", ["windows"], "template's example"),
        ("- OS / shell: Linux + bash", ["linux"], "template's example"),
        ("- OS / shell: WSL", ["wsl"], "WSL is its own environment"),
        ("- OS / shell: WSL (Linux)", ["linux", "wsl"],
         "names both; output follows OS_LABELS order, not mention order"),
        ("- OS / shell: macOS\n- Priority: P1", ["macos", "P1"], "both families"),
        ("**Priority:** P2", ["P2"], "bold key, no bullet"),
        ("- Priority (P2): p2", ["P2"], "parenthesised hint, lowercase value"),
        ("Priority: P3\n\nSome body.", ["P3"], "bare key on its own line"),
        ("", [], "empty body fails open"),
        ("Nothing structured here.", [], "no vocabulary hit"),
        ("<!-- OS / shell: e.g. macOS + zsh -->", [],
         "template comment must not label every PR as macOS"),
        ("Refactor.\n\n- OS / shell: macOS", ["macos"],
         "value later in the body still counts"),
        ("- OS / shell: Darwin", ["macos"], "Darwin is macOS"),
        ("- OS / shell: OS X", ["macos"], "legacy spelling"),
        ("- Priority: P0", [], "P0 is outside the vocabulary"),
        ("- Priority: P4", [], "P4 is outside the vocabulary"),
        ("- priority: p1", ["P1"], "case-insensitive key and value"),
        ("- OS / shell: Windows\n- Priority: P2",
         ["windows", "P2"], "ordering is OS then priority"),
        ("- OS / shell: macOS and Linux", ["macos", "linux"],
         "vocabulary order, not mention order"),
        ("See <!-- P1 --> later\n- OS / shell: macOS", ["macos"],
         "commented priority is ignored"),
        # The template's own unfilled line must yield nothing. This is the case
        # that made an untouched PR pick up all four platforms at once.
        ("- OS / shell: [e.g. macOS + zsh (POSIX) / Linux + bash / "
         "Windows native + PowerShell / WSL]", [],
         "unfilled template placeholder is not a claim"),
        ("- OS / shell: [macOS]", [], "bracketed single value is still a placeholder"),
        ("- OS / shell: macOS", ["macos"], "the same key with a real value still works"),
        ("- OS / shell: macOS (verified)", ["macos"],
         "parenthesised note around a real value is not a placeholder"),
        ("This mentions Windows in prose but asserts no OS line.", [],
         "a platform named outside the key line is not an environment claim"),
        ("- OS and shell: Linux + bash", ["linux"], "key spelled with 'and'"),
        # Fenced examples. A PR that documents a Windows example is describing
        # something, not asserting its own environment.
        ("- OS / shell: macOS\n\n```text\n- OS / shell: Windows native\n```",
         ["macos"], "OS line inside a fenced block is an example"),
        ("- OS / shell: macOS\n\n~~~\n- OS / shell: Linux\n~~~",
         ["macos"], "~~~ fences count too"),
        ("- OS / shell: macOS\n\n```\n- Priority: P1\n```",
         ["macos"], "Priority inside a fenced block is an example"),
        ("```\n- OS / shell: Windows\n```\n- OS / shell: macOS",
         ["macos"], "fence before the real assertion is skipped"),
        ("- Priority: P1\n```\nunclosed fence\n- Priority: P2",
         ["P1"], "unclosed fence still skips what follows"),
        # A fence toggles, so a CLOSED pair must not latch the skip on: the
        # Windows line is fenced out, the macOS line after it is not.
        ("```\n- OS / shell: Windows\n```\n- OS / shell: macOS\n```",
         ["macos"], "closed fences toggle rather than latch"),
    ]

    failures = []
    for body, expected, note in cases:
        actual = derive_labels(body)
        if actual != expected:
            failures.append((body, expected, actual, note))
            print(f"FAIL: {body!r}")
            print(f"      expected={expected}  actual={actual}  ({note})")
    total = len(cases)
    if failures:
        print(f"FAIL: {len(failures)}/{total} pr-metadata label cases wrong")
        return 1
    print(f"OK: {total}/{total} pr-metadata label cases correct")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Derive OS/priority labels from a PR description.")
    parser.add_argument("--body-file", help="path to the PR description ('-' for stdin)")
    parser.add_argument("--json", action="store_true", help="emit JSON, not one label per line")
    parser.add_argument("--selftest", action="store_true",
                        help="regression-check the detector and exit")
    args = parser.parse_args(argv)

    if args.selftest:
        return _selftest()

    if not args.body_file:
        print("error: --body-file is required (or use --selftest)", file=sys.stderr)
        return 2

    if args.body_file == "-":
        body = sys.stdin.read()
    else:
        try:
            with open(args.body_file, encoding="utf-8", errors="replace") as handle:
                body = handle.read()
        except OSError as exc:
            # An unreadable description is unusable input, but it is not a repo
            # defect, so this stays exit 2 (the documented "unusable input" code)
            # rather than raising.
            print(f"error: cannot read body file: {exc}", file=sys.stderr)
            return 2

    labels = derive_labels(body)
    if args.json:
        print(json.dumps(labels))
    else:
        for label in labels:
            print(label)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
