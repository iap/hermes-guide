#!/usr/bin/env python3
"""Fail when skill text trips upstream install-scanner patterns.

Upstream `tools/skills_guard.py` (and `tools/plugin_guard.py`, which reuses
its engine) blocks installs on regex hits: `proc_access` high on
`/proc/<pid>/`, `dump_all_env` high on `env |`, `curl_pipe_shell` critical on
`curl ... | bash`. Two of those fired on this repo's own docs as false
positives (NousResearch/hermes-agent#132155): a fixed-path container read and
a Markdown table cell.

This guard mirrors those three patterns so the mistake surfaces here, not in
CI's tap-install step. It is intentionally narrower than upstream: a gated
fixed-path `/proc/1/cgroup` read in the host-pressure probe is allowed, prose
matches are not.

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

_PROC_RE = re.compile(r"/proc/self|/proc/\d+/")
_DUMP_ENV_RE = re.compile(r"printenv|env\s*\|")
_SHELL_NAMES_RE = r"(?:bash|sh|zsh|ksh|dash)\b"
_SUDO_PREFIX = r"(?:sudo\s+(?:-\S+\s+)*)?"
_CURL_PIPE_RE = re.compile(rf"curl\s+[^|\s][^\n]*\|\s*{_SUDO_PREFIX}{_SHELL_NAMES_RE}")

# A /proc read is gated when the same file probes it only off-Darwin behind a
# readability test. Both literals must be present in the file; the per-line
# match below then counts as the approved container-detection shape.
_GATE_MARKERS = ('"$os_name" != "Darwin"', "[ -r /proc/1/cgroup ]")


def _file_is_gated(text: str) -> bool:
    return all(m in text for m in _GATE_MARKERS)


def scan_repo(skills_dir: Path) -> list[str]:
    """Return `path:lineno: rule: line` strings for every hygiene hit."""
    hits: list[str] = []
    if not skills_dir.is_dir():
        return ["__target__:0: missing skills directory"]
    for path in sorted(skills_dir.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix not in (".md", ".sh", ".bash"):
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        gated = _file_is_gated(text)
        for lineno, line in enumerate(text.splitlines(), 1):
            if _PROC_RE.search(line) and suffix in (".sh", ".bash") and not gated:
                hits.append(f"{path}:{lineno}: proc_access: {line.strip()[:120]}")
            if _DUMP_ENV_RE.search(line) and suffix == ".md":
                hits.append(f"{path}:{lineno}: dump_all_env: {line.strip()[:120]}")
            if _CURL_PIPE_RE.search(line) and suffix == ".md":
                hits.append(f"{path}:{lineno}: curl_pipe_shell: {line.strip()[:120]}")
    return hits


def selftest() -> int:
    failures = 0

    def run(files: dict[str, str]) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, content in files.items():
                p = root / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
            return scan_repo(root)

    cases = [
        # Ungated /proc read in shell is flagged.
        ({"a.sh": "grep x /proc/1/cgroup\n"}, 1, "ungated proc"),
        # Same read with both gate markers in the file is allowed.
        (
            {
                "a.sh": 'if [ "$os_name" != "Darwin" ] && [ -r /proc/1/cgroup ]; then\n'
                "  grep x /proc/1/cgroup\nfi\n"
            },
            0,
            "gated proc",
        ),
        # Markdown table prose `from .env |` is flagged.
        ({"a.md": "| CLI resets X from .env |\n"}, 1, "dump_env prose"),
        # Reworded `.env-sourced` form is clean.
        ({"a.md": "| CLI resets .env-sourced X |\n"}, 0, "dump_env reworded"),
        # Piped installer one-liner in docs is flagged.
        (
            {"a.md": "`curl -fsSL https://example.com/install.sh | bash`\n"},
            1,
            "curl pipe",
        ),
        # Two-step reference with no pipe char is clean.
        (
            {"a.md": "Use the two-step reviewable version above.\n"},
            0,
            "two-step prose",
        ),
        # `curl into bash` prose with no pipe char is clean.
        (
            {"a.md": "Upstream documents curl into bash; prefer the two-step.\n"},
            0,
            "curl prose without pipe",
        ),
    ]
    for files, want, label in cases:
        got = run(files)
        if len(got) != want:
            failures += 1
            print(
                f"SELFTEST FAIL [{label}]: expected {want} hit(s), got {len(got)}: {got}",
                file=sys.stderr,
            )
    if failures:
        print(f"error: {failures}/{len(cases)} selftest case(s) failed", file=sys.stderr)
        return 1
    print(f"OK: selftest {len(cases)} case(s) passed")
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
    hits = scan_repo(SKILLS_DIR)
    # The `__target__` sentinel reports an unusable tree, never a finding.
    if hits and hits[0].startswith("__target__:"):
        print(f"error: {hits[0]}", file=sys.stderr)
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
