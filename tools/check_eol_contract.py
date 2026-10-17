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
2. **The index.** `git ls-files --eol` must report `i/lf` for every tracked
   text path and `i/-text` for everything under `assets/`. The index is the
   state that gets committed; the worktree column is deliberately ignored,
   since a CRLF worktree on Windows is expected and harmless.

`i/none` is accepted for text: git reports it for the BOM-prefixed
`.github/upstream-drift.baseline`, which is text and correctly LF-clean.

Unusable input is reported, never skipped: a missing or undecodable
`.gitattributes`, a failed `git ls-files`, or empty output all exit 2.

Usage:
    python tools/check_eol_contract.py            # check the repo

Exit codes: 0 clean, 1 contract violated, 2 unusable input (git/`.gitattributes`).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Paths under this prefix must be binary in the index.
BINARY_PREFIX = "assets/"

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
# then the path — which may contain spaces, so it is the last field.
_EOL_LINE = re.compile(r"^(?P<index>\S+)\s+\S+\s+\S+\s+(?P<path>\S.*?)\s*$")

# Index states acceptable for a text path. `i/crlf` and `i/mixed` are the
# violations; `i/none` is git's report for text it cannot line-classify.
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


def eol_problems(eol_output: str) -> tuple[list[str], int]:
    """Return ``(problems, tracked_count)`` for `git ls-files --eol` output.

    Unparseable lines are ignored rather than failed: the column layout is a
    git implementation detail, and a new column must not turn every clone into
    a red build. Empty output is handled by the caller as unusable input.
    """
    problems: list[str] = []
    tracked = 0
    for line in eol_output.splitlines():
        if not line.strip():
            continue
        match = _EOL_LINE.match(line)
        if match is None:
            continue
        index, path = match["index"], match["path"]
        tracked += 1
        if path.startswith(BINARY_PREFIX):
            if index != _BINARY_INDEX:
                problems.append(
                    f"{path}: index EOL is {index}, expected {_BINARY_INDEX} "
                    "(mark the asset binary in .gitattributes)"
                )
        elif index not in _TEXT_INDEX_OK:
            problems.append(f"{path}: index EOL is {index}, expected i/lf")
    return problems, tracked


def audit(root: Path, eol_output: str) -> tuple[int, list[str]]:
    """Return ``(exit_code, messages)`` for the tree rooted at *root*."""
    text = read(root / ".gitattributes")
    if text is None:
        return 2, ["cannot read .gitattributes"]
    if not eol_output.strip():
        return 2, ["empty `git ls-files --eol` output (git failed or the tree is empty)"]

    problems = [f".gitattributes does not declare: {rule}" for rule in missing_rules(text)]
    eol_found, tracked = eol_problems(eol_output)
    problems.extend(eol_found)

    if problems:
        return 1, problems
    return 0, [
        f"LF index contract holds across {tracked} tracked path(s); "
        f"{BINARY_PREFIX} stays binary"
    ]


def ls_files_eol(root: Path) -> tuple[str | None, str | None]:
    """Return ``(output, problem)`` for `git ls-files --eol` in *root*."""
    try:
        proc = subprocess.run(
            ["git", "ls-files", "--eol"],
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
