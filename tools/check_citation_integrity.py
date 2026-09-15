#!/usr/bin/env python3
"""Verify every source citation in the guide's ``skills/*/SKILL.md`` files.

Why this exists
---------------
This guide's value proposition is traceability: each skill claims its facts were
verified against named upstream files and symbols. Reading-based review cannot
catch the failure mode that matters here. The 2026-09 review ran four passes,
each asking *"does the symbol exist?"* (yes) and *"did the line move?"* (no) --
neither question asks **which file the symbol lives in**. A mechanical scan
found 2 of 8 ``file::symbol`` citations naming the wrong file, and one line
citation that had already drifted +11 lines. This check is that scan.

Citations recognised
--------------------
* ``path/to/file.py::symbol``  -- ``symbol`` must be defined in *that* file.
* ``path/to/file.py:123``      -- the cited line must still carry content.
* ``path/to/file.py`` ... ``line 123`` (prose form) -- same rule.

Resolution is against a Hermes source tree at a fixed revision. By default the
revision is read from ``.github/upstream-drift.baseline`` so citations are always
checked against the revision the repo declares.

Usage
-----
    python tools/check_citation_integrity.py --src /path/to/hermes-agent
    python tools/check_citation_integrity.py --src ... --rev ce...  # override
    python tools/check_citation_integrity.py --selftest             # parser test

Exit code is 0 when every citation resolves, 1 otherwise. ``--src`` may also be
supplied via the ``HERMES_AGENT_SRC`` environment variable.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASELINE_FILE = REPO / ".github" / "upstream-drift.baseline"

_EXT = r"(?:py|ts|tsx|js|mjs|json|ya?ml|toml)"
SYM_RE = re.compile(r"`?([A-Za-z0-9_./-]+\.%s)`?::`?([A-Za-z_][A-Za-z0-9_]*)`?" % _EXT)
LIN_RE = re.compile(r"`?([A-Za-z0-9_./-]+\.%s)`?:(\d+)`?" % _EXT)
PROSE_RE = re.compile(r"`?([A-Za-z0-9_./-]+\.%s)`?[^\n]{0,48}?\blines?\s+~?(\d+)" % _EXT)

# Identifiers in a citing sentence that could confirm the cited line. snake_case
# and CamelCase, length >= 4, minus prose noise.
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")
_STOP = {
    "when", "with", "that", "this", "from", "into", "line", "lines", "code",
    "file", "skill", "hermes", "which", "where", "after", "before", "then",
    "than", "them", "they", "will", "must", "note", "only", "also", "same",
    "each", "some", "have", "has", "the", "and", "for", "not", "are", "its",
}


def _git(src: Path, *args: str) -> tuple[str, int]:
    # Encoding is explicit on purpose: the default (locale) codec is cp1252 on a
    # Windows host, which dies on the non-ASCII bytes in the Hermes tree. A dead
    # reader thread returns a None stdout rather than an error, so the return
    # value is coerced to "" as well -- a check must never crash on input it
    # exists to inspect.
    proc = subprocess.run(["git", "-C", str(src), *args],
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return proc.stdout or "", proc.returncode


def _show(src: Path, rev: str, path: str) -> list[str] | None:
    out, rc = _git(src, "show", "%s:%s" % (rev, path))
    return out.splitlines() if rc == 0 else None


def _defined_in(content: list[str], symbol: str) -> bool:
    pat = re.compile(
        r"(?m)^\s*(?:async\s+)?def\s+%s\b"
        r"|^\s*class\s+%s\b"
        r"|^\s*%s\s*[:=]"
        r"|^\s*(?:export\s+)?(?:const|let|var|function)\s+%s\b"
        % (re.escape(symbol), re.escape(symbol), re.escape(symbol), re.escape(symbol))
    )
    return bool(pat.search("\n".join(content)))


def _find_home(src: Path, rev: str, symbol: str) -> str:
    out, _ = _git(src, "grep", "-l", "-E",
                  r"(^|[^A-Za-z0-9_])(def|class|const|let|var|function)\s+%s\b" % re.escape(symbol),
                  rev, "--")
    hits = [ln.split(":", 1)[1] for ln in out.splitlines() if ":" in ln]
    hits = [h for h in hits if not h.startswith(("tests/", "test_"))]
    return hits[0] if hits else ""


def collect() -> dict:
    """Return {'syms': [...], 'lins': [...]} of (skill, path, target, skill_line, text)."""
    syms, lins = [], []
    for f in sorted(REPO.glob("skills/*/SKILL.md")):
        skill = f.parent.name
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for m in SYM_RE.finditer(line):
                syms.append((skill, m.group(1), m.group(2), i, line.strip()))
            for m in LIN_RE.finditer(line):
                lins.append((skill, m.group(1), int(m.group(2)), i, line.strip()))
            for m in PROSE_RE.finditer(line):
                if ":%s" % m.group(2) in line:      # already caught by LIN_RE
                    continue
                lins.append((skill, m.group(1), int(m.group(2)), i, line.strip()))
    return {"syms": syms, "lins": lins}


def verify(src: Path, rev: str) -> tuple[list[str], list[str], list[str]]:
    fails: list[str] = []
    warns: list[str] = []
    notes: list[str] = []
    data = collect()

    for skill, path, sym, ln, text in data["syms"]:
        content = _show(src, rev, path)
        if content is None:
            fails.append("%s:%d cites %s::%s but %s does not exist at %s"
                         % (skill, ln, path, sym, path, rev[:12]))
            continue
        if _defined_in(content, sym):
            notes.append("ok    %s::%s" % (path, sym))
        else:
            home = _find_home(src, rev, sym)
            fails.append("%s:%d cites %s::%s -- NOT defined there%s"
                         % (skill, ln, path, sym,
                            ("; actual home: %s" % home) if home else " (nowhere found)"))

    for skill, path, num, ln, text in data["lins"]:
        content = _show(src, rev, path)
        if content is None:
            fails.append("%s:%d cites %s:%d but %s does not exist at %s"
                         % (skill, ln, path, num, path, rev[:12]))
            continue
        if num < 1 or num > len(content):
            fails.append("%s:%d cites %s:%d but the file has only %d lines"
                         % (skill, ln, path, num, len(content)))
            continue
        actual = content[num - 1].strip()
        if not actual:
            fails.append("%s:%d cites %s:%d but that line is blank"
                         % (skill, ln, path, num))
            continue
        # The cited line ITSELF must carry a token from the citing sentence. A
        # wider window silently passes a line that has drifted a few rows -- the
        # exact failure this check exists to catch (it let a +11 drift through on
        # the installed revision). Drift-suspect is a warning, never a failure.
        idents = [w for w in _IDENT_RE.findall(text) if w.lower() not in _STOP]
        if idents and not any(w in content[num - 1] for w in idents):
            whole = "\n".join(content)
            moved = [j + 1 for j, l in enumerate(content)
                     if any(w in l for w in idents)]
            warns.append("%s:%d cites %s:%d (now: %r) -- DRIFT SUSPECT%s"
                         % (skill, ln, path, num, actual[:60],
                            ("; token appears at %s" % moved[:4]) if moved else ""))
        else:
            notes.append("ok    %s:%d -> %s" % (path, num, actual[:60]))
    return fails, warns, notes


def selftest() -> int:
    """Parser regression: synthetic text must yield the expected citations."""
    sample = (
        "see `agent/prompt_builder.py::_find_hermes_md` and `hermes_cli/config.py:2574`\n"
        "the impl lives in **`hermes_cli/main_desktop.py`** (`cmd_gui`, line ~1501)\n"
    )
    got = collect.__doc__  # keep flake honest; real work below
    syms = [(m.group(1), m.group(2)) for m in SYM_RE.finditer(sample)]
    lins = [(m.group(1), m.group(2)) for m in LIN_RE.finditer(sample)]
    prose = [(m.group(1), m.group(2)) for m in PROSE_RE.finditer(sample)]
    exp_s = [("agent/prompt_builder.py", "_find_hermes_md")]
    exp_l = [("hermes_cli/config.py", "2574")]
    exp_p = [("hermes_cli/main_desktop.py", "1501")]
    ok = syms == exp_s and lins == exp_l and prose == exp_p
    print("selftest:", "OK" if ok else "FAIL %r %r %r" % (syms, lins, prose))
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    src = None
    if "--src" in argv:
        src = Path(argv[argv.index("--src") + 1])
    else:
        env = os.environ.get("HERMES_AGENT_SRC")
        src = Path(env) if env else None
    if src is None:
        print("error: pass --src <hermes-agent clone> (or set HERMES_AGENT_SRC)", file=sys.stderr)
        return 2
    rev = argv[argv.index("--rev") + 1] if "--rev" in argv else None
    if rev is None:
        rev = BASELINE_FILE.read_text(encoding="utf-8").strip()
    if not (src / ".git").exists():
        print("error: %s is not a git clone" % src, file=sys.stderr)
        return 2

    _, rc = _git(src, "rev-parse", "--verify", rev + "^{commit}")
    if rc != 0:
        print("error: revision %s not found in %s" % (rev, src), file=sys.stderr)
        return 2
    # Guard against an incomplete/partial clone. If the commit resolves but its
    # tree cannot be read, every citation would report as broken -- a
    # false-positive storm that looks like a regression instead of a bad clone.
    # Fail loudly so infrastructure failure is never mistaken for a defect.
    _, rc = _git(src, "cat-file", "-e", rev + "^{tree}")
    if rc != 0:
        print(
            "error: cannot read the tree at %s in %s -- the clone is incomplete "
            "(partial clone missing its promisor remote, or a --no-checkout clone "
            "without objects). Re-clone before trusting any result." % (rev, src),
            file=sys.stderr,
        )
        return 2

    fails, warns, notes = verify(src, rev)
    data = collect()
    print("citation integrity vs %s (rev %s)" % (src, rev[:12]))
    print("  file::symbol : %d" % len(data["syms"]))
    print("  file:line    : %d" % len(data["lins"]))
    for n in notes:
        print("  " + n)
    for w in warns:
        print("  WARN  " + w)
    for f in fails:
        print("  FAIL  " + f)
    if fails:
        print("FAIL: %d citation(s) broken" % len(fails))
        return 1
    print("OK: all citations resolve (%d warning(s))" % len(warns))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
