#!/usr/bin/env python3
"""Every `hermes <subcommand>` cited in skills must exist on the live CLI.

Why this exists
---------------
Noob triage runs free-styled nonexistent subcommands (`hermes python set`,
`hermes db vacuum`, `hermes channels`) instead of routing through the guide.
Prose linters cannot see that: the strings are well-formed Markdown. This
check parses the cited (subcommand, sub-subcommand, flag) triples out of
`skills/*/SKILL.md` and resolves each against `hermes --help` trees.

Tiering (deliberate): this needs a live `hermes` binary, so it is CI-only,
like the dogfood check — not part of the hermetic `check_gates.py` tier.
If `hermes` is absent it skips cleanly (same contract as dogfood).

Depth (deliberate): top-level command + one subcommand level + flags at
both levels. Third-level positionals are skipped: deeper nesting churns
across versions and the failure mode observed was always depth ≤ 2.
Version skew: skills verified against older pins may cite renamed
commands. A failure names the skill line and the live usage, so the
fixer checks the skill's verified revision before "fixing" prose that
is correct for its pin.

Run: python3 tools/check_cli_surface.py
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO / "skills"

# Code spans like `hermes skills install --yes "x"` — capture the command
# words and --flags, stopping at placeholders, paths, and quoted values.
SPAN_RE = re.compile(r"`hermes\s+([^`]+)`")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
FLAG_RE = re.compile(r"--[A-Za-z][A-Za-z0-9_-]*")
SHORT_RE = re.compile(r"(?<!\S)-[A-Za-z](?!\S)")
BRACE_RE = re.compile(r"\{([^{}]+)\}")

# Global flags valid at any depth (from top-level `hermes --help` options).
GLOBAL_FLAGS = {
    "-h", "--help", "-z", "-m", "--provider", "--reasoning", "-t",
    "--resume", "--no-restore-cwd", "--in", "--continue", "--worktree",
    "--accept-hooks", "--skills", "--yolo", "--pass-session-id",
    "--ignore-user-config", "--ignore-rules", "--safe-mode", "--tui",
    "--native", "--cli", "--dev", "--version",
}

# Session slash commands live in another namespace, not the CLI parser.
SESSION_PREFIXES = ("/",)


# Plugin-provided commands never appear in `hermes --help` (only builtins
# do). Listed here with their subcommand sets so skill cites resolve.
# Scopes mirror checks._CHECKS; update together. Flags are the command's
# own options (`hermes guide --help` takes only -h); globals apply on top.
PLUGIN_COMMANDS = {
    "guide": ({"config", "mcp", "skills", "commands", "hooks", "plugins",
               "memories"}, set()),
}


# Hidden globals verified behaviorally: they work everywhere but are absent
# from `hermes --help` text (`hermes -p <profile> --version` is routine).
HIDDEN_GLOBAL_FLAGS = {"-p"}


# Tops newer than some supported installs, absent from the CI install pin
# (v2026.9.24; blocked on upstream #136259). Skipped ONLY at top-level
# absence — never a blanket pass, and never for subcommand or flag help
# failures: a present-but-broken subcommand is exactly what this check
# exists to catch. Re-check when the pin moves.
SKIP_IF_ABSENT = {"pm", "connectors"}


def _usage_names(help_text: str) -> set[str]:
    """Command/positional names from three argparse shapes.

    - Usage braces: ``{serve,add,remove}`` (subcommand helps).
    - 4-space command columns: ``    chat<2+ spaces>Interactive...``
      (top-level help lists subcommands this way, no braces). A parenthesized
      alias group (``desktop (gui)``) is tolerated after the name.
    Two-space positional labels (``log_name``) are deliberately NOT
    parsed: they name a parameter, not a runnable subcommand.
    Continuation lines use single-space gaps and never match: the name
    must be followed by two or more spaces (or a tab), optionally via an
    alias group.
    """
    names: set[str] = set()
    for m in BRACE_RE.finditer(help_text):
        # Option-value braces (`--source {all,hub}`) are flag values, not
        # runnable subcommands — only groups that do NOT follow a flag.
        if re.search(r"--[A-Za-z][A-Za-z0-9_-]*\s+$", help_text[:m.start()]):
            continue
        names.update(p.strip() for p in m.group(1).split(","))
    for m in re.finditer(
            r"(?m)^    ([a-z][a-z0-9_-]*)(?:\s+\([^)]*\))?(?:  +|\t)",
            help_text):
        names.add(m.group(1))
    return {n for n in names if n}


def _canonical_command(help_text: str) -> str | None:
    """Command name from a `usage: hermes <name>` line (alias resolution)."""
    m = re.search(r"(?m)^usage:\s*hermes\s+(\S+)", help_text)
    return m.group(1) if m else None


def _enum_values(help_text: str) -> set[str]:
    """Enum-like values from the positional-arguments section.

    Catches `log_name`-style value positionals (`agent, errors, gateway,
    gui, ...`): bare words from comma-separated fragments plus braced
    groups, quotes stripped. Deliberately lenient — it answers "is this a
    documented value" not "is it the right one".
    """
    section = re.split(
        r"(?m)^(?:options|optional arguments):", help_text, maxsplit=1)[0]
    m = re.search(r"(?m)^positional arguments:(.*)$", section, re.S)
    body = m.group(1) if m else ""
    out: set[str] = set()
    for m in BRACE_RE.finditer(body):
        out.update(p.strip().strip("'\"") for p in m.group(1).split(","))
    for frag in re.split(r",|\bor\b", body):
        tok = frag.strip().strip("'\"")
        m = re.match(r"^[a-z][a-z0-9_-]*", tok)
        if m:
            out.add(m.group(0))
    return {v for v in out if v}


def _usage_flags(help_text: str) -> set[str]:
    """Long flags anywhere plus short flags from usage brackets."""
    flags = set(FLAG_RE.findall(help_text))
    for m in re.finditer(r"\[(-\S+?)\]", help_text):
        for tok in m.group(1).split():
            if SHORT_RE.fullmatch(tok):
                flags.add(tok)
    return flags


def _run_help(args: list[str]) -> tuple[str | None, str | None]:
    """`hermes ... --help` as (stdout, error).

    error is None on success; otherwise "absent" (no executable) or the
    failure ("exit N", "timeout", "spawn error"). Callers distinguish a
    missing CLI (skip cleanly, dogfood contract) from a broken one (fail:
    in full tier the binary must answer).
    """
    exe = shutil.which("hermes")
    if exe is None:
        return None, "absent"
    try:
        proc = subprocess.run(
            [exe, *args, "--help"], capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except OSError as exc:
        return None, "spawn error: %s" % exc
    if proc.returncode != 0:
        return None, "exit %d" % proc.returncode
    return proc.stdout, None


# Flags taking a value: the following token is data, not a subcommand.
# `-z` takes the whole rest of the span (a free prompt string).
# `-p` verified behaviorally (`hermes -p <profile> ...` is routine) though
# absent from `--help` text — profile-prefixed cites must not read the
# profile name as the command.
VALUE_FLAGS = {
    "-m", "--provider", "--reasoning", "-t", "--resume", "--in",
    "--continue", "--skills", "--usage-file", "-p",
}

# Bracketed flag groups in skill examples (`[--for-tool X]`,
# `[--enable|--no-enable]`): unwrap before tokenizing so each alternative
# is validated. Brackets without a `--` inside (e.g. `[name]`) are left
# alone and fall through to the placeholder path below.
BRACKET_RE = re.compile(r"\[([^\[\]]*--[^\[\]]*)\]")


def _cite_parts(span: str) -> tuple[list[str], list[str]] | None:
    """Split a span body into (positionals, flags); None when not a command."""
    if span.startswith(SESSION_PREFIXES):
        return None
    span = BRACKET_RE.sub(lambda m: m.group(1).replace("|", " "), span)
    tokens = re.findall(r"<[^>]*>|[^\s]+", span)
    pos: list[str] = []
    flags: list[str] = []
    skip_next = False
    prev_flag = False
    for tok in tokens:
        if skip_next:
            skip_next = False
            prev_flag = False
            continue
        if tok == "-z":
            break  # free prompt string follows; nothing after is a command
        if tok in VALUE_FLAGS:
            skip_next = True
            prev_flag = False
            continue
        if tok.startswith("<") or "/" in tok or "\\" in tok or "." in tok:
            if tok.startswith("-"):
                flags.append(tok)
                prev_flag = True
            else:
                prev_flag = False
            continue  # placeholder, path, dotted value: not verifiable here
        if tok.startswith("--") or (tok.startswith("-") and len(tok) == 2):
            flags.append(tok)
            prev_flag = True
        elif WORD_RE.fullmatch(tok):
            # An ALLCAPS token right after a flag is that flag's value
            # (`[--for-tool X]`), not a subcommand.
            if prev_flag and re.fullmatch(r"[A-Z][A-Z0-9_]*", tok):
                prev_flag = False
                continue
            pos.append(tok)
            prev_flag = False
        # Anything else ($VAR, values, operators) is out of scope.
    if not pos:
        return None
    return pos[:3], flags


# A cite inside a negation ("there is no `hermes voice status`", "never
# run `hermes x`") discusses a non-command, so there is nothing to resolve.
# The negation governs its sentence: "There is no A, B, or C" skips all
# three, while "not installed. Run X" still checks X (own sentence). A
# contrast marker (but/yet/however/except/instead) ends the scope, so
# "not X but Y" checks Y.
# Limitation, documented: "do not run X unless Y" stays skipped even
# though X is real there. The D5 rule targets endorsed fix-path commands;
# meta-discussion about absent commands is out of scope.
NEG_RE = re.compile(
    r"\b(no|not|never|n't|without|instead of|rather than|isn't|aren't"
    r"|don't|doesn't|can't|cannot|won't|avoid)\b", re.I)
SENTENCE_RE = re.compile(r"[.!?\n]+")
CONTRAST_RE = re.compile(
    r"\b(?:but|yet|however|although|though|while|whereas|except"
    r"|instead)\b", re.I)


def _negated(line: str, pos: int) -> bool:
    """True when a negator governs the span starting at pos."""
    # Mask code spans with equal-length blanks first: a period inside a
    # span (``config.yaml`, `v1.2.0`) is not a sentence boundary, and
    # positions stay valid because the mask preserves length.
    masked = re.sub(r"`[^`]*`", lambda m: " " * len(m.group(0)), line)
    start = 0
    for m in SENTENCE_RE.finditer(masked):
        end = m.end()
        if start <= pos < end or (pos == end and end == len(line)):
            break
        start = end
    else:
        end = len(line)
    segment = masked[start:pos]
    segment = CONTRAST_RE.split(segment)[-1]
    return NEG_RE.search(segment) is not None


def collect() -> list[tuple[str, int, str, list[str], list[str]]]:
    """(skill, line, span, positionals, flags) for every hermes cite."""
    out = []
    for f in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        skill = f.parent.name
        for i, line in enumerate(
                f.read_text(encoding="utf-8").splitlines(), 1):
            for m in SPAN_RE.finditer(line):
                if _negated(line, m.start()):
                    continue
                rest = m.group(1).strip()
                if not rest:
                    continue
                parsed = _cite_parts(rest)
                if parsed is None:
                    continue
                pos, flags = parsed
                out.append((skill, i, m.group(0), pos, flags))
    return out


def verify(cites) -> tuple[list[str], str]:
    """Resolve cites against the live CLI. Returns (failures, summary)."""
    top_text, top_err = _run_help([])
    if top_text is None:
        if top_err == "absent":
            return [], "SKIP: no hermes on PATH"
        return ["hermes --help failed (%s): cannot verify" % top_err], ""
    top_cmds = _usage_names(top_text)
    top_flags = _usage_flags(top_text) | GLOBAL_FLAGS | HIDDEN_GLOBAL_FLAGS
    sub_cache: dict[tuple[str, ...], tuple[set[str], set[str]]] = {}
    text_cache: dict[tuple[str, ...], str] = {}
    err_cache: dict[tuple[str, ...], str] = {}
    failures: list[str] = []
    checked = 0
    skipped: list[str] = []

    def text_of(cmd: list[str]) -> str | None:
        """Raw `--help` text, fetched once per command path (each launch
        pays the CLI startup prelude, so every duplicate fetch costs
        seconds — this cache is what keeps a full-tree run in budget).
        Failures are recorded too: without that, every later cite of a
        broken command relaunches a 60-second timeout each."""
        key = tuple(cmd)
        if key not in text_cache and key not in err_cache:
            text, err = _run_help(cmd)
            if err is not None:
                err_cache[key] = err
            else:
                text_cache[key] = text or ""
        return text_cache.get(key)

    def help_err(cmd: list[str]) -> str | None:
        """Failure reason for a `--help` call, or None when it succeeded."""
        text_of(cmd)
        return err_cache.get(tuple(cmd))

    def sub_tree(cmd: list[str]) -> tuple[set[str], set[str]]:
        key = tuple(cmd)
        if key not in sub_cache:
            text = text_of(cmd)
            sub_cache[key] = (
                (_usage_names(text), _usage_flags(text) | GLOBAL_FLAGS
                 | HIDDEN_GLOBAL_FLAGS)
                if text is not None else (set(), set()))
        return sub_cache[key]

    def canonical(cmd: str) -> str | None:
        """Resolve aliases and hidden commands via their own usage line.

        `<alias> --help` prints `usage: hermes <canonical>` (e.g.
        memory-graph → journey); a missing command errors out (None).
        Accepts the canonical name when its help parses to a non-empty
        tree — covering alias chains into commands hidden from top help.
        """
        text = text_of([cmd])
        if text is None:
            return None
        name = _canonical_command(text)
        if name is None:
            return None
        if name == cmd or name in top_cmds:
            return name
        names, flags = sub_tree([name])
        return name if names or flags else None

    for skill, ln, span, pos, flags in cites:
        top = pos[0]
        if top in PLUGIN_COMMANDS:
            checked += 1
            scopes, allowed = PLUGIN_COMMANDS[top]
            if len(pos) > 1 and pos[1] not in scopes:
                failures.append(
                    "%s:%d: %s — unknown scope (have for %s: %s)" %
                    (skill, ln, span, top, ", ".join(sorted(scopes))))
                continue
            for flag in flags:
                if flag not in allowed and flag not in top_flags:
                    failures.append(
                        "%s:%d: %s — unknown flag (have for %s: %s)" %
                        (skill, ln, span, top, _sample(allowed, flag)))
            continue
        canon = top if top in top_cmds else canonical(top)
        if canon is None:
            if top in SKIP_IF_ABSENT:
                skipped.append(top)
                continue
            err = help_err([top])
            if err is not None:
                failures.append(
                    "%s:%d: %s — `hermes %s --help` failed (%s)" %
                    (skill, ln, span, top, err))
            else:
                failures.append(
                    "%s:%d: %s — unknown top-level command (have: %s)" %
                    (skill, ln, span, _sample(top_cmds, top)))
            continue
        checked += 1
        names, available = sub_tree([canon])
        sub = pos[1] if len(pos) > 1 else None
        if sub is not None and sub not in names:
            # Maybe an enum value (`logs gui`), not a subcommand. The top
            # text is already cached — no extra launch.
            if sub not in _enum_values(text_of([canon]) or ""):
                err = help_err([canon])
                if err is not None:
                    failures.append(
                        "%s:%d: %s — `hermes %s --help` failed (%s)" %
                        (skill, ln, span, canon, err))
                else:
                    failures.append(
                        "%s:%d: %s — unknown subcommand (have for %s: %s)" %
                        (skill, ln, span, canon, _sample(names, sub)))
                continue
            sub = None  # enum value accepted; no deeper flags to check
        for flag in flags:
            if flag in available or flag in top_flags:
                continue
            # Subcommand-specific flags live one depth deeper — fetch that
            # help only now that a flag actually missed up top.
            if sub is not None:
                err = help_err([canon, sub])
                if err is not None:
                    failures.append(
                        "%s:%d: %s — `hermes %s %s --help` failed (%s)" %
                        (skill, ln, span, canon, sub, err))
                    break
                if flag in sub_tree([canon, sub])[1]:
                    continue
            failures.append(
                "%s:%d: %s — unknown flag (have for %s: %s)" %
                (skill, ln, span, canon, _sample(available, flag)))
    summary = "OK: %d cited command(s) resolve against the live CLI" % checked
    if skipped:
        summary += " (%d skipped as absent here: %s)" % (
            len(skipped), ", ".join(sorted(set(skipped))))
    return failures, summary


def _sample(options: set[str], want: str, limit: int = 8) -> str:
    """A short have-list biased toward near-matches of the miss."""
    import difflib
    close = difflib.get_close_matches(want, sorted(options), n=3, cutoff=0.5)
    rest = [o for o in sorted(options) if o not in close]
    return ", ".join(close + rest[: max(0, limit - len(close))]) or "(none)"


def _selftest() -> int:
    top = "usage: hermes [-h] {config,skills,auth} ...\n  config  C\n  skills  S\noptions:\n  -h\n  --yes\n"
    four = "positional arguments:\n  <command>  C\n    chat                Interactive\n    model               Select\n                        model fails\n"
    assert _usage_names(top) >= {"config", "skills", "auth"}
    assert _usage_names(four) == {"chat", "model"}
    assert "--yes" in _usage_flags(top) and "-h" in _usage_flags(top)
    assert _cite_parts("skills install --yes foo") == (
        ["skills", "install", "foo"], ["--yes"])  # depth-3+ positionals
    # recorded but unchecked: only top + subcommand levels are verified.
    assert _cite_parts("config path") == (["config", "path"], [])
    assert _cite_parts("/reload-mcp") is None
    assert _cite_parts("guide <scope>") == (["guide"], [])
    assert NEG_RE.search("there is no `hermes voice status` here")
    assert not NEG_RE.search("run `hermes guide` to check")
    assert _negated("There is no `a`, `b`, or `c`.", 25)
    assert not _negated("not installed. Run `hermes x` now", 19)
    assert _negated("not `a` but `b`", 4)
    assert not _negated("not `a` but `b`", 12)
    # Dots inside spans are not sentence boundaries.
    assert _negated("There is no `a.b`, or `c`.", 22)
    assert _cite_parts("hooks test <event> [--for-tool X]") == (
        ["hooks", "test"], ["--for-tool"])
    assert _cite_parts("plugins install [--enable|--no-enable]") == (
        ["plugins", "install"], ["--enable", "--no-enable"])
    assert _cite_parts("-p work config path") == (["config", "path"], [])
    optvals = ("usage: hermes x [-h] [--source {all,hub}] ...\n"
               "  other  O\n")
    assert _usage_names(optvals) == set()
    print("OK: cli-surface selftest")
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
    # Transparency, not validation: when several hermes executables share
    # PATH, the log must show which one the cites were checked against.
    # (PATH-first is correct for CI, where the install step owns PATH;
    # on multi-install dev machines, read this line before trusting a pass.)
    exe = shutil.which("hermes")
    if exe:
        print("hermes under check: %s" % exe)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
