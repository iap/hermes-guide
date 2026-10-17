#!/usr/bin/env python3
"""Fail if the repository's line-ending contract stops being true.

`.gitattributes` (added in #277) is a declaration, so nothing else in the tree
notices when it is loosened: drop `eol=lf` and a Windows clone quietly checks
out CRLF again, every touched file becomes a whole-file diff, and the one
tracked shell script (`skills/diagnosing-host-pressure/scripts/host_pressure_probe.sh`)
stops executing. Drop the `binary` marking and a 190 KB README banner turns
into a text diff and an EOL-conversion candidate.

Two layers are checked, because either can rot on its own:

1. **The declaration.** The rules the tracked tree actually depends on must be
   present. Deliberately a short list: `*.bat`/`*.cmd`/`*.ps1` CRLF rules are
   documented but NOT required, because no tracked file uses them and a
   requirement with no dependent file is a test of the file's own text.
2. **The resolved attributes plus the index**, from `git ls-files --eol`.

Layer 2 is defence in depth, not the primary detector, and the reason is worth
stating so nobody over-trusts it: while `text=auto eol=lf` holds, git
NORMALIZES on `git add`, so a CRLF file is stored as `i/lf` and no CRLF index
entry can exist to find (verified: a hand-written CRLF blob adds as `i/lf`).
What layer 2 actually catches is:

  * a dropped `binary` rule -- git's own content heuristic keeps the JPEG at
    `i/-text` either way, so only the resolved-attribute column flips
    (`attr/-text` -> `attr/text=auto eol=lf`) and that is what is compared;
  * a text path git classified as binary (a stray CR or a NUL byte);
  * an asset that became text in the index;
  * `i/mixed`, and `i/crlf` once `eol=lf` has been dropped.

`i/none` is accepted for text: git reports it when a blob has no line
terminator at all (an empty file, or a single line with no trailing newline --
`.github/upstream-drift.baseline` is one). It cannot hide CRLF, because CRLF
implies a terminator, and a terminator makes git report `i/lf` or `i/crlf`.

Unusable input is reported, never skipped: a missing or undecodable
`.gitattributes`, a failed `git ls-files`, empty output, and any row without
git's TAB path separator all exit 2. That last one matters: the attribute
column carries two tokens (`text=auto eol=lf`), so an untabbed row cannot be
split safely -- guessing would report the wrong path, and skipping would turn
a future git format change into an all-green run.

Usage:
    python tools/check_eol_contract.py            # check the repo

Exit codes: 0 clean, 1 contract violated, 2 unusable input (git/`.gitattributes`/format).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Paths under this prefix are expected to be binary whatever their suffix.
BINARY_PREFIX = "assets/"

# Suffixes `.gitattributes` marks `binary`. A declared type is expected to be
# binary wherever it lives, so adding `docs/diagram.png` does not need a guard
# edit. Case-folded: a Windows checkout can commit either casing.
BINARY_SUFFIXES = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".ico", ".pdf", ".zip")

# Rule lines the tracked tree depends on, as ordered token prefixes. A line
# satisfies a requirement when its tokens start with the requirement, so extra
# attributes on the same line (`* text=auto eol=lf diff=x`) still count.
REQUIRED_RULES: tuple[tuple[str, ...], ...] = (
    ("*", "text=auto", "eol=lf"),
    ("*.sh", "text", "eol=lf"),
    ("*.jpg", "binary"),
    ("*.png", "binary"),
)

# `git ls-files --eol` columns: index EOL, worktree EOL, resolved attributes,
# then the path. The first three are whitespace-separated (the attribute column
# is `attr/text=auto eol=lf`, two tokens) and the path follows a TAB.
_EOL_ATTR_NO_TEXT = "-text"

# The one resolved attribute this repo never wants on a tracked path. The
# `*.bat`/`*.cmd`/`*.ps1` rules in `.gitattributes` would produce it, which is
# why they are documented but not required: nothing tracked uses them yet.
_EOL_CRLF = "eol=crlf"

# Index states acceptable for a text path.
_TEXT_INDEX_OK = ("i/lf", "i/none")

_BINARY_INDEX = "i/-text"


def read(path: Path) -> str | None:
    """Return the file's text, or None when it cannot be read or decoded."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def missing_rules(text: str) -> list[str]:
    """Return the required rules *text* does not declare.

    Comments and blank lines are skipped, and tokens are compared
    whitespace-wise, so a CRLF copy of the file satisfies the same rules.
    """
    declared: list[tuple[str, ...]] = []
    for line in text.splitlines():
        tokens = line.split()
        if not tokens or tokens[0].startswith("#"):
            continue
        declared.append(tuple(tokens))
    missing = []
    for rule in REQUIRED_RULES:
        if not any(line[: len(rule)] == rule for line in declared):
            missing.append(" ".join(rule))
    return missing


def parse_eol_line(line: str) -> tuple[str, str, str] | None:
    """Return ``(index_eol, attr, path)``, or None when the row is unusable.

    The attribute column is everything after the second field, joined back
    together: it is `attr/-text` for a binary blob but `attr/text eol=lf` (two
    tokens) for text, and dropping the second token loses the very `eol=crlf`
    this guard exists to catch. A row without git's TAB path separator returns
    None rather than a guess -- whitespace alone cannot say where the path
    begins, because the attribute column holds two tokens.
    """
    info, tab, path = line.partition("\t")
    if not tab:
        return None
    fields = info.split()
    if len(fields) < 3:
        return None
    return fields[0], " ".join(fields[2:]), path.strip()


def split_entries(payload: str) -> list[str]:
    """Split NUL-delimited `git ls-files --eol -z` output into rows."""
    return [entry for entry in payload.split("\0") if entry.strip()]


def expects_binary(path: str) -> bool:
    """True when *path* must be binary: under assets/, or a declared type."""
    if path.startswith(BINARY_PREFIX):
        return True
    return path.casefold().endswith(BINARY_SUFFIXES)


def eol_problems(eol_output: str) -> tuple[list[str], int, list[str]]:
    """Return ``(problems, tracked_count, unusable)`` for ls-files --eol -z output.

    A row that cannot be parsed lands in `unusable` rather than being dropped:
    see the module docstring for why a silent skip is worse than a red build.
    """
    problems: list[str] = []
    unusable: list[str] = []
    tracked = 0
    for line in split_entries(eol_output):
        parsed = parse_eol_line(line)
        if parsed is None:
            unusable.append(f"cannot tell where the path starts in: {line.strip()!r}")
            continue
        index, attr, path = parsed
        tracked += 1

        # git normalizes the index, so a later rule that overrides eol=lf
        # leaves an LF index and a CRLF checkout. Only the resolved attribute
        # shows the override, which is why no tracked path may resolve to one.
        if _EOL_CRLF in attr:
            problems.append(
                f"{path}: resolves to {attr!r}; every tracked path must check "
                "out LF, so no rule may set eol=crlf"
            )
            continue

        if expects_binary(path):
            # The declaration is the signal, not the index column: git reports
            # `i/-text` for a binary blob but `i/none` for a small one with no
            # terminator to classify, so keying on the index false-positives on
            # a legitimate tiny asset.
            if _EOL_ATTR_NO_TEXT not in attr:
                problems.append(
                    f"{path}: attribute is {attr!r}, expected a `binary` "
                    f"(or -text) rule; git may keep the blob binary by content "
                    f"heuristic alone (index EOL {index}), which is not a "
                    "declaration"
                )
        elif index == _BINARY_INDEX:
            # Binary because a rule says so (`attr/-text`) is a declaration and
            # is accepted even for a type this guard has never heard of, so
            # adding `docs/demo.webm` with its own `binary` rule needs no guard
            # edit. Binary with only `attr/text=auto eol=lf` is git's content
            # heuristic -- a stray CR or a NUL byte in what should be text.
            if _EOL_ATTR_NO_TEXT not in attr:
                problems.append(
                    f"{path}: git treats this text path as binary ({attr}); "
                    "check for a stray CR or a NUL byte"
                )
        elif index not in _TEXT_INDEX_OK:
            problems.append(f"{path}: index EOL is {index}, expected i/lf")
    return problems, tracked, unusable


def audit(root: Path, eol_output: str) -> tuple[int, list[str]]:
    """Return ``(exit_code, messages)`` for the tree rooted at *root*."""
    text = read(root / ".gitattributes")
    if text is None:
        return 2, ["cannot read .gitattributes"]
    if not eol_output.strip():
        return 2, ["empty `git ls-files --eol` output (git failed or the tree is empty)"]

    problems, tracked, unusable = eol_problems(eol_output)
    if unusable:
        return 2, unusable + [
            "refusing to guess the column layout; `git ls-files --eol` no longer "
            "separates the path with a TAB, so this guard cannot read it"
        ]

    problems = [f".gitattributes does not declare: {rule}" for rule in missing_rules(text)] + problems
    if problems:
        return 1, problems
    return 0, [
        f"LF index contract holds across {tracked} tracked path(s); "
        f"{BINARY_PREFIX} and declared binary types stay binary"
    ]


def ls_files_eol(root: Path) -> tuple[str | None, str | None]:
    """Return ``(output, problem)`` for `git ls-files --eol` in *root*."""
    try:
        proc = subprocess.run(
            ["git", "ls-files", "--eol", "-z"],
            cwd=root, capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"cannot run git ls-files --eol: {exc}"
    if proc.returncode != 0:
        detail = proc.stderr.strip() or str(proc.returncode)
        return None, f"git ls-files --eol failed: {detail}"
    return proc.stdout, None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args()

    eol_output, problem = ls_files_eol(REPO)
    if problem is not None:
        print(f"error: {problem}", file=sys.stderr)
        return 2

    code, messages = audit(REPO, eol_output or "")
    if code == 0:
        print(f"OK: {messages[0]}")
        return 0
    stream = sys.stderr
    for message in messages:
        print(f"{'error' if code == 2 else 'FAIL'}: {message}", file=stream)
    if code == 1:
        print(
            "error: line-ending contract violated; fix .gitattributes and "
            "renormalize the index in the same commit",
            file=stream,
        )
    return code


if __name__ == "__main__":
    sys.exit(main())
