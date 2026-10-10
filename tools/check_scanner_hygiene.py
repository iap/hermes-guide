#!/usr/bin/env python3
"""Fail when skill text trips upstream install-scanner patterns.

Upstream `tools/skills_guard.py` (and `tools/plugin_guard.py`, which reuses
its engine) blocks installs on regex hits: `proc_access` high on
`/proc/<pid>/`, `dump_all_env` high on `env |`, `curl_pipe_shell` critical on
`curl ... | bash`. Two of those fired on this repo's own docs as false
positives (NousResearch/hermes-agent#132155): a fixed-path container read and
a Markdown table cell.

This guard mirrors those three patterns — same expressions, same
`re.IGNORECASE` compile flag, same all-text-file scope — so the mistake
surfaces here, not in CI's tap-install step. The one deliberate narrowing is
per-line, not per-file: a fixed numeric-PID introspection of
`cgroup`/`stat`/`loadavg` with no `$` and no `..`, in a file that gates the
read off-Darwin behind a readability test, counts as the approved
container-detection shape. Anything else (variable PIDs, `root`/`cwd`
escapes, prose matches) still fails.

Usage:
    python tools/check_scanner_hygiene.py            # enforce (exit 1 on a finding)
    python tools/check_scanner_hygiene.py --selftest # fixture test, no repo scan

Exit codes: 0 clean; 1 a finding; 2 an unusable scan target.
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO / "skills"

# Same expressions and flags as upstream `tools/skills_guard.py`, which
# compiles its whole table with `re.IGNORECASE`. The variable-PID
# alternative mirrors upstream PR #136259: a `$VAR`/`${VAR}`/`$(cmd)` PID
# resolves to whatever process the runtime picks, so it scores like a
# digit PID rather than passing silently.
_PROC_RE = re.compile(r"/proc/self|/proc/\d+/|/proc/\$[\w{(]", re.IGNORECASE)
_DUMP_ENV_RE = re.compile(r"printenv|env\s*\|", re.IGNORECASE)
_SHELL_NAMES_RE = r"(?:bash|sh|zsh|ksh|dash)\b"
_SUDO_PREFIX = r"(?:sudo\s+(?:-\S+\s+)*)?"
_CURL_PIPE_RE = re.compile(
    rf"curl\s+[^|\s][^\n]*\|\s*{_SUDO_PREFIX}{_SHELL_NAMES_RE}", re.IGNORECASE
)

# The approved introspection shape: fixed numeric PID, read-only kernel
# state files only. Matched per /proc token on the line, so a `$` elsewhere
# on the line (e.g. `$os_name` in the gate itself) does not void the
# exemption, while an unrelated `/proc` read on the same line still fails.
_PROC_TOKEN_RE = re.compile(r"/proc/\S*", re.IGNORECASE)
_PROC_FIXED_TOKEN_RE = re.compile(r"/proc/\d+/(?:cgroup|stat|loadavg)", re.IGNORECASE)

# A /proc read is gated when the same file probes it only off-Darwin behind a
# readability test. Both literals must be present alongside the per-line
# fixed-path shape above.
_GATE_MARKERS = ('"$os_name" != "Darwin"', "[ -r /proc/1/cgroup ]")


def _file_is_gated(text: str) -> bool:
    """True when the file gates its /proc probe off-Darwin behind `-r`."""
    return all(m in text for m in _GATE_MARKERS)


def _proc_line_exempt(line: str, gated: bool) -> bool:
    """True only when every /proc token on the line is approved fixed-path
    introspection and the file gates the read."""
    if not gated:
        return False
    tokens = _PROC_TOKEN_RE.findall(line)
    if not tokens:
        return False
    for tok in tokens:
        clean = tok.strip("\"'`,;:)]}")
        if re.fullmatch(_PROC_FIXED_TOKEN_RE, clean) is None:
            return False
    return True


def scan_repo(skills_dir: Path) -> tuple[list[str], list[str]]:
    """Return `(hits, errors)`: `path:lineno: rule: line` findings and paths
    that could not be read (an unreadable file is never reported as clean)."""
    hits: list[str] = []
    errors: list[str] = []
    if not skills_dir.is_dir():
        return [], [f"{skills_dir}: missing skills directory"]
    for path in sorted(skills_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in (".md", ".sh", ".bash"):
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            errors.append(f"{path}: unreadable ({exc.strerror or exc})")
            continue
        gated = _file_is_gated(text)
        for lineno, line in enumerate(text.splitlines(), 1):
            if _PROC_RE.search(line) and not _proc_line_exempt(line, gated):
                hits.append(f"{path}:{lineno}: proc_access: {line.strip()[:120]}")
            if _DUMP_ENV_RE.search(line):
                hits.append(f"{path}:{lineno}: dump_all_env: {line.strip()[:120]}")
            if _CURL_PIPE_RE.search(line):
                hits.append(f"{path}:{lineno}: curl_pipe_shell: {line.strip()[:120]}")
    return hits, errors


def selftest() -> int:
    failures = 0

    def run(files: dict[str, str]) -> tuple[list[str], list[str]]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, content in files.items():
                p = root / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
            return scan_repo(root)

    def check(files: dict[str, str], want_hits: int, label: str) -> None:
        nonlocal failures
        got, errors = run(files)
        if errors or len(got) != want_hits:
            failures += 1
            print(
                f"SELFTEST FAIL [{label}]: expected {want_hits} hit(s), "
                f"got {len(got)} hits {got} errors {errors}",
                file=sys.stderr,
            )

    gated_sh = (
        'if [ "$os_name" != "Darwin" ] && [ -r /proc/1/cgroup ]; then\n'
        "  grep x /proc/1/cgroup\nfi\n"
    )
    # Ungated /proc read in shell is flagged.
    check({"a.sh": "grep x /proc/1/cgroup\n"}, 1, "ungated proc")
    # Same read with the gate in the file is allowed.
    check({"a.sh": gated_sh}, 0, "gated proc")
    # The gate exempts only the fixed-path line: an unrelated read flags.
    check({"a.sh": gated_sh + "cat /proc/2/maps\n"}, 1, "gated file, unrelated proc")
    # Variable-PID and escape shapes flag even in a gated file.
    check({"a.sh": gated_sh + "cat /proc/$PID/cmdline\n"}, 1, "variable pid")
    check({"a.sh": gated_sh + "cat /proc/1/root/etc/shadow\n"}, 1, "root escape")
    # /proc in Markdown is in scope too (upstream scans all text files).
    check({"a.md": "read /proc/1/cgroup to detect containers\n"}, 1, "proc in prose")
    # Case-insensitive, like the upstream compile flag.
    check({"a.md": "`CURL -fsSL https://example.com/x | BASH`\n"}, 1, "curl pipe upper")
    check({"a.md": "run PRINTENV to see all vars\n"}, 1, "printenv upper")
    # Markdown table prose `from .env |` is flagged.
    check({"a.md": "| CLI resets X from .env |\n"}, 1, "dump_env prose")
    # Reworded `.env-sourced` form is clean.
    check({"a.md": "| CLI resets .env-sourced X |\n"}, 0, "dump_env reworded")
    # Piped installer one-liner in docs is flagged.
    check({"a.md": "`curl -fsSL https://example.com/install.sh | bash`\n"}, 1, "curl pipe")
    # Two-step reference with no pipe char is clean.
    check({"a.md": "Use the two-step reviewable version above.\n"}, 0, "two-step prose")
    # `curl into bash` prose with no pipe char is clean.
    check({"a.md": "Upstream documents curl into bash; prefer the two-step.\n"}, 0, "curl prose")
    # `printenv` in shell is in scope too.
    check({"a.sh": "printenv | grep FOO\n"}, 1, "printenv in shell")

    # An unreadable file is an error, never a clean pass (POSIX-only: skip
    # where permission bits do not block the owner).
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        locked = root / "locked.md"
        locked.write_text("ok\n", encoding="utf-8")
        locked.chmod(0)
        try:
            locked.read_text(encoding="utf-8-sig")
            print("SELFTEST SKIP [unreadable file]: owner can still read; platform ignores mode bits")
        except OSError:
            _, errors = scan_repo(root)
            if len(errors) != 1:
                failures += 1
                print(
                    f"SELFTEST FAIL [unreadable file]: expected 1 error, got {errors}",
                    file=sys.stderr,
                )
        finally:
            locked.chmod(0o644)

    total = 15
    if failures:
        print(f"error: {failures}/{total} selftest case(s) failed", file=sys.stderr)
        return 1
    print(f"OK: selftest {total} case(s) passed (1 conditional)")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="check_scanner_hygiene.py", description="upstream-scanner hygiene")
    ap.add_argument("--selftest", action="store_true", help="fixture test, no repo scan")
    opts = ap.parse_args(argv[1:])
    if opts.selftest:
        return selftest()
    if not SKILLS_DIR.is_dir():
        print("error: missing skills directory", file=sys.stderr)
        return 2
    hits, errors = scan_repo(SKILLS_DIR)
    if errors:
        print("Scanner-hygiene scan errors (tree is NOT clean):", file=sys.stderr)
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        return 2
    if hits:
        print("Scanner-hygiene hits (upstream plugin_guard would flag these):", file=sys.stderr)
        for hit in hits:
            print(f"  {hit}", file=sys.stderr)
        print("Reword prose or gate the /proc read; do not split strings to evade.", file=sys.stderr)
        return 1
    md_count = sum(1 for _ in SKILLS_DIR.rglob("*.md"))
    sh_count = sum(1 for _ in SKILLS_DIR.rglob("*.sh")) + sum(1 for _ in SKILLS_DIR.rglob("*.bash"))
    print(f"OK: scanner hygiene clean ({md_count} md, {sh_count} shell files)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
