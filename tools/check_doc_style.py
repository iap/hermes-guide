#!/usr/bin/env python3
"""Enforce the repo's tone rules where they are mechanically decidable.

Why this exists
---------------
CONTRIBUTING.md states the tone standard (no filler, no emoji in prose) and
AGENTS.md states it for agents. A rule nothing checks decays — this repo has
already paid that cost once, when hand-maintained counts in three prose files
drifted apart (see tools/render_docs.py for the fix). So the two halves that
CAN be decided from the working tree are decided here.

What is gated
-------------
1. **Emoji in Python source, outside string literals.** Zero legitimate uses
   today outside one place: `checks.py` parses the hook markers that
   `hermes hooks doctor` prints, so those glyphs are a protocol dependency. The
   exemption is scoped to literals for that reason — a glyph in a comment is
   decoration, and a glyph in a regex is something the code matches. Scope is
   `git ls-files '*.py'`, which also covers `skills/*/scripts/`. Typographic
   characters are fine and deliberately allowed: em dash, ellipsis and section
   sign all appear in this repo's docstrings on purpose.
2. **Filler phrases in Markdown prose.** A closed deny-list, so the signal stays
   unambiguous. Scanned against prose only — fenced code blocks and inline code
   spans are stripped first, which is what lets a skill quote an example of bad
   phrasing, or transcribe CLI output containing a glyph, without tripping it.

What is NOT gated, deliberately
-------------------------------
Emoji in Markdown *prose*, commit messages, and PR bodies. Every existing
exception here is either pedagogical (CONTRIBUTING.md's own good/bad examples)
or quoted output (the ✔ glyphs that skills transcribe from the Hermes TUI), so a
prose check needs a per-file allowlist — which rots exactly the way the
hand-maintained counts did. The rule is stated in CONTRIBUTING.md with its
carve-out; the parts with a clean signal are enforced here.

Usage
-----
    python tools/check_doc_style.py            # enforce (exit 1 on a finding)
    python tools/check_doc_style.py --selftest # fixture test, no repo scan

Exit codes: 0 clean; 1 a finding; 2 an unusable scan target (git unavailable, or
nothing to scan — never reported as clean, so a mistyped path cannot bypass it).
"""

from __future__ import annotations

import argparse
import io
import re
import subprocess
import sys
import tokenize
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Pictograph / dingbat ranges. Deliberately excludes U+2014 EM DASH, U+2026
# HORIZONTAL ELLIPSIS and U+00A7 SECTION SIGN, which this repo uses in prose.
EMOJI_RANGES: tuple[tuple[int, int], ...] = (
    (0x1F000, 0x1FAFF),  # pictographs, symbols, regional indicators
    (0x2600, 0x27BF),  # misc symbols + dingbats: check marks, warning signs
    (0x2B00, 0x2BFF),  # misc symbols and arrows: stars, blocks
    (0xFE00, 0xFE0F),  # variation selectors that force emoji presentation
)

# Cheerful filler with no informational content. Each entry is specific enough
# that no honest technical sentence trips it; the terminator requirement on the
# interjections keeps "of course" from firing on "of course there is a caveat".
FILLER: tuple[tuple[str, str], ...] = (
    (r"\bthanks?\s+so\s+much\b", "thanks so much"),
    (
        r"\bthanks?\s+for\s+(?:your\s+)?(?:question|asking|reading)\b",
        "thanks for asking",
    ),
    (r"\bgreat\s+question\b", "great question"),
    (r"\bhappy\s+to\s+help\b", "happy to help"),
    (r"\bglad\s+to\s+help\b", "glad to help"),
    (r"\bi(?:'d| would)\s+be\s+happy\b", "I'd be happy"),
    (r"\bhope\s+this\s+helps\b", "hope this helps"),
    (r"\bi\s+hope\s+(?:this|that)\s+helps\b", "I hope this helps"),
    (r"\bfeel\s+free\s+to\s+(?:ask|reach\s+out|holler)\b", "feel free to ask"),
    (
        r"\b(?:of\s+course|certainly|absolutely|alright|sure\s+thing)\s*[!.]",
        "sure! / certainly!",
    ),
    (r"\bno\s+problem\s*[!.]", "no problem!"),
    (r"\bno\s+worries\b", "no worries"),
    (r"\byou'?re\s+welcome\b", "you're welcome"),
    (r"\bmy\s+apologies\b", "my apologies"),
    (r"\bi\s+apologize\b", "I apologize"),
    (r"\bas\s+an\s+ai\b", "as an AI"),
)


def emoji_in(text: str) -> list[str]:
    """Distinct emoji/pictograph characters present, in first-seen order."""
    seen: list[str] = []
    for ch in text:
        cp = ord(ch)
        if any(lo <= cp <= hi for lo, hi in EMOJI_RANGES) and ch not in seen:
            seen.append(ch)
    return seen


def _is_string_token(token_type: int) -> bool:
    """True for STRING and every FSTRING_* part (3.12+ splits f-strings)."""
    name = tokenize.tok_name.get(token_type, "")
    return name == "STRING" or name.startswith("FSTRING")


def emoji_outside_strings(src: str) -> list[tuple[int, list[str]]]:
    """(lineno, glyphs) for emoji in any token that is NOT a string literal.

    The string-literal exemption is load-bearing, not a loophole: `checks.py`
    parses the ✗/⚠ markers that `hermes hooks doctor` prints, so those glyphs are
    a protocol dependency and removing them breaks the check. Restricting the
    exemption to literals keeps that case working while still refusing emoji
    everywhere decoration hides — notably comments, where a bare "# ✗" is
    exactly the thing that should be written "# U+2717 BALLOT X" instead.
    """
    findings: list[tuple[int, list[str]]] = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return findings
    for tok in tokens:
        if _is_string_token(tok.type):
            continue
        found = emoji_in(tok.string)
        if found:
            findings.append((tok.start[0], found))
    return findings


# Markdown lets a fence or a list item sit inside a block quote, and lets a
# doc quote a fence inside a list item, so the container marker has to come off
# before the delimiter can be recognised. Without this a fence nested in a list
# item is invisible: its body is read as prose.
_CONTAINER_PREFIX = re.compile(r"^(?:(?:\s*>\s?)|(?:\s*(?:[-+*]|\d+[.)])\s+))+")

# A code span opens with a run of N backticks and closes only on a run of
# exactly N (CommonMark 6.1). The naive `[^`]*` body also matches a newline,
# which both leaks quoted text into the prose and renumbers every line after a
# span that happens to straddle one.
_CODE_SPAN = re.compile(r"(`+)(?:(?!\1).)*\1")


def prose_only(text: str) -> str:
    """Markdown prose with fenced code blocks and inline code spans removed.

    Both are places where a glyph is quoted rather than used: a skill
    transcribing `hermes` output, or a doc showing an example of phrasing to
    avoid. Refusing those would force the carve-out to grow into an allowlist.

    Line numbers are preserved: a span is replaced in place rather than
    deleted, so a finding on line N is still reported as line N.
    """
    kept: list[str] = []
    # (marker char, delimiter length). The length is load-bearing: inside a
    # four-backtick block a three-backtick line is CONTENT, not the closer
    # (CommonMark 4.5), so a shorter fence must not end the block.
    fence: tuple[str, int] | None = None
    for line in text.splitlines():
        stripped = _CONTAINER_PREFIX.sub("", line).lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[0]
            length = len(stripped) - len(stripped.lstrip(marker))
            if fence is None:
                fence = (marker, length)
            elif marker == fence[0] and length >= fence[1]:
                fence = None
            # The delimiter line is blanked, not dropped. Dropping it would
            # renumber every line after the block, and a finding cites a line
            # its reader then opens -- so the number has to be the real one.
            kept.append("")
            continue
        if fence is not None:
            kept.append("")
            continue
        kept.append(line)
    return _CODE_SPAN.sub(" ", "\n".join(kept))


def filler_hits(text: str) -> list[tuple[int, str, str]]:
    """(lineno, phrase, line) for each deny-listed phrase in Markdown prose."""
    hits: list[tuple[int, str, str]] = []
    for lineno, line in enumerate(prose_only(text).splitlines(), 1):
        low = line.lower()
        for pattern, label in FILLER:
            if re.search(pattern, low, re.IGNORECASE):
                hits.append((lineno, label, line.strip()))
    return hits


def tracked(pattern: str) -> list[Path]:
    """Tracked files matching a git pathspec. Raises if git cannot answer."""
    proc = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", pattern],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git ls-files failed: {proc.stderr.strip() or proc.returncode}"
        )
    return [REPO / ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]


def scan() -> list[str]:
    """Return one message per finding; empty means clean."""
    py_files = tracked("*.py")
    md_files = tracked("*.md")
    if not py_files or not md_files:
        raise RuntimeError(
            "nothing to scan (no tracked .py or .md) - refusing to report clean"
        )

    problems: list[str] = []
    for path in py_files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            problems.append(
                f"{path.relative_to(REPO)}: unreadable ({type(exc).__name__})"
            )
            continue
        found = emoji_outside_strings(text)
        if found:
            for lineno, glyphs in found:
                shown = " ".join(f"{c!r} U+{ord(c):04X}" for c in glyphs)
                problems.append(
                    f"{path.relative_to(REPO)}:{lineno}: emoji outside a string literal "
                    f"({shown}) - name the codepoint in a comment, or use a \\uXXXX escape"
                )

    for path in md_files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            problems.append(
                f"{path.relative_to(REPO)}: unreadable ({type(exc).__name__})"
            )
            continue
        for lineno, label, line in filler_hits(text):
            problems.append(
                f"{path.relative_to(REPO)}:{lineno}: filler ({label}) - {line[:70]}"
            )
    return problems


# --- selftest --------------------------------------------------------------

_PROSE_CASES: list[tuple[str, int, str]] = [
    # (markdown, expected number of filler hits, description)
    ("The check returns an envelope.\n", 0, "clean technical prose"),
    ("Thanks so much for the detailed report!\n", 1, "thanks so much"),
    ("Great question - let us look at the resolver.\n", 1, "great question"),
    ("Of course there is a caveat.\n", 0, "'of course' without a terminator"),
    ("Of course!\n", 1, "'of course!' as an interjection"),
    ("```\nThanks so much!\n```\n", 0, "filler inside a fenced block"),
    ("~~~\nGreat question\n~~~\n", 0, "filler inside a tilde fence"),
    (
        "Use the phrase `thanks so much` as the counter-example.\n",
        0,
        "filler in an inline code span",
    ),
    ('- ✅ "Skills track the source"\n', 0, "emoji marker is not prose filler"),
    # --- code spans: the delimiter run length decides the match (CommonMark 6.1)
    (
        "The doc quotes ``Thanks so much for the review!`` verbatim.\n",
        0,
        "filler in a two-backtick code span",
    ),
    (
        "Quoted: ```Great question``` here.\n",
        0,
        "filler in a three-backtick code span",
    ),
    # --- fences: a shorter fence is content, not the closer (CommonMark 4.5)
    (
        "````markdown\n```\nThanks so much!\n````\n",
        0,
        "three-backtick line inside a four-backtick block",
    ),
    (
        "~~~~markdown\n~~~\nGreat question\n~~~~\n",
        0,
        "three-tilde line inside a four-tilde block",
    ),
    (
        "`````markdown\n```\nThanks so much!\n`````\n",
        0,
        "three-backtick line inside a five-backtick block",
    ),
    # --- fences nested in containers need the marker stripped first
    (
        "- ```\n  Thanks so much!\n  ```\n",
        0,
        "filler in a fence nested in a list item",
    ),
    (
        "1. ```\n   Great question\n   ```\n",
        0,
        "filler in a fence nested in an ordered list item",
    ),
    (
        "> ```\n> Thanks so much!\n> ```\n",
        0,
        "filler in a fence nested in a block quote",
    ),
    # --- a span straddling a newline must not renumber later lines
    (
        "line one\n`code span\ncontinues here`\nline four\nThanks so much!\n",
        1,
        "multi-line code span still reports the right line",
    ),
]

# Line numbers are load-bearing: a finding cites a line a human then opens, so
# an off-by-one sends them to the wrong line. Asserted separately from the
# counts because every other case would still pass with the number wrong.
_PROSE_LINENO_CASES: list[tuple[str, int, str]] = [
    ("Thanks so much!\n", 1, "single line"),
    (
        "Intro.\n```\ncode\n```\nThanks so much!\n",
        5,
        "after a fenced block",
    ),
    (
        "Intro.\n`a`\n`code span\ncontinues here`\nThanks so much!\n",
        5,
        "after a multi-line code span",
    ),
    (
        "- item\n\n  ```\n  code\n  ```\n\nThanks so much!\n",
        7,
        "after a list-nested fenced block",
    ),
]

_EMOJI_CASES: list[tuple[str, list[int], str]] = [
    # (python source, expected flagged line numbers, description)
    ("plain ascii source\n", [], "ascii"),
    ("# comment - em dash \u2014 is fine\n", [], "em dash allowed"),
    ("s = '\u00a7 \u2026'\n", [], "section sign + ellipsis allowed"),
    ('mark = "\u2717"\n', [], "protocol glyph inside a string literal allowed"),
    ('re.findall(r"\\s+[\u2717\u26a0]", out)\n', [], "hook-marker regex allowed"),
    ('mark = "\\u2717"\n', [], "escape sequence is ascii"),
    ("# trailing comment \u2717\n", [1], "glyph in a comment flagged"),
    ('mark = "\u2717"  # \u2717\n', [1], "string allowed, comment flagged"),
    ("x = '\u2705'\n", [], "emoji inside a string literal allowed"),
    ("# ok \u2705\n", [1], "white heavy check mark in a comment flagged"),
    ("# bad \u274c\n", [1], "cross mark in a comment flagged"),
    ("# star \u2b50\n", [1], "black star in a comment flagged"),
]


def _selftest() -> int:
    fails = 0
    for md, expected, label in _PROSE_CASES:
        count = len(filler_hits(md))
        if count != expected:
            print(
                f"selftest FAIL ({label}): expected {expected} filler hit(s), got {count}"
            )
            fails += 1
    for md, expected, label in _PROSE_LINENO_CASES:
        hits = filler_hits(md)
        lineno = hits[0][0] if hits else None
        if lineno != expected:
            print(
                f"selftest FAIL ({label}): expected line {expected}, got {lineno!r}"
            )
            fails += 1
    for src, expected_lines, label in _EMOJI_CASES:
        found_lines = [lineno for lineno, _ in emoji_outside_strings(src)]
        if found_lines != expected_lines:
            print(
                f"selftest FAIL ({label}): expected lines {expected_lines!r}, "
                f"got {found_lines!r}"
            )
            fails += 1

    total = len(_PROSE_CASES) + len(_PROSE_LINENO_CASES) + len(_EMOJI_CASES)
    if fails:
        return 1
    print(f"selftest OK ({total} cases)")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):  # pragma: no cover
            pass

    ap = argparse.ArgumentParser(description="Enforce the repo's tone rules")
    ap.add_argument("--selftest", action="store_true", help="run the fixture test")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    try:
        problems = scan()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if problems:
        print("Tone findings:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        print(
            "Rules in CONTRIBUTING.md (Tone and artifact rules). Filler inside fenced\n"
            "blocks or inline code spans is allowed; emoji in prose and Python source\n"
            "is not.",
            file=sys.stderr,
        )
        return 1

    print(f"style: no emoji in Python source, no filler in Markdown prose")
    return 0


if __name__ == "__main__":
    sys.exit(main())
